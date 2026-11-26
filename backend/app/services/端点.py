from __future__ import annotations

from app.db import 连接
from app.services import 校验
from app.services.时间 import 此刻
from app.modules.并发投递锁 import 立即事务
from app.modules.停用联拒 import 骨签, 启用指纹 as 算指纹


def 登记(body: dict) -> dict:
    端点键 = 校验.非空("端点键", body.get("端点键"))
    名称 = 校验.非空("名称", body.get("名称"))
    url = 校验.非空("回调URL", body.get("回调URL"))
    版本 = str(body.get("密钥版本") or "v1")
    说明 = str(body.get("说明") or "")
    t = 此刻()
    with 立即事务(连接) as conn:
        if conn.execute(
            "SELECT 1 FROM 投递端点 WHERE 端点键=?", (端点键,)
        ).fetchone():
            raise ValueError("端点键已存在")
        conn.execute(
            "INSERT INTO 投递端点(端点键,名称,回调URL,密钥版本,启用,说明)"
            " VALUES (?,?,?,?,1,?)",
            (端点键, 名称, url, 版本, 说明),
        )
        conn.execute(
            "INSERT INTO 端点凭证(端点键,启用,启用指纹,版本号,更新时)"
            " VALUES (?,?,?,1,?)",
            (端点键, 1, 算指纹(端点键, 1, 版本), t),
        )
        conn.execute(
            "INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
            (t, "登记端点", "", 端点键),
        )
        row = conn.execute(
            "SELECT * FROM 投递端点 WHERE 端点键=?", (端点键,)
        ).fetchone()
        out = dict(row)
    out["骨签"] = 骨签
    return out


def 改启用(端点键: str, 启用: bool) -> dict:
    灯 = 1 if 启用 else 0
    t = 此刻()
    # 与入队打同一把同锁 + IMMEDIATE 票：名册灯翻转与凭证指纹同成同败，
    # 且不可能插进某个入队联票的缝里（救争用丙）。
    with 立即事务(连接) as conn:
        ep = conn.execute(
            "SELECT * FROM 投递端点 WHERE 端点键=?", (端点键,)
        ).fetchone()
        if not ep:
            raise ValueError("无此端点")
        conn.execute(
            "UPDATE 投递端点 SET 启用=? WHERE 端点键=?", (灯, 端点键)
        )
        指纹 = 算指纹(端点键, 灯, ep["密钥版本"])
        已有凭证 = conn.execute(
            "SELECT 版本号 FROM 端点凭证 WHERE 端点键=?", (端点键,)
        ).fetchone()
        if 已有凭证:
            新版 = int(已有凭证["版本号"] or 1) + 1
            conn.execute(
                "UPDATE 端点凭证 SET 启用=?,启用指纹=?,版本号=?,更新时=?"
                " WHERE 端点键=?",
                (灯, 指纹, 新版, t, 端点键),
            )
        else:
            conn.execute(
                "INSERT INTO 端点凭证(端点键,启用,启用指纹,版本号,更新时)"
                " VALUES (?,?,?,1,?)",
                (端点键, 灯, 指纹, t),
            )
        conn.execute(
            "INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
            (t, "停用端点" if 灯 == 0 else "启用端点", "", 端点键),
        )
        row = conn.execute(
            "SELECT * FROM 投递端点 WHERE 端点键=?", (端点键,)
        ).fetchone()
        out = dict(row)
    out["启用灯"] = "启用" if 灯 == 1 else "停用"
    out["骨签"] = 骨签
    return out


def 名册对账() -> list[dict]:
    """端点名册列表的对账面（与库同源）。

    每行在原始端点字段外给出：启用灯中文、在队数（待投/投递中，物理口径）、
    归档拒数、合法布尔与中文名册结论。停用灯亮却仍有在队行 → 判非法挂账。
    """
    conn = 连接()
    try:
        eps = conn.execute(
            "SELECT * FROM 投递端点 ORDER BY 端点键"
        ).fetchall()
        out: list[dict] = []
        for r in eps:
            d = dict(r)
            key = r["端点键"]
            在队 = conn.execute(
                "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=?"
                " AND 状态 IN ('待投','投递中')",
                (key,),
            ).fetchone()["n"]
            待投 = conn.execute(
                "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=? AND 状态='待投'",
                (key,),
            ).fetchone()["n"]
            归档拒 = conn.execute(
                "SELECT COUNT(*) AS n FROM 停用归档 WHERE 端点键=?", (key,)
            ).fetchone()["n"]
            死信 = conn.execute(
                "SELECT COUNT(*) AS n FROM 事件 WHERE 端点键=? AND 状态='死信'",
                (key,),
            ).fetchone()["n"]
            启用 = int(r["启用"]) == 1
            if 启用:
                合法 = True
                结论 = f"启用中·可入队（在队{在队}）"
            elif 在队 > 0:
                合法 = False
                结论 = f"停用但有{在队}条在队·挂账异常，对账判非法（联拒影子，待清退）"
            else:
                合法 = True
                结论 = "已停用·入队联拒（无挂账）"
            d.update({
                "启用灯": "启用" if 启用 else "停用",
                "在队数": int(在队),
                "待投数": int(待投),
                "死信数": int(死信),
                "归档拒数": int(归档拒),
                "合法": bool(合法),
                "名册结论": 结论,
                "骨签": 骨签,
            })
            out.append(d)
        return out
    finally:
        conn.close()
