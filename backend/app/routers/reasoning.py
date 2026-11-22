"""可达性推演只读视图：推理图覆盖状态、推荐下发轮次与首轮/补齐后差异。

计算与重算的写操作仍走通用动作接口（path_reason 的"可达性计算"、
graph_index 的"重建索引"），这里只提供跨模块的汇总读视图。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import service_for

router = APIRouter(prefix="/api/reasoning", tags=["可达性推演"])


def _service(module: str, capability: str):
    service = service_for(module)
    if service is None or not hasattr(service, capability):
        raise HTTPException(status_code=503, detail=f"{module} 未提供 {capability} 能力")
    return service


@router.get("/graph")
def reasoning_graph() -> dict[str, Any]:
    """推理图与索引覆盖状态：哪些段已读齐、哪些段还缺、谁发起了覆盖查询。"""
    return _service("path_reason", "graph_view").graph_view()


@router.get("/delivery")
def delivery_current() -> dict[str, Any]:
    """当前下发视图：可下发候选、待补算、已排除及各自的空态原因。"""
    return _service("reco_engine", "current_delivery").current_delivery()


@router.get("/delivery/rounds")
def delivery_rounds() -> dict[str, Any]:
    """下发轮次历史：第 1 轮为推理回写后的首轮下发。"""
    service = _service("reco_engine", "current_delivery")
    return {"轮次": service.delivery_rounds}


@router.get("/delivery/diff")
def delivery_diff() -> dict[str, Any]:
    """首轮下发 vs 当前：补齐后恢复的目标、保持排除未叠加的目标。"""
    return _service("reco_engine", "delivery_diff").delivery_diff()


@router.post("/recompute")
def recompute() -> dict[str, Any]:
    """手动触发待补算目标重算（索引补齐后一般已由 graph_index 联动触发）。"""
    service = _service("reco_engine", "recompute_pending")
    return {"ok": True, "message": service.recompute_pending(trigger="手动")}
