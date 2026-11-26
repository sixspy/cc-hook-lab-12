# -*- coding: utf-8 -*-
"""hook-12-停用端点联拒 · 双会话并发打同锁脚本。

用法：
    cd backend && .venv/bin/python scripts/双会话同锁.py

做什么：
  1. 父进程准备独立临时 SQLite 库与端点 ep-dual；
  2. 另起两个操作系统进程（两会话）：
       - 会话甲：80 次并发节奏的入队锤（本进程内多线程）；
       - 会话乙：40 次启用/停用翻转；
     两个进程不共享 threading.RLock，只靠 SQLite 文件锁 +
     BEGIN IMMEDIATE + busy_timeout=8000 打同一把库锁；
  3. 断言：没有 database is locked 等非预期错误；成功返回数 == 库内行数；
  4. 收尾把端点停用，再开第三个会话入队，必须被中文联拒：
     正式待投不增、停用归档 +1。

退出码 0 表示全部断言通过。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

后端根 = Path(__file__).resolve().parents[1]
骨签 = "hook-12-停用端点联拒"


# ---------------- 子进程入口 ----------------

def 子_入队锤(库目录: str, 键: str, 总数: int) -> int:
    os.environ["数据目录"] = 库目录
    sys.path.insert(0, str(后端根))
    from app.services import 入队
    from app.modules.停用联拒 import 停用联拒错误

    锁 = threading.Lock()
    成功: list[str] = []
    联拒 = 0
    错误: list[str] = []

    def one(i: int) -> None:
        nonlocal 联拒
        try:
            r = 入队.建事件({
                "事件类型": f"dual.enq.{i}",
                "端点键": 键,
                "事件号": f"EVT-DUAL-{os.getpid()}-{i}",
            })
            with 锁:
                成功.append(r["事件号"])
        except 停用联拒错误:
            with 锁:
                联拒 += 1  # 翻转到停用瞬间的合法拒绝
        except ValueError:
            with 锁:
                联拒 += 1
        except Exception as e:  # noqa: BLE001
            with 锁:
                错误.append(repr(e))

    # 进程内也用多线程，尽量与翻转操作抢同一个立即事务票。
    ts = [threading.Thread(target=one, args=(i,)) for i in range(总数)]
    for i, t in enumerate(ts):
        t.start()
        if i % 8 == 0:
            time.sleep(0.002)  # 轻微错峰，制造真实交错而非同时暴冲
    for t in ts:
        t.join(15)

    print("RESULT_JSON=" + json.dumps(
        {"角色": "会话甲-入队锤", "成功": 成功, "联拒": 联拒, "错误": 错误},
        ensure_ascii=False))
    return 0 if not 错误 else 2


def 子_翻转锤(库目录: str, 键: str, 总数: int) -> int:
    os.environ["数据目录"] = 库目录
    sys.path.insert(0, str(后端根))
    from app.services import 端点

    错误: list[str] = []
    for i in range(总数):
        try:
            端点.改启用(键, i % 2 == 0)  # 最后一次为 True（启用），父进程随后自己停用
            time.sleep(0.004)
        except Exception as e:  # noqa: BLE001
            错误.append(repr(e))
    print("RESULT_JSON=" + json.dumps(
        {"角色": "会话乙-名册翻转", "翻转次数": 总数, "错误": 错误},
        ensure_ascii=False))
    return 0 if not 错误 else 2


def 子_单次联拒(库目录: str, 键: str) -> int:
    os.environ["数据目录"] = 库目录
    sys.path.insert(0, str(后端根))
    from app.services import 入队
    from app.modules.停用联拒 import 停用联拒错误

    号 = f"EVT-DUAL-FINAL-{os.getpid()}"
    try:
        入队.建事件({"事件类型": "dual.final", "端点键": 键, "事件号": 号})
    except 停用联拒错误 as e:
        print("RESULT_JSON=" + json.dumps(
            {"联拒": True, "事件号": 号, "拒因": e.拒因, "归档号": e.归档号},
            ensure_ascii=False))
        return 0
    except ValueError as e:
        print("RESULT_JSON=" + json.dumps(
            {"联拒": True, "事件号": 号, "拒因": str(e), "归档号": ""},
            ensure_ascii=False))
        return 0
    print("RESULT_JSON=" + json.dumps({"联拒": False, "事件号": 号}, ensure_ascii=False))
    return 0


# ---------------- 父进程编排 ----------------

def _跑子进程(args: list[str], env: dict) -> tuple[int, dict | None, str]:
    p = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args],
        env=env, capture_output=True, text=True, timeout=120,
    )
    result = None
    for line in p.stdout.splitlines():
        if line.startswith("RESULT_JSON="):
            result = json.loads(line.split("=", 1)[1])
    return p.returncode, result, p.stdout + p.stderr


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="hook12_双会话_")
    os.environ["数据目录"] = tmp
    sys.path.insert(0, str(后端根))

    from app import seed, db
    from app.services import 端点

    seed.初始化库()
    键 = "ep-dual"
    端点.登记({"端点键": 键, "名称": "双会话同锁端点",
               "回调URL": "https://example.local/hooks/dual"})

    env = {**os.environ, "数据目录": tmp, "PYTHONPATH": str(后端根)}

    print(f"[{骨签}] 独立库目录：{tmp}")
    print("启动两个操作系统会话：甲=入队锤(80)，乙=启用灯翻转(40) …")
    t0 = time.time()
    r1 = subprocess.Popen(
        [sys.executable, __file__, "enqueue", tmp, 键, "80"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    r2 = subprocess.Popen(
        [sys.executable, __file__, "toggle", tmp, 键, "40"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out1, err1 = r1.communicate(timeout=120)
    out2, err2 = r2.communicate(timeout=120)
    耗时 = time.time() - t0

    def 解析(out: str) -> dict:
        for line in out.splitlines():
            if line.startswith("RESULT_JSON="):
                return json.loads(line.split("=", 1)[1])
        return {}

    j1, j2 = 解析(out1), 解析(out2)
    print("会话甲：", json.dumps(j1, ensure_ascii=False)[:400])
    print("会话乙：", json.dumps(j2, ensure_ascii=False)[:400])
    if r1.returncode != 0 or r2.returncode != 0:
        print("子进程异常输出：\n", err1[-2000:], err2[-2000:])
        print("❌ 有会话以非零码退出（可能出现 database is locked）")
        return 1

    错误 = list(j1.get("错误", [])) + list(j2.get("错误", []))
    if 错误:
        print("❌ 并发下出现非预期错误：", 错误[:5])
        return 1
    if any("locked" in str(x).lower() for x in 错误):
        print("❌ 出现 database is locked")
        return 1

    成功号 = j1.get("成功", [])
    conn = db.连接()
    try:
        库行数 = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 事件号 LIKE 'EVT-DUAL-%'"
        ).fetchone()["n"]
        待投数 = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=? AND 状态='待投'", (键,)
        ).fetchone()["n"]
    finally:
        conn.close()

    if int(库行数) != len(成功号):
        print(f"❌ 同成同败破坏：成功返回 {len(成功号)} 条，库内 EVT-DUAL 行 {库行数} 条")
        return 1
    print(f"✅ 双会话锤完成：成功入队 {len(成功号)}，合法联拒 {j1.get('联拒')}，"
          f"库内行数 {库行数} == 成功数，耗时 {耗时:.1f}s，无 locked/无错误")

    # —— 收尾：父会话停用，第三个 OS 会话尝试入队，必须被联拒 ——
    端点.改启用(键, False)
    conn = db.连接()
    try:
        前待投 = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=? AND 状态='待投'", (键,)
        ).fetchone()["n"]
        前归档 = conn.execute("SELECT COUNT(*) AS n FROM 停用归档").fetchone()["n"]
    finally:
        conn.close()

    code, j3, raw = _跑子进程(["once", tmp, 键], env)
    if code != 0 or not j3 or not j3.get("联拒"):
        print("❌ 停用后新会话入队未被联拒：", raw[-1000:])
        return 1
    if "停用" not in (j3.get("拒因") or "") or "拒" not in (j3.get("拒因") or ""):
        print("❌ 拒因不含中文停用/拒字样：", j3)
        return 1

    conn = db.连接()
    try:
        后待投 = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=? AND 状态='待投'", (键,)
        ).fetchone()["n"]
        后归档 = conn.execute("SELECT COUNT(*) AS n FROM 停用归档").fetchone()["n"]
        正式读集 = [dict(r) for r in conn.execute(
            "SELECT e.事件号 FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=1 AND e.事件号=?", (j3["事件号"],)
        ).fetchall()]
    finally:
        conn.close()

    if 后待投 != 前待投:
        print(f"❌ 停用端入队推高正式待投：{前待投} → {后待投}")
        return 1
    if 后归档 != 前归档 + 1:
        print(f"❌ 归档轨未恰好 +1：{前归档} → {后归档}")
        return 1
    if 正式读集:
        print("❌ 被拒事件混进正式启用端读集合")
        return 1

    print("✅ 第三会话停用后入队被中文联拒：")
    print("   拒因：" + j3["拒因"])
    print(f"   归档号：{j3.get('归档号')}；正式待投不增（{前待投}），"
          f"归档 {前归档}→{后归档}，正式读集无该事件")
    print("\n🎉 双会话同锁脚本全部通过：同票串行、同成同败、两轨分离。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "enqueue":
        raise SystemExit(子_入队锤(sys.argv[2], sys.argv[3], int(sys.argv[4])))
    if len(sys.argv) >= 2 and sys.argv[1] == "toggle":
        raise SystemExit(子_翻转锤(sys.argv[2], sys.argv[3], int(sys.argv[4])))
    if len(sys.argv) >= 2 and sys.argv[1] == "once":
        raise SystemExit(子_单次联拒(sys.argv[2], sys.argv[3]))
    raise SystemExit(main())
