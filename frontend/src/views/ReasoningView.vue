<template>
  <section class="page" data-module="reasoning">
    <header class="page-head">
      <div>
        <h2>可达性推演 · 路径推理 → 推荐引擎</h2>
        <p class="page-desc">
          起点 {{ task?.起始实体 ?? 'ENT-ALPHA' }} 到两个目的地都没有可执行路径，但两种空路径的发布范围不同：
          确认越界是终态结论（写明实际边界），索引未读齐不等于不可达（等待补算，不作路径证据）。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="run-reachability" type="button" :disabled="running" @click="runReachability">
          {{ running ? '计算中…' : '执行可达性计算' }}
        </button>
        <button
          class="btn"
          data-testid="rebuild-index"
          type="button"
          :disabled="rebuilding || !missingIndexId"
          @click="rebuildMissingIndex"
        >
          {{ rebuilding ? '补齐中…' : `补齐缺失索引 ${missingIndexCode} 并重算` }}
        </button>
      </div>
    </header>

    <p v-if="actionMessage" class="action-message" data-testid="action-message">{{ actionMessage }}</p>
    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <h3 class="section-title">推理图与索引覆盖</h3>
    <table class="data-table" data-testid="graph-table">
      <thead>
        <tr>
          <th>段号</th><th>边</th><th>关系</th><th>索引编号</th><th>索引状态</th><th>覆盖状态</th><th>覆盖查询</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="edge in graph?.边 ?? []" :key="edge.段号" :data-covered="edge.覆盖状态">
          <td>{{ edge.段号 }}</td>
          <td>{{ edge.源实体 }} → {{ edge.目标实体 }}</td>
          <td>{{ edge.关系 }}</td>
          <td>{{ edge.索引编号 }}</td>
          <td>{{ edge.索引状态 }}</td>
          <td>
            <span class="tag" :class="edge.覆盖状态 === '已读齐' ? 'tag-ok' : 'tag-warn'">{{ edge.覆盖状态 }}</span>
          </td>
          <td>{{ edge.覆盖查询 || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">推理任务与可达性结果（带余量的空路径数据）</h3>
    <p v-if="task" class="task-line">
      {{ task.任务编号 }}：{{ task.起始实体 }} → {{ task.目标实体 }}，上限 {{ task.最大跳数 }} 跳，当前状态「{{ task.status }}」
    </p>
    <table v-if="results.length" class="data-table" data-testid="result-table">
      <thead>
        <tr>
          <th>目标实体</th><th>结论</th><th>空路径</th><th>实际边界</th><th>余量</th><th>缺失索引</th><th>发布范围</th><th>原因</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in results" :key="item.目标实体">
          <td>{{ item.目标实体 }}</td>
          <td><span class="tag" :class="conclusionClass(item.结论)">{{ item.结论 }}</span></td>
          <td>{{ item.空路径 ? '是' : '否' }}</td>
          <td>{{ item.实际边界 ?? '—' }}{{ item.实际边界 ? ' 跳' : '' }}</td>
          <td>{{ item.余量 ?? '—' }}{{ item.余量 !== null ? ` 跳（${item.余量状态}）` : '' }}</td>
          <td>{{ item.缺失索引.join('、') || '—' }}</td>
          <td>{{ item.发布范围 }}</td>
          <td>{{ item.原因 }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">尚未执行可达性计算，点击右上角按钮开始。</p>

    <h3 class="section-title">推荐下发：首轮 vs 补齐之后</h3>
    <div class="delivery-compare">
      <article class="delivery-panel" data-testid="delivery-first">
        <h4>首轮下发<small>（索引未补齐，{{ firstRound?.候选总数 ?? 0 }} 个候选）</small></h4>
        <template v-if="firstRound">
          <DeliveryGroup title="可下发（使用人收到的候选）" :items="firstRound.可下发" />
          <DeliveryGroup title="待补算（不作路径证据）" :items="firstRound.待补算" />
          <DeliveryGroup title="已排除（确认越界）" :items="firstRound.已排除" />
        </template>
        <p v-else class="empty-state">还没有下发记录</p>
      </article>
      <article class="delivery-panel" data-testid="delivery-current">
        <h4>当前一轮<small>（{{ current?.候选总数 ?? 0 }} 个候选）</small></h4>
        <template v-if="current">
          <DeliveryGroup title="可下发（使用人收到的候选）" :items="current.可下发" />
          <DeliveryGroup title="待补算（不作路径证据）" :items="current.待补算" />
          <DeliveryGroup title="已排除（确认越界）" :items="current.已排除" />
        </template>
        <p v-else class="empty-state">还没有下发记录</p>
      </article>
    </div>

    <div v-if="diff?.ok" class="diff-summary" data-testid="delivery-diff">
      <h4>候选数据差异</h4>
      <p>补齐后恢复：<strong>{{ diff.补齐后恢复?.join('、') || '无' }}</strong></p>
      <p>保持排除（未叠加原排除范围）：<strong>{{ diff.保持排除未叠加?.join('、') || '无' }}</strong></p>
      <p>仍待补算：<strong>{{ diff.仍待补算?.join('、') || '无' }}</strong></p>
      <p>新增排除：<strong>{{ diff.新增排除?.join('、') || '无' }}</strong></p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import type { FunctionalComponent, PropType } from 'vue'

import { listEntries, runAction } from '@/api/backend-service'
import {
  fetchDelivery,
  fetchDeliveryDiff,
  fetchReasoningGraph,
} from '@/api/reasoning'
import type {
  CandidateBrief,
  DeliveryDiff,
  DeliveryView,
  ReachabilityResult,
  ReasoningGraph,
} from '@/api/reasoning'
import type { EntryRow } from '@/data/types'

const DeliveryGroup: FunctionalComponent<{ title: string; items: CandidateBrief[] }> = (
  props,
) =>
  h('div', { class: 'delivery-group' }, [
    h('p', { class: 'delivery-group-title' }, `${props.title}：${props.items.length}`),
    props.items.length
      ? h(
          'ul',
          props.items.map((item) =>
            h('li', { key: item.目标实体 }, [
              h('strong', item.目标实体),
              ` ${item.空态原因}`,
              item.覆盖查询 ? `（覆盖查询 ${item.覆盖查询}）` : '',
            ]),
          ),
        )
      : h('p', { class: 'empty-state' }, '空'),
  ])
DeliveryGroup.props = {
  title: { type: String, required: true },
  items: { type: Array as PropType<CandidateBrief[]>, required: true },
}

const graph = ref<ReasoningGraph | null>(null)
const task = ref<EntryRow | null>(null)
const results = ref<ReachabilityResult[]>([])
const firstRound = ref<DeliveryView | null>(null)
const current = ref<DeliveryView | null>(null)
const diff = ref<DeliveryDiff | null>(null)
const running = ref(false)
const rebuilding = ref(false)
const actionMessage = ref('')
const errorMessage = ref('')
const missingIndexId = ref<number | null>(null)

const missingIndexCode = computed(() => {
  const missing = graph.value?.边.find((edge) => edge.覆盖状态 !== '已读齐')
  return missing?.索引编号 ?? 'IDX-007'
})

function conclusionClass(conclusion: string): string {
  if (conclusion === '可达') return 'tag-ok'
  if (conclusion === '待补齐索引') return 'tag-warn'
  return 'tag-bad'
}

async function loadTask() {
  const page = await listEntries('path_reason', { 任务编号: 'PATH-0004' })
  task.value = page.items[0] ?? null
  const detail = (task.value?.可达性结果 ?? null) as unknown as ReachabilityResult[] | null
  if (detail) results.value = detail
}

async function loadMissingIndex() {
  const page = await listEntries('graph_index', { 索引编号: missingIndexCode.value })
  const row = page.items[0]
  missingIndexId.value = row && row.status !== '已生效' ? Number(row.id) : null
}

async function reload() {
  errorMessage.value = ''
  try {
    const [graphData, delivery, diffData] = await Promise.all([
      fetchReasoningGraph(),
      fetchDelivery(),
      fetchDeliveryDiff(),
    ])
    graph.value = graphData
    current.value = delivery
    diff.value = diffData
    firstRound.value = diffData.ok ? diffData.首轮 ?? null : null
    await loadTask()
    await loadMissingIndex()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '推演数据读取失败'
  }
}

async function runReachability() {
  if (!task.value) return
  running.value = true
  errorMessage.value = ''
  try {
    const result = await runAction('path_reason', Number(task.value.id), '可达性计算')
    if (!result.ok) throw new Error(result.message)
    actionMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '可达性计算失败'
  } finally {
    running.value = false
  }
}

async function rebuildMissingIndex() {
  if (missingIndexId.value === null) return
  rebuilding.value = true
  errorMessage.value = ''
  try {
    const result = await runAction('graph_index', missingIndexId.value, '重建索引')
    if (!result.ok) throw new Error(result.message)
    actionMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '索引补齐失败'
  } finally {
    rebuilding.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title { margin: 18px 0 8px; font-size: 15px; }
.task-line { font-size: 13px; color: var(--muted); }
.action-message { background: #ecfdf3; border: 1px solid #a6f4c5; border-radius: 6px; padding: 8px 10px; font-size: 13px; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.tag-ok { background: #ecfdf3; color: #067647; }
.tag-warn { background: #fffaeb; color: #b54708; }
.tag-bad { background: #fef3f2; color: #b42318; }
.delivery-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.delivery-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.delivery-panel h4 { margin: 0 0 8px; }
.delivery-panel small { color: var(--muted); font-weight: normal; margin-left: 6px; }
.delivery-group { margin-bottom: 8px; }
.delivery-group-title { font-size: 13px; color: var(--muted); margin: 0 0 4px; }
.delivery-group ul { margin: 0; padding-left: 18px; font-size: 13px; }
.delivery-group li { margin-bottom: 4px; }
.diff-summary { margin-top: 12px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.diff-summary h4 { margin: 0 0 8px; }
.diff-summary p { margin: 4px 0; font-size: 13px; }
</style>
