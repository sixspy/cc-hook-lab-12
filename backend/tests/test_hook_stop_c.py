# -*- coding: utf-8 -*-
"""骨签 hook-12-停用端点联拒 · 争用失败测丙

丙：改停用的瞬间并发入队，check-then-act 的缝会漏拦。
救绿服务：并发同锁/同票原子事务（app/modules/并发投递锁 + 入队/端点两侧同锁）。

手法：在测试里给入队连接装一道「读完启用灯之后、写下一行之前」的栅栏，
确定性地把并发缝撑大。现状停用会话会在入队联票中途提交（overtake=True），
随后入队仍写入待投 → 漏拦，本文件必须见红。
"""
import os
import sqlite3
import tempfile
import threading
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="hook_c_")
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest  # noqa: E402

from app import db, seed  # noqa: E402
from app.services import 入队, 端点  # noqa: E402


@pytest.fixture()
def 库(tmp_path, monkeypatch):
    路径 = tmp_path / "hook_stop_c.db"
    monkeypatch.setattr(db, "库路径", 路径)
    seed.初始化库()
    yield 路径


def _装栅栏连接(monkeypatch, ctl):
    """把 app.services.入队.连接 换成带栅栏的连接工厂。"""

    class GatedConn(sqlite3.Connection):
        def execute(self, sql, params=()):  # type: ignore[override]
            if "FROM 投递端点" in sql:
                cur = super().execute(sql, params)
                self._读过端点 = True
                return cur
            if getattr(self, "_读过端点", False) and not getattr(self, "_已过栅栏", False):
                self._已过栅栏 = True
                ctl["at"].set()
                ctl["gate"].wait(5)
            return super().execute(sql, params)

    def 工厂():
        conn = sqlite3.connect(str(db.库路径), factory=GatedConn, timeout=8)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=OFF")
        return conn

    monkeypatch.setattr(入队, "连接", 工厂)


def _跑一次交错(键: str, monkeypatch):
    """返回 (overtake, worker结果, worker异常)。"""
    ctl = {"gate": threading.Event(), "at": threading.Event()}
    _装栅栏连接(monkeypatch, ctl)

    box = {}

    def worker():
        try:
            box["ok"] = 入队.建事件(
                {"事件类型": "race.c", "端点键": 键, "事件号": "EVT-C-GATE"}
            )
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=worker)
    th.start()
    assert ctl["at"].wait(3), "入队线程未到达栅栏（可能未读到端点查询）"

    done = threading.Event()

    def disabler():
        try:
            端点.改启用(键, False)
        except Exception as e:  # noqa: BLE001
            box["disable_err"] = e
        finally:
            done.set()

    td = threading.Thread(target=disabler)
    td.start()
    overtake = done.wait(0.8)  # 停用能否在入队持票中途提交
    ctl["gate"].set()
    th.join(6)
    td.join(6)
    return overtake, box


def test_丙_停用不得在入队联票中途插队提交(库, monkeypatch):
    端点.登记({"端点键": "ep-c1", "名称": "丙1", "回调URL": "https://x/c1"})
    overtake, box = _跑一次交错("ep-c1", monkeypatch)
    # 红：现状没有同锁，停用在缝里提交，overtake=True。
    assert overtake is False, (
        "停用会话在入队「读启用→写入」联票中途提交，存在并发漏拦窗口"
    )
    # 绿态串行顺序应是：入队整票先提交（当时仍启用），停用随后提交。
    assert "err" not in box, box.get("err")


def test_丙_若停用已先提交_栅栏后入队不得落正式待投(库, monkeypatch):
    """漏拦不变量：一旦停用先于入队写入提交，该入队必须被拒/归档，正式待投不增。"""
    端点.登记({"端点键": "ep-c2", "名称": "丙2", "回调URL": "https://x/c2"})
    overtake, box = _跑一次交错("ep-c2", monkeypatch)

    conn = db.连接()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键='ep-c2' AND 状态='待投'"
        ).fetchone()["n"]
        enabled = conn.execute(
            "SELECT 启用 FROM 投递端点 WHERE 端点键='ep-c2'"
        ).fetchone()["启用"]
    finally:
        conn.close()

    assert int(enabled) == 0
    if overtake:
        # 旧代码确定性走到这里：停用先提交，入队仍写待投 -> n==1，判红。
        assert n == 0, f"并发漏拦：停用已先提交，仍有 {n} 行落正式待投"
        assert "ok" not in box


def test_丙_多线程同锁打满无漏拦无锁错误(库):
    """真实并发锤：同锁串行化后，不允许 database is locked 逃逸，成功数与落库一致。"""
    端点.登记({"端点键": "ep-c3", "名称": "丙3", "回调URL": "https://x/c3"})
    端点.改启用("ep-c3", True)

    错误 = []
    成功号 = []
    锁 = threading.Lock()

    def enq(i):
        try:
            r = 入队.建事件(
                {"事件类型": f"hammer.{i}", "端点键": "ep-c3",
                 "事件号": f"EVT-C-{i}"}
            )
            with 锁:
                成功号.append(r["事件号"])
        except ValueError:
            pass  # 停用瞬间的合法拒绝
        except Exception as e:  # noqa: BLE001
            with 锁:
                错误.append(repr(e))

    def toggle():
        for i in range(30):
            try:
                端点.改启用("ep-c3", i % 2 == 0)
            except Exception as e:  # noqa: BLE001
                with 锁:
                    错误.append(repr(e))

    ts = [threading.Thread(target=enq, args=(i,)) for i in range(60)]
    tt = threading.Thread(target=toggle)
    for t in ts:
        t.start()
    tt.start()
    for t in ts:
        t.join(10)
    tt.join(10)

    assert not 错误, f"并发下出现非预期错误（如 database is locked）: {错误[:3]}"
    conn = db.连接()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 事件号 LIKE 'EVT-C-%'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert n == len(成功号), "返回成功数与落库行数不一致，违反同成同败"
