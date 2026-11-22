"""推荐引擎领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。

新增推理候选清单：接收路径推理回写的带余量空路径数据，
- 确认越界的目标 → 已排除，空态原因写明实际边界；
- 待补齐索引的目标 → 待补算，关联覆盖查询请求，不作路径证据下发；
- 索引补齐后重算只评估待补算目标，不把首轮排除范围再叠加一次。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.path_reason import CONCLUSION_CANDIDATE_STATUS
from app.store import store

# 候选状态 → 清单行的通用状态（沿用推荐规则的状态机，便于工作台筛选）。
CANDIDATE_ROW_STATUS = {"可下发": "已生效", "已排除": "已停用", "待补算": "草稿"}


class RecoEngineService(BaseModuleService):
    MODULE = "reco_engine"
    ENTITY = "推荐规则"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["规则编号", "推荐场景", "源实体", "推荐算法", "候选数量", "过滤条件", "命中次数", "采纳率"]
    REQUIRED_FIELDS = ["规则编号", "推荐场景", "源实体"]
    STATUS_ORDER = ["草稿", "已生效", "效果差", "已停用"]
    ACTION_RULES = {"启效规则": "已生效", "标记差效": "效果差", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    def __init__(self) -> None:
        # 下发轮次快照：第 1 轮是推理回写后的首轮下发，之后每次补齐重算追加一轮。
        self.delivery_rounds: list[dict[str, Any]] = []

    # ===== 推理结果回写 =====
    def upsert_path_candidate(self, task_entry: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """按（来源任务, 目标实体）幂等回写：重算只更新原行，不新建、不叠加排除。"""
        rows = store.rows(self.MODULE)
        task_code = str(task_entry.get("任务编号", ""))
        target = str(result.get("目标实体", ""))
        candidate = CONCLUSION_CANDIDATE_STATUS.get(str(result.get("结论", "")), "待补算")
        existing = next(
            (r for r in rows if r.get("来源任务") == task_code and r.get("目标实体") == target),
            None,
        )
        coverage_query = ""
        missing_idx = [str(i) for i in result.get("缺失索引", []) if str(i).strip()]
        if candidate == "待补算" and missing_idx:
            # 用带余量的空路径数据关联覆盖查询请求：点名图谱索引补齐缺失段。
            coverage_query = f"COV-{missing_idx[0]}"
            self._register_coverage_query(coverage_query, missing_idx, task_code, target)
        reason = str(result.get("原因", ""))
        if existing is None:
            next_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            existing = {
                "id": next_id,
                "规则编号": f"RECO-PATH-{next_id:04d}",
                "推荐场景": "路径推理关联推荐",
                "源实体": str(task_entry.get("起始实体", "")),
                "推荐算法": f"path-rank-{task_entry.get('推理模式', '')}",
                "命中次数": "0",
                "采纳率": "0%",
                "来源任务": task_code,
                "目标实体": target,
            }
            rows.append(existing)
        existing.update({
            "status": CANDIDATE_ROW_STATUS[candidate],
            "pending": candidate != "已排除",
            "abnormal": candidate == "已排除",
            "候选数量": 1 if candidate == "可下发" else 0,
            "过滤条件": f"排除{target}：{reason}" if candidate == "已排除" else "",
            "候选状态": candidate,
            "结论": result.get("结论", ""),
            "空路径": bool(result.get("空路径", False)),
            "余量": result.get("余量"),
            "余量状态": result.get("余量状态", ""),
            "实际边界": result.get("实际边界"),
            "缺失索引": ",".join(missing_idx),
            "覆盖查询": coverage_query,
            "空态原因": reason,
            "发布范围": result.get("发布范围", ""),
            "下发轮次": len(self.delivery_rounds) + 1,
        })
        return existing

    def _register_coverage_query(self, query_code: str, missing_idx: list[str], task_code: str, target: str) -> None:
        """在图谱索引行上登记覆盖查询来源，表示推荐侧点名要补这段索引。"""
        for row in store.rows("graph_index"):
            if str(row.get("索引编号", "")) in missing_idx:
                row["覆盖查询"] = f"{query_code}←{task_code}/{target}"

    # ===== 下发视图 =====
    def current_delivery(self) -> dict[str, Any]:
        """当前下发视图：使用人收到的候选 = 可下发；缺席者附空态原因。"""
        rows = [r for r in store.rows(self.MODULE) if r.get("来源任务")]
        deliver = [self._brief(r) for r in rows if r.get("候选状态") == "可下发"]
        pending = [self._brief(r) for r in rows if r.get("候选状态") == "待补算"]
        excluded = [self._brief(r) for r in rows if r.get("候选状态") == "已排除"]
        return {
            "可下发": deliver,
            "待补算": pending,
            "已排除": excluded,
            "候选总数": len(deliver),
            "空态说明": [f"{b['目标实体']}：{b['空态原因']}" for b in (*pending, *excluded)],
        }

    def record_delivery(self, label: str) -> dict[str, Any]:
        snapshot = self.current_delivery()
        snapshot["轮次"] = len(self.delivery_rounds) + 1
        snapshot["标签"] = label
        self.delivery_rounds.append(snapshot)
        return snapshot

    def delivery_diff(self) -> dict[str, Any]:
        """首轮下发 vs 当前：看谁恢复了、谁保持排除（未叠加）、谁还在等。"""
        if not self.delivery_rounds:
            return {"ok": False, "message": "尚无下发记录，请先对推理任务执行可达性计算"}
        first = self.delivery_rounds[0]
        current = self.current_delivery()
        first_pending = {b["目标实体"] for b in first["待补算"]}
        first_excluded = {b["目标实体"] for b in first["已排除"]}
        now_deliver = {b["目标实体"] for b in current["可下发"]}
        now_pending = {b["目标实体"] for b in current["待补算"]}
        now_excluded = {b["目标实体"] for b in current["已排除"]}
        return {
            "ok": True,
            "首轮": first,
            "当前": current,
            "补齐后恢复": sorted(first_pending & now_deliver),
            "仍待补算": sorted(first_pending & now_pending),
            "保持排除未叠加": sorted(first_excluded & now_excluded),
            "新增排除": sorted(now_excluded - first_excluded),
        }

    # ===== 补齐重算 =====
    def has_pending_candidates(self) -> bool:
        return any(r.get("候选状态") == "待补算" for r in store.rows(self.MODULE))

    def recompute_pending(self, trigger: str = "") -> str:
        """索引补齐后重算待补算目标。

        只按当前覆盖状态从零评估"待补算"行；首轮已排除的确认越界目标
        是终态结论，不参与重算，也不会被再排除一次。
        """
        from app.services import service_for

        reason_service = service_for("path_reason")
        if reason_service is None or not hasattr(reason_service, "compute_target"):
            return "路径推理服务未就绪，重算跳过"
        pending_rows = [r for r in store.rows(self.MODULE) if r.get("候选状态") == "待补算"]
        if not pending_rows:
            return "没有等待补算的目标"
        recovered: list[str] = []
        still: list[str] = []
        for row in pending_rows:
            task = self._find_task(str(row.get("来源任务", "")))
            if task is None:
                continue
            target = str(row.get("目标实体", ""))
            result = reason_service.compute_target(task, target)
            self.upsert_path_candidate(task, result)
            (recovered if result["结论"] == "可达" else still).append(target)
        label = f"补齐重算({trigger})" if trigger else "补齐重算"
        snapshot = self.record_delivery(label)
        parts = [f"第{snapshot['轮次']}轮下发已生成"]
        if recovered:
            parts.append(f"恢复候选：{'、'.join(recovered)}")
        if still:
            parts.append(f"仍待补算：{'、'.join(still)}")
        return "；".join(parts)

    @staticmethod
    def _find_task(task_code: str) -> dict[str, Any] | None:
        return next(
            (r for r in store.rows("path_reason") if str(r.get("任务编号", "")) == task_code),
            None,
        )

    @staticmethod
    def _brief(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "规则编号": row.get("规则编号", ""),
            "来源任务": row.get("来源任务", ""),
            "源实体": row.get("源实体", ""),
            "目标实体": row.get("目标实体", ""),
            "候选状态": row.get("候选状态", ""),
            "结论": row.get("结论", ""),
            "空态原因": row.get("空态原因", ""),
            "余量": row.get("余量"),
            "实际边界": row.get("实际边界"),
            "缺失索引": row.get("缺失索引", ""),
            "覆盖查询": row.get("覆盖查询", ""),
            "发布范围": row.get("发布范围", ""),
        }
