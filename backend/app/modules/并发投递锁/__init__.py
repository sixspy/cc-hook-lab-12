"""骨签 hook-12-停用端点联拒 · 并发投递同锁。

救绿争用失败测丙：启用灯联查与入队写入必须同票（同一把进程锁 + SQLite
``BEGIN IMMEDIATE`` 写事务），使「改停用」与「入队」严格串行，消灭
check-then-act 的缝。

- 进程内多线程：用可重入锁 :data:`同锁` 串行化「读启用 → 写库 → 提交」整票。
- 双会话 / 双进程：Python 锁不跨进程，靠 ``BEGIN IMMEDIATE`` 拿 SQLite 写锁，
  配合 ``busy_timeout`` 让后到者等待，而不是立刻 ``database is locked``。
"""
from __future__ import annotations

import contextlib
import threading

#: 全进程同一把锁：入队、停用/启用、死信回投都打这把锁。
同锁 = threading.RLock()

#: 统一锁等待，避免并发下即时 database is locked。
BUSY_TIMEOUT_MS = 8000


@contextlib.contextmanager
def 立即事务(连接工厂):
    """在 :data:`同锁` 内开一个 ``BEGIN IMMEDIATE`` 原子写事务。

    用法::

        with 立即事务(连接) as conn:
            ...  # 联查启用灯 + 写入，同成同败
        # 干净退出即 COMMIT；抛异常即 ROLLBACK。

    连接工厂必须是可调用对象，返回一个新的 ``sqlite3.Connection``。
    """
    with 同锁:
        conn = 连接工厂()
        try:
            # 必须在任何 DML / 隐式开事务前切到 autocommit，再显式 IMMEDIATE。
            try:
                conn.isolation_level = None
            except Exception:
                pass
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
