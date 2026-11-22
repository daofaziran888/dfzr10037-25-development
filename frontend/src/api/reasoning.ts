/** 可达性推演接口：推理图覆盖、推荐下发视图与首轮/补齐后差异。 */
import { fetchJson, request } from './client'

export type ReasoningEdge = {
  段号: string
  源实体: string
  目标实体: string
  关系: string
  索引编号: string
  索引状态: string
  覆盖状态: string
  覆盖查询: string
}

export type ReasoningGraph = {
  边: ReasoningEdge[]
  已读齐段: string[]
}

export type CandidateBrief = {
  规则编号: string
  来源任务: string
  源实体: string
  目标实体: string
  候选状态: string
  结论: string
  空态原因: string
  余量: number | null
  实际边界: number | null
  缺失索引: string
  覆盖查询: string
  发布范围: string
}

export type DeliveryView = {
  可下发: CandidateBrief[]
  待补算: CandidateBrief[]
  已排除: CandidateBrief[]
  候选总数: number
  空态说明: string[]
  轮次?: number
  标签?: string
}

export type DeliveryDiff = {
  ok: boolean
  message?: string
  首轮?: DeliveryView
  当前?: DeliveryView
  补齐后恢复?: string[]
  仍待补算?: string[]
  保持排除未叠加?: string[]
  新增排除?: string[]
}

export type ReachabilityResult = {
  目标实体: string
  结论: string
  空路径: boolean
  路径: string[]
  候选路径?: string[]
  最大跳数: number
  实际边界: number | null
  余量: number | null
  余量状态: string
  缺失段: string[]
  缺失索引: string[]
  发布范围: string
  原因: string
}

export function fetchReasoningGraph(): Promise<ReasoningGraph> {
  return fetchJson('/api/reasoning/graph')
}

export function fetchDelivery(): Promise<DeliveryView> {
  return fetchJson('/api/reasoning/delivery')
}

export function fetchDeliveryDiff(): Promise<DeliveryDiff> {
  return fetchJson('/api/reasoning/delivery/diff')
}

export async function recomputePending(): Promise<string> {
  const response = await request('/api/reasoning/recompute', { method: 'POST' })
  const data = (await response.json()) as { message: string }
  return data.message
}
