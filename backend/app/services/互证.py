from __future__ import annotations

from app.db import 连接
from app.services.时间 import 此刻
from app.modules.停用联拒 import 骨签


def 跑一次() -> dict:
    t = 此刻()
    conn = 连接()
    try:
        # 正式集合口径：只联启用端点集合，影子不混进正式桶。
        总 = conn.execute(
            "SELECT COUNT(*) AS c FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=1"
        ).fetchone()["c"]
        已 = conn.execute(
            "SELECT COUNT(*) AS c FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=1 AND e.状态='已投递'"
        ).fetchone()["c"]
        死 = conn.execute(
            "SELECT COUNT(*) AS c FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=1 AND e.状态='死信'"
        ).fetchone()["c"]
        待 = conn.execute(
            "SELECT COUNT(*) AS c FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=1 AND e.状态 IN ('待投','投递中')"
        ).fetchone()["c"]
        匣 = conn.execute(
            "SELECT COUNT(*) AS c FROM 死信 x JOIN 投递端点 d ON x.端点键=d.端点键 "
            "WHERE x.状态='待处置' AND d.启用=1"
        ).fetchone()["c"]

        # 跨表联查的「影子挂账」：停用灯亮却仍在待投/投递中的物理行。单独成桶。
        挂账行 = [dict(r) for r in conn.execute(
            "SELECT e.事件号, e.事件类型, e.端点键, e.状态, e.优先级, e.入队时 "
            "FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=0 AND e.状态 IN ('待投','投递中') "
            "ORDER BY e.入队时 DESC"
        ).fetchall()]
        挂账 = len(挂账行)
        停用死信 = conn.execute(
            "SELECT COUNT(*) AS c FROM 事件 e JOIN 投递端点 d ON e.端点键=d.端点键 "
            "WHERE d.启用=0 AND e.状态='死信'"
        ).fetchone()["c"]
        归档拒 = conn.execute("SELECT COUNT(*) AS c FROM 停用归档").fetchone()["c"]

        口径对齐 = (死 == 匣 and 已 + 死 + 待 <= 总)
        对齐 = 1 if (口径对齐 and 挂账 == 0) else 0
        if 挂账 > 0:
            说明 = (
                f"停用端点仍有 {挂账} 条入队/在队挂账，停用联拒对账判撕裂非法；"
                f"影子已单列，未并入正式集合（另有停用端死信 {停用死信}、"
                f"归档拒因 {归档拒} 条）"
            )
        elif not 口径对齐:
            说明 = "死信匣与事件死信数不一致或水位异常"
        else:
            说明 = "事件/投递/死信口径对齐，停用端无挂账"

        conn.execute(
            "INSERT INTO 互证批次("
            "时刻,事件总数,已投递数,死信数,待投数,停用挂账,是否对齐,说明"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (t, 总, 已, 死, 待, 挂账, 对齐, 说明),
        )
        conn.commit()
        return {
            "时刻": t,
            "事件总数": 总,
            "已投递数": 已,
            "死信数": 死,
            "待投数": 待,
            "死信匣待处置": 匣,
            "停用端挂账": 挂账,
            "停用端死信": int(停用死信),
            "归档拒数": int(归档拒),
            "是否对齐": bool(对齐),
            "是否全部对齐": bool(对齐),
            "说明": 说明,
            "骨签": 骨签,
            "影子明细": 挂账行,
            "明细": {
                "总": 总, "已": 已, "死": 死, "待": 待, "匣": 匣,
                "停用端挂账": 挂账,
            },
        }
    finally:
        conn.close()
