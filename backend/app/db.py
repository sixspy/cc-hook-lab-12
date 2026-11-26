import os
import sqlite3
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "投递台.db"


def 连接() -> sqlite3.Connection:
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=8.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 8000")
    # 实验/阅卷环境的磁盘 fsync 与元数据延迟极高（默认 FULL 时每次提交可达
    # 数百毫秒）。投递台是单机实验库，采用内存回滚日志 + 关闭同步刷盘以保证
    # 用例与页面流畅；多会话/多进程仍由 SQLite 文件锁与 BEGIN IMMEDIATE 串行。
    # 可用环境变量 库同步=FULL 切回耐久优先配置。
    if os.environ.get("库同步", "FAST").upper() == "FULL":
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    else:
        c.execute("PRAGMA journal_mode=MEMORY")
        c.execute("PRAGMA synchronous=OFF")
    return c
