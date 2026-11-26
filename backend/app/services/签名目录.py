from __future__ import annotations
from app.db import 连接
from app.services import 校验


def 签名规() -> dict:
    conn = 连接()
    try:
        rows = conn.execute("SELECT 键,值 FROM 签名规").fetchall()
        return {r["键"]: r["值"] for r in rows}
    finally:
        conn.close()


def 改签名规(body: dict) -> dict:
    conn = 连接()
    try:
        for k, v in body.items():
            键 = 校验.非空("键", k)
            值 = 校验.非空("值", v)
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (键, 值),
            )
        conn.commit()
        return 签名规()
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        def c(sql):
            return conn.execute(sql).fetchone()[0]

        def cf(状态条件: str) -> int:
            # 正式集合：只数启用端点名下的事件（现行队列只读启用端集）。
            return conn.execute(
                "SELECT COUNT(*) FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
                f"WHERE d.启用=1 AND {状态条件}"
            ).fetchone()[0]

        return {
            "端点数": c("SELECT COUNT(*) FROM 投递端点"),
            "启用端点": c("SELECT COUNT(*) FROM 投递端点 WHERE 启用=1"),
            "事件总数": c("SELECT COUNT(*) FROM 事件"),
            "待投": cf("e.状态='待投'"),
            "投递中": cf("e.状态='投递中'"),
            "已投递": cf("e.状态='已投递'"),
            "死信": cf("e.状态='死信'"),
            "尝试数": c("SELECT COUNT(*) FROM 投递尝试"),
            "死信匣": c("SELECT COUNT(*) FROM 死信 WHERE 状态='待处置'"),
            # 跨表联查得到的影子/归档，单独成桶，不混进上面的正式集合。
            "停用端挂账": c(
                "SELECT COUNT(*) FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
                "WHERE d.启用=0 AND e.状态 IN ('待投','投递中')"
            ),
            "停用归档拒数": c("SELECT COUNT(*) FROM 停用归档"),
            "签名规": 签名规(),
        }
    finally:
        conn.close()


def 事件列表() -> list:
    """正式事件/现行队列读集合：只读启用端点集合（双写两轨选边）。

    停用端名下的物理行不在此返回；它们由对账服务作为「影子挂账」单列，
    被拒的新入队则在 :func:`停用归档列表` 的只读归档轨里。
    需要含影子的全量请用 :func:`事件全量`。
    """
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT e.* FROM 事件 e "
            "JOIN 投递端点 d ON e.端点键 = d.端点键 "
            "WHERE d.启用 = 1 "
            "ORDER BY e.入队时 DESC"
        ).fetchall()]
    finally:
        conn.close()


def 现行队列() -> list:
    return 事件列表()


def 事件全量() -> list:
    """含停用端影子行的物理全量，仅供对账/排障，不得当正式队列渲染。"""
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 事件 ORDER BY 入队时 DESC"
        ).fetchall()]
    finally:
        conn.close()


def 停用归档列表() -> list:
    """只读归档轨：停用端被联拒的入队尝试 + 中文拒因。"""
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 停用归档 ORDER BY 时刻 DESC, 归档号 DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()


def 事件一条(事件号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["尝试"] = [dict(x) for x in conn.execute(
            "SELECT * FROM 投递尝试 WHERE 事件号=? ORDER BY 投递时 DESC", (事件号,)
        ).fetchall()]
        dl = conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone()
        d["死信"] = dict(dl) if dl else None
        return d
    finally:
        conn.close()


def 投递列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 投递尝试 ORDER BY 投递时 DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()


def 死信列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 死信 ORDER BY 入匣时 DESC").fetchall()]
    finally:
        conn.close()


def 端点列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 投递端点 ORDER BY 端点键").fetchall()]
    finally:
        conn.close()


def 互证列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 互证批次 ORDER BY 批次号 DESC LIMIT 50").fetchall()]
    finally:
        conn.close()
