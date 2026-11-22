"""图谱索引领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。

索引读齐（状态变为"已生效"）时，自动触发推荐引擎重算等待补算的目标：
覆盖失败而挂起的候选按新覆盖状态恢复评估，已确认越界的排除结论不受影响。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService


class GraphIndexService(BaseModuleService):
    MODULE = "graph_index"
    ENTITY = "索引配置"
    OPERATION_TERM = "存储"
    LIST_FIELDS = ["索引编号", "目标属性", "索引类型", "覆盖实体", "存储体积", "构建耗时", "刷新周期", "最近重建"]
    REQUIRED_FIELDS = ["索引编号", "目标属性", "索引类型"]
    STATUS_ORDER = ["待构建", "构建中", "已生效", "索引异常"]
    ACTION_RULES = {"启动构建": "构建中", "重建索引": "已生效", "标记异常": "索引异常"}
    NEGATIVE_ACTIONS = []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry, message = super().run_action(entry_id, action)
        if entry is None:
            return entry, message
        # 链路：graph_index → reco_engine（索引读齐后重算待补算候选）
        if entry.get("status") == "已生效":
            from app.services import service_for

            reco = service_for("reco_engine")
            if reco is not None and getattr(reco, "has_pending_candidates", lambda: False)():
                summary = reco.recompute_pending(trigger=str(entry.get("索引编号", "")))
                message += f"；索引读齐，{summary}"
        return entry, message
