# -*- coding: utf-8 -*-
"""骨签 hook-12-停用端点联拒 · 失败测乙

乙：端点名册亮停用灯时，对账不得仍把「停用端有入队/在队」当成合法。
救绿服务：互证/名册对账服务（app/services/互证.py、app/services/端点.py 的对账面）。
跨表联查得到的停用挂账只是「影子」，单独成桶，不得混进正式集合。
本文件在未挂对账影子前必须见红。
"""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="hook_b_")
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest  # noqa: E402

from app import db, seed  # noqa: E402
from app.services import 端点, 互证  # noqa: E402


@pytest.fixture()
def 库(tmp_path, monkeypatch):
    路径 = tmp_path / "hook_stop_b.db"
    monkeypatch.setattr(db, "库路径", 路径)
    seed.初始化库()
    yield 路径


def 造停用挂账(键: str = "ep-stop-b", 条数: int = 3) -> str:
    端点.登记({"端点键": 键, "名称": "停用乙", "回调URL": "https://x/b"})
    端点.改启用(键, False)
    t = "2026-02-01T00:00:00Z"
    conn = db.连接()
    try:
        for i in range(条数):
            conn.execute(
                "INSERT INTO 事件(事件号,事件类型,端点键,载荷摘要,优先级,状态,入队时,更新时)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"ACC-B-{i}", "acc.b", 键, f"b-{i}", "紧急", "待投", t, t),
            )
        conn.commit()
    finally:
        conn.close()
    return 键


def test_乙_停用灯亮有入队_互证不得判对齐合法(库):
    """核心红：现状互证只数总数/死信，停用端待投行被当成合法水位 → 是否对齐=True。"""
    键 = 造停用挂账(条数=3)
    rep = 互证.跑一次()
    assert rep["是否对齐"] is False, (
        "停用灯已亮且有 3 条入队在队，对账必须判撕裂/非法，不能仍判对齐"
    )
    assert int(rep.get("停用端挂账", 0)) >= 3
    assert "停用" in rep.get("说明", "")
    # 影子明细单独给出，可逐行追
    影子 = rep.get("影子明细") or []
    assert len(影子) >= 3
    assert all(row["端点键"] == 键 for row in 影子)


def test_乙_影子挂账不得混进正式待投口径(库):
    """跨表联查的影子单独成桶：正式待投只数启用端集，停用挂账另计。"""
    造停用挂账(条数=3)
    rep = 互证.跑一次()
    明细 = rep["明细"]
    assert int(rep["停用端挂账"]) == 3
    # 正式待投口径里不应含这 3 条停用端事故行
    conn = db.连接()
    try:
        启用端待投 = conn.execute(
            "SELECT COUNT(*) AS n FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE e.状态 IN ('待投','投递中') AND d.启用=1"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert int(明细["待"]) == 启用端待投
    # 影子数不被并进正式待投
    assert int(明细["待"]) + int(rep["停用端挂账"]) >= 3


def test_乙_名册对账分启用灯并判停用挂账非法(库):
    """端点名册列表的对账面：启用灯、在队数、中文结论、合法布尔，同库同源。"""
    键 = 造停用挂账(条数=2)
    rows = 端点.名册对账()
    row = next(r for r in rows if r["端点键"] == 键)
    assert int(row["启用"]) == 0
    assert int(row["在队数"]) >= 2
    assert row["合法"] is False
    结论 = str(row["名册结论"])
    assert "停用" in 结论 and ("挂账" in 结论 or "异常" in 结论 or "拒" in 结论)


def test_乙_干净启用端点名册判合法(库):
    """对照组：启用且无异常的端点必须仍判合法，避免一刀切全红。"""
    rows = 端点.名册对账()
    billing = next(r for r in rows if r["端点键"] == "ep-billing")
    assert int(billing["启用"]) == 1
    assert billing["合法"] is True
