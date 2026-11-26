# -*- coding: utf-8 -*-
"""骨签 hook-12-停用端点联拒 · 失败测甲

甲：端点名册把回调停用后，灌队/入队不得让「正式待投」行仍增。
救绿服务：入队服务（app/services/入队.py）＋正式队列读集合与只读归档轨。
本文件在未挂「停用联拒」前必须见红。
"""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="hook_a_")
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest  # noqa: E402

from app import db, seed  # noqa: E402
from app.services import 入队, 端点, 签名目录, 投递, 死信  # noqa: E402

骨签 = "hook-12-停用端点联拒"


@pytest.fixture()
def 库(tmp_path, monkeypatch):
    路径 = tmp_path / "hook_stop_a.db"
    monkeypatch.setattr(db, "库路径", 路径)
    seed.初始化库()
    yield 路径


def 造停用灌队事故(键: str = "ep-stop-a", 条数: int = 3) -> str:
    """夹具动作：先登记并停用端点，再把事件灌入待投，造「停用端仍有入队」事故。"""
    端点.登记({"端点键": 键, "名称": "停用甲", "回调URL": "https://x/a"})
    端点.改启用(键, False)
    t = "2026-01-01T00:00:00Z"
    conn = db.连接()
    try:
        for i in range(条数):
            conn.execute(
                "INSERT INTO 事件(事件号,事件类型,端点键,载荷摘要,优先级,状态,入队时,更新时)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"ACC-A-{i}", "acc.a", 键, f"a-{i}", "普通", "待投", t, t),
            )
        conn.commit()
    finally:
        conn.close()
    return 键


def 待投行数(键: str) -> int:
    conn = db.连接()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=? AND 状态='待投'", (键,)
        ).fetchone()["n"]
    finally:
        conn.close()


def test_甲_事故夹具确实造出停用端待投行(库):
    """自证事故夹具：物理表里确有停用端待投行（否则后面的红没有意义）。"""
    键 = 造停用灌队事故()
    assert 待投行数(键) == 3


def test_甲_停用端灌队后正式队列不得仍增(库):
    """核心红：事故灌队后，页面对应的正式事件队列读集合不得容纳停用端行。

    现状：签名目录.事件列表()  SELECT * FROM 事件  把事故行也当正式队列，
    于是「停用端入队后待投行仍增」。本断言必须先红。
    """
    键 = 造停用灌队事故()
    正式 = 签名目录.事件列表()
    事故行 = [e for e in 正式 if e["端点键"] == 键]
    assert 事故行 == [], (
        f"停用端 {键} 的 {len(事故行)} 行混进正式队列，待投行仍增；"
        "正式队列必须改读启用端点集合"
    )


def test_甲_正式入队停用端点被中文拒绝且不增行(库):
    端点.登记({"端点键": "ep-a2", "名称": "甲2", "回调URL": "https://x/a2"})
    端点.改启用("ep-a2", False)
    before = 待投行数("ep-a2")
    with pytest.raises(ValueError) as ei:
        入队.建事件({"事件类型": "a.x", "端点键": "ep-a2", "事件号": "EVT-A-NO"})
    信息 = str(ei.value)
    assert "停用" in 信息 and "拒" in 信息
    assert 待投行数("ep-a2") == before == 0


def test_甲_拒因中文落只读归档且不混正式集合(库):
    """停用端入队被拒后，须在分开的只读归档轨留下成败=拒与中文拒因。"""
    端点.登记({"端点键": "ep-a3", "名称": "甲3", "回调URL": "https://x/a3"})
    端点.改启用("ep-a3", False)
    with pytest.raises(ValueError):
        入队.建事件({"事件类型": "a.arc", "端点键": "ep-a3", "事件号": "EVT-A-ARC"})

    归档 = 签名目录.停用归档列表()
    assert len(归档) == 1, "停用端被拒入队必须双写到只读归档轨"
    row = 归档[0]
    assert row["端点键"] == "ep-a3"
    assert int(row["入队成败"]) == 0
    assert "停用" in row["拒因"] and "拒" in row["拒因"]
    # 归档/影子不得混进正式集合
    正式号 = {e["事件号"] for e in 签名目录.事件列表()}
    assert "EVT-A-ARC" not in 正式号
    assert all(e["端点键"] != "ep-a3" for e in 签名目录.事件列表())


def test_甲_停用端死信重投不得部分提交回待投(库):
    """死信重投也是回待投的入队面：停用端点必须在翻状态前同票拒绝，不得先 commit。"""
    ev = 入队.建事件({"事件类型": "requeue.fail", "端点键": "ep-billing", "载荷摘要": "rq"})
    eid = ev["事件号"]
    结局 = None
    for _ in range(6):
        r = 投递.投递一次(eid, 强制失败=True)
        结局 = r.get("事件状态")
        if 结局 == "死信":
            break
    assert 结局 == "死信"
    assert 签名目录.事件一条(eid)["状态"] == "死信"

    端点.改启用("ep-billing", False)
    with pytest.raises(ValueError):
        死信.重投(eid)

    # 现状：重投先把 事件 改成待投并 commit，随后投递才报停用，造成待投行虚增。
    assert 签名目录.事件一条(eid)["状态"] == "死信", (
        "停用端死信重投不得把事件部分提交回待投"
    )
    dl = 签名目录.事件一条(eid)["死信"]
    assert dl["状态"] == "待处置"
