from __future__ import annotations

import uuid

from app.db import 连接
from app.services import 校验
from app.services.时间 import 此刻
from app.modules.并发投递锁 import 立即事务
from app.modules.停用联拒 import (
    骨签,
    启用指纹 as 算指纹,
    拒因中文,
    停用联拒错误,
)
from app.modules.双写归档轨 import 写归档


def 建事件(body: dict) -> dict:
    类型 = 校验.非空("事件类型", body.get("事件类型"))
    端点键 = 校验.非空("端点键", body.get("端点键"))
    摘要 = str(body.get("载荷摘要") or "")
    优先级 = str(body.get("优先级") or "普通")
    事件号 = str(body.get("事件号") or f"EVT-{uuid.uuid4().hex[:10]}")
    t = 此刻()

    拒因: str | None = None
    归档号 = ""
    out: dict | None = None

    # 启用灯联查与入队写入在同一把同锁 + BEGIN IMMEDIATE 票内，同成同败。
    with 立即事务(连接) as conn:
        ep = conn.execute(
            "SELECT * FROM 投递端点 WHERE 端点键=?", (端点键,)
        ).fetchone()
        if not ep:
            raise ValueError("端点不存在")

        指纹 = 算指纹(端点键, ep["启用"], ep["密钥版本"])

        if int(ep["启用"]) != 1:
            # 停用联拒：不写正式 事件 表，只在同票内落只读归档轨（双写两轨）。
            拒因 = 拒因中文(端点键)
            归档号 = 写归档(
                conn,
                端点键=端点键,
                拒因=拒因,
                时刻=t,
                事件号=事件号,
                事件类型=类型,
                载荷摘要=摘要,
                优先级=优先级,
                启用指纹值=指纹,
            )
            conn.execute(
                "INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                (t, "停用联拒", 事件号, f"{端点键} 拒入队→{归档号}"),
            )
        else:
            if conn.execute(
                "SELECT 1 FROM 事件 WHERE 事件号=?", (事件号,)
            ).fetchone():
                raise ValueError("事件号已存在")
            conn.execute(
                "INSERT INTO 事件("
                "事件号,事件类型,端点键,载荷摘要,优先级,状态,启用指纹,入队时,更新时"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (事件号, 类型, 端点键, 摘要, 优先级, "待投", 指纹, t, t),
            )
            conn.execute(
                "INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                (t, "入队", 事件号, 类型),
            )
            row = conn.execute(
                "SELECT * FROM 事件 WHERE 事件号=?", (事件号,)
            ).fetchone()
            out = dict(row)

    # with 块干净退出已 COMMIT（归档/正式写入都已落库）。停用情形在票外抛中文拒因。
    if 拒因 is not None:
        err = 停用联拒错误(拒因, 端点键=端点键, 归档号=归档号)
        raise err

    assert out is not None
    out["入队成败"] = True
    out["入队结果"] = "已入队·待投"
    out["骨签"] = 骨签
    return out
