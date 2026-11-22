"""路径推理领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。

新增可达性计算：对推理任务的端点、关系与覆盖数据做可达性判定。
走不到的目标不再只回一个"无路径"，而是输出带余量的空路径数据：
- 确认越界：完整图上真实最短跳数仍超上限，结论为终态，写明实际边界；
- 待补齐索引：只是途经的索引段还没读齐，不等于不可达，标出缺失段，
  等图谱索引补齐后再重算，重算不叠加首轮的排除范围。
结论按（来源任务, 目标实体）幂等回写推荐引擎清单。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 推理图快照：真实项目里来自图谱存储，这里用一份固定图演示可达性判定。
# 边 = (源实体, 目标实体, 关系, 段号)；段号对应图谱索引的"目标属性"，
# 索引状态为"已生效"时该段才算读齐、可参与可执行路径。
REASONING_EDGES: list[tuple[str, str, str, str]] = [
    ("ENT-ALPHA", "ENT-NORTH-1", "依赖", "SEG-01"),
    ("ENT-NORTH-1", "ENT-NORTH-2", "依赖", "SEG-02"),
    ("ENT-NORTH-2", "ENT-NORTH-3", "依赖", "SEG-03"),
    ("ENT-NORTH-3", "ENT-NORTH-4", "依赖", "SEG-04"),
    ("ENT-NORTH-4", "ENT-OMEGA", "依赖", "SEG-05"),
    ("ENT-ALPHA", "ENT-MID", "引用", "SEG-06"),
    ("ENT-MID", "ENT-BETA", "引用", "SEG-07"),
]

# 段号 → 图谱索引编号；覆盖查询请求按索引编号发起。
SEGMENT_INDEX: dict[str, str] = {f"SEG-0{i}": f"IDX-00{i}" for i in range(1, 8)}

# 可达性结论 → 候选状态（推荐引擎侧）。
CONCLUSION_CANDIDATE_STATUS = {
    "可达": "可下发",
    "确认越界": "已排除",
    "图内不连通": "已排除",
    "待补齐索引": "待补算",
}


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class PathReasonService(BaseModuleService):
    MODULE = "path_reason"
    ENTITY = "推理任务"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["任务编号", "起始实体", "目标实体", "推理模式", "最大跳数", "路径数量", "置信阈值", "推理耗时"]
    REQUIRED_FIELDS = ["任务编号", "起始实体", "目标实体"]
    STATUS_ORDER = ["待推理", "推理中", "已完成", "推理超时"]
    ACTION_RULES = {"启动推理": "推理中", "可达性计算": "已完成", "取消推理": "已完成", "标记超时": "推理超时"}
    NEGATIVE_ACTIONS = []

    # ===== 可达性计算 =====
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action == "可达性计算":
            return self._run_reachability(entry_id)
        entry, message = super().run_action(entry_id, action)
        if entry is None:
            return entry, message
        # 链路 L10: path_reason → query_cache（推理结果写入查询缓存）
        if entry.get("status") == "已完成":
            cache_msg = self._push_to_query_cache(entry)
            message += "；" + cache_msg
        # 链路 L11: path_reason → reco_engine（推理路径推送推荐引擎）
        if entry.get("status") == "已完成":
            reco_msg = self._push_to_reco_engine(entry)
            message += "；" + reco_msg
        return entry, message

    def _run_reachability(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """对任务的每个目标做可达性计算，输出带余量的空路径数据并回写推荐引擎。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        results = self.compute_all(entry)
        entry["可达性结果"] = results
        entry["status"] = "已完成"
        entry["pending"] = False
        entry["abnormal"] = any(r["结论"] in ("确认越界", "图内不连通") for r in results)
        cache_msg = self._push_to_query_cache(entry)
        reco_msg = self._writeback_reco(entry, results)
        summary = "；".join(f"{r['目标实体']}{r['结论']}" for r in results)
        return entry, f"可达性计算完成：{summary}；{cache_msg}；{reco_msg}"

    def compute_all(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        targets = [t.strip() for t in str(entry.get("目标实体", "")).split(",") if t.strip()]
        return [self.compute_target(entry, target) for target in targets]

    def compute_target(self, entry: dict[str, Any], target: str) -> dict[str, Any]:
        """单目标可达性判定：先在已读齐子图内限跳找路，走不到再判定是越界还是缺索引。"""
        max_hops = _parse_int(entry.get("最大跳数"), default=3)
        start = str(entry.get("起始实体", "")).strip()
        covered = self._covered_segments()
        base: dict[str, Any] = {
            "目标实体": target,
            "最大跳数": max_hops,
            "缺失段": [],
            "缺失索引": [],
        }
        # 1) 已读齐子图 + 跳数上限内：找得到才是可执行路径。
        nodes, segs = self._shortest_path(self._adjacency(covered), start, target, max_hops)
        if nodes is not None:
            hops = len(segs)
            return base | {
                "结论": "可达",
                "空路径": False,
                "路径": nodes,
                "路径段": segs,
                "跳数": hops,
                "实际边界": hops,
                "余量": max_hops - hops,
                "余量状态": "已证实",
                "发布范围": "可发布：作为路径证据下发",
                "原因": f"可达：{hops} 跳，余量 {max_hops - hops} 跳",
            }
        # 2) 完整图（含未读齐段）求真实边界，区分"确定越界"与"索引没读齐"。
        full_nodes, full_segs = self._shortest_path(self._adjacency(None), start, target, None)
        if full_nodes is None:
            return base | {
                "结论": "图内不连通",
                "空路径": True,
                "路径": [],
                "实际边界": None,
                "余量": None,
                "余量状态": "已证实",
                "发布范围": "可发布结论：不可达（终态），推荐侧可排除",
                "原因": "完整图内不存在通路，确认不可达",
            }
        boundary = len(full_segs)
        if boundary > max_hops:
            return base | {
                "结论": "确认越界",
                "空路径": True,
                "路径": [],
                "实际边界": boundary,
                "余量": max_hops - boundary,
                "余量状态": "已证实",
                "发布范围": "可发布结论：不可达（终态），推荐侧可排除",
                "原因": (
                    f"确认越界：实际最短 {boundary} 跳 > 上限 {max_hops} 跳，"
                    f"缺口 {boundary - max_hops} 跳；与索引覆盖无关，补齐也不会改变"
                ),
            }
        missing_segs = [seg for seg in full_segs if seg not in covered]
        missing_idx = [SEGMENT_INDEX[seg] for seg in missing_segs if seg in SEGMENT_INDEX]
        return base | {
            "结论": "待补齐索引",
            "空路径": True,
            "路径": [],
            "候选路径": full_nodes,
            "实际边界": boundary,
            "余量": max_hops - boundary,
            "余量状态": "待证实",
            "缺失段": missing_segs,
            "缺失索引": missing_idx,
            "发布范围": "不可发布不可达结论：索引未读齐不等于不可达，仅可标记待补算",
            "原因": (
                f"索引 {'、'.join(missing_idx)} 未读齐（缺段 {'、'.join(missing_segs)}），"
                f"不等于不可达；若补齐，{boundary} 跳可达，余量 {max_hops - boundary} 跳"
            ),
        }

    def graph_view(self) -> dict[str, Any]:
        """推理图 + 索引覆盖状态，供推演视图展示。"""
        covered = self._covered_segments()
        index_rows = {str(r.get("索引编号", "")): r for r in store.rows("graph_index")}
        edges = []
        for src, dst, rel, seg in REASONING_EDGES:
            index_code = SEGMENT_INDEX.get(seg, "")
            index_row = index_rows.get(index_code, {})
            edges.append({
                "段号": seg,
                "源实体": src,
                "目标实体": dst,
                "关系": rel,
                "索引编号": index_code,
                "索引状态": index_row.get("status", "未登记"),
                "覆盖状态": "已读齐" if seg in covered else "未读齐",
                "覆盖查询": index_row.get("覆盖查询", ""),
            })
        return {"边": edges, "已读齐段": sorted(covered)}

    def _covered_segments(self) -> set[str]:
        """覆盖数据来自图谱索引：状态"已生效"的索引，其目标属性（段号）才算读齐。"""
        return {
            str(row.get("目标属性", "")).strip()
            for row in store.rows("graph_index")
            if row.get("status") == "已生效" and str(row.get("目标属性", "")).strip()
        }

    @staticmethod
    def _adjacency(allowed_segments: set[str] | None) -> dict[str, list[tuple[str, str]]]:
        adj: dict[str, list[tuple[str, str]]] = {}
        for src, dst, _rel, seg in REASONING_EDGES:
            if allowed_segments is not None and seg not in allowed_segments:
                continue
            adj.setdefault(src, []).append((dst, seg))
        return adj

    @staticmethod
    def _shortest_path(
        adj: dict[str, list[tuple[str, str]]],
        start: str,
        target: str,
        limit: int | None,
    ) -> tuple[list[str] | None, list[str] | None]:
        """BFS 最短路径；limit 为跳数上限（None 表示不限）。返回 (节点路径, 段序列)。"""
        if start == target:
            return [start], []
        frontier = [(start, [start], [])]
        seen = {start}
        depth = 0
        while frontier:
            depth += 1
            if limit is not None and depth > limit:
                break
            next_frontier: list[tuple[str, list[str], list[str]]] = []
            for node, nodes, segs in frontier:
                for nxt, seg in adj.get(node, []):
                    if nxt in seen:
                        continue
                    if nxt == target:
                        return nodes + [nxt], segs + [seg]
                    seen.add(nxt)
                    next_frontier.append((nxt, nodes + [nxt], segs + [seg]))
            frontier = next_frontier
        return None, None

    # ===== 跨模块数据流实现 =====
    def _writeback_reco(self, entry: dict[str, Any], results: list[dict[str, Any]]) -> str:
        """推理结果回写推荐引擎清单：逐目标幂等更新，随后记录一轮下发快照。"""
        from app.services import service_for

        reco = service_for("reco_engine")
        if reco is None or not hasattr(reco, "upsert_path_candidate"):
            return "推荐引擎未就绪，回写跳过"
        for result in results:
            reco.upsert_path_candidate(entry, result)
        snapshot = reco.record_delivery("首轮下发" if not reco.delivery_rounds else "推理回写")
        return f"推理结果已回写推荐引擎清单（{len(results)} 个目标，第{snapshot['轮次']}轮下发）"

    def _push_to_query_cache(self, entry: dict[str, Any]) -> str:
        rows = store.rows("query_cache")
        next_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        qc_entry: dict[str, Any] = {
            "id": next_id,
            "status": "有效",
            "pending": True,
            "abnormal": False,
            "条目编号": f"QUER-PATH-{next_id:04d}",
            "查询模板": f"path_{entry.get('起始实体','')}_to_{entry.get('目标实体','')}",
            "结果哈希": f"reasoned_{entry.get('路径数量','')}",
            "命中次数": "0",
            "TTL秒数": "7200",
            "存储大小": "2KB",
            "最后命中": "",
            "缓存状态": "fresh",
        }
        rows.append(qc_entry)
        return f"推理结果已缓存 {qc_entry['条目编号']}"

    def _push_to_reco_engine(self, entry: dict[str, Any]) -> str:
        rows = store.rows("reco_engine")
        next_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        reco_entry: dict[str, Any] = {
            "id": next_id,
            "status": "草稿",
            "pending": True,
            "abnormal": False,
            "规则编号": f"RECO-PATH-{next_id:04d}",
            "推荐场景": f"路径推理关联推荐",
            "源实体": str(entry.get("起始实体", "")),
            "推荐算法": f"path-rank-{entry.get('推理模式','')}",
            "候选数量": int(entry.get("路径数量", 10)) + 5,
            "过滤条件": str(entry.get("置信阈值", "")),
            "命中次数": "0",
            "采纳率": "0%",
        }
        rows.append(reco_entry)
        return f"路径推理结果推送推荐引擎 {reco_entry['规则编号']}"

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["cross_module_consumers"] = ["query_cache", "reco_engine"]
        return base
