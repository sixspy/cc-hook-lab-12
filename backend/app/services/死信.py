from __future__ import annotations

from app.db import 连接
from app.services.时间 import 此刻
from app.services import 投递
from app.modules.并发投递锁 import 同锁
from app.modules.停用联拒 import 拒因中文, 停用联拒错误


def 作废(事件号: str, 原因: str = "人工作废") -> dict:
    t = 此刻()
    conn = 连接()
    try:
        dl = conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone()
        if not dl:
            raise ValueError("不在死信匣")
        if dl["状态"] != "待处置":
            raise ValueError("死信已处置")
        conn.execute("UPDATE 死信 SET 状态=? WHERE 事件号=?", ("已作废", 事件号))
        conn.execute("UPDATE 事件 SET 状态=?, 更新时=? WHERE 事件号=?", ("已作废", t, 事件号))
        conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                     (t, "死信作废", 事件号, 原因))
        conn.commit()
        return dict(conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone())
    finally:
        conn.close()


def 重投(事件号: str) -> dict:
    t = 此刻()
    # 回待投也是入队面：先在同锁内把「死信校验 + 启用灯联查 + 翻状态」做完，
    # 停用端点在任何提交之前就被中文拒绝，杜绝部分提交导致待投行虚增。
    with 同锁:
        conn = 连接()
        try:
            dl = conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone()
            if not dl:
                raise ValueError("不在死信匣")
            if dl["状态"] != "待处置":
                raise ValueError("死信已处置")
            ev = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
            if not ev:
                raise ValueError("无此事件")
            ep = conn.execute(
                "SELECT * FROM 投递端点 WHERE 端点键=?", (ev["端点键"],)
            ).fetchone()
            if not ep:
                raise ValueError("端点缺失")
            if int(ep["启用"]) != 1:
                # 尚未做任何 UPDATE/commit，故事件仍是死信、死信仍待处置。
                raise 停用联拒错误(拒因中文(ev["端点键"]), 端点键=ev["端点键"])
            conn.execute("UPDATE 死信 SET 状态=? WHERE 事件号=?", ("已重投", 事件号))
            conn.execute("UPDATE 事件 SET 状态=?, 更新时=? WHERE 事件号=?", ("待投", t, 事件号))
            conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                         (t, "死信重投", 事件号, "回待投"))
            conn.commit()
        finally:
            conn.close()

    try:
        return 投递.投递一次(事件号)
    except ValueError as e:
        # 跨进程极端情况下停用恰在提交后、投递前落下：补偿回滚，保证待投行不净增。
        if "停用" not in str(e):
            raise
        t2 = 此刻()
        conn = 连接()
        try:
            conn.execute("UPDATE 事件 SET 状态=?, 更新时=? WHERE 事件号=?", ("死信", t2, 事件号))
            conn.execute("UPDATE 死信 SET 状态=? WHERE 事件号=?", ("待处置", 事件号))
            conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                         (t2, "停用联拒", 事件号, "重投遇停用，回退死信"))
            conn.commit()
        finally:
            conn.close()
        raise


def 列表():
    from app.services import 签名目录
    return 签名目录.死信列表()
