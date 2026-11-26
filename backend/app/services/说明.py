from __future__ import annotations
from app.services import 签名目录
from app.modules.停用联拒 import 骨签


def 仓情() -> dict:
    return {
        "产品": "投递台",
        "领域": "应用开发/全栈开发",
        "骨签": 骨签,
        "工程形态": "双写两轨：停用端被拒入队进只读归档，现行队列只读启用端集；凭证表钉启用指纹并拒停用回刷",
        "主链": "端点登记→事件入队→签名投递→失败重试与死信→投递账互证",
        "声明": "Webhook投递控制台，非工单客服/OA/CRM，非数据工程采集入库",
        "概览": 签名目录.概览(),
    }


def 主链说明() -> str:
    return 仓情()["主链"]
