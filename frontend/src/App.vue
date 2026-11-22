<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">知谱工坊 · 元数据知识图谱与智能探查平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向元数据实体抽取、关系建模、知识图谱构建、图谱搜索、实体链接、消岐融合、路径推理、子图探查与图谱演化追踪的元数据知识图谱与智能探查平台。</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "实体抽取", path: "/entity_extract" }, { label: "关系建模", path: "/relation_model" }, { label: "图谱构建", path: "/graph_build" }, { label: "图谱搜索", path: "/graph_search" }, { label: "实体链接", path: "/entity_link" }, { label: "消岐融合", path: "/disambig" }, { label: "路径推理", path: "/path_reason" }, { label: "可达性推演", path: "/reasoning" }, { label: "子图探查", path: "/subgraph_exp" }, { label: "图谱演化", path: "/graph_evolve" }, { label: "质量审计", path: "/quality_audit" }, { label: "元数据标注", path: "/metadata_tag" }, { label: "分类体系", path: "/taxonomy" }, { label: "查询缓存", path: "/query_cache" }, { label: "图谱索引", path: "/graph_index" }, { label: "数据血缘", path: "/data_lineage" }, { label: "推荐引擎", path: "/reco_engine" }, { label: "实体归并", path: "/entity_merge" }, { label: "批量导入", path: "/batch_load" }, { label: "图谱报告", path: "/report_gen" }, { label: "图谱比对", path: "/graph_compare" }, { label: "定时任务", path: "/schedule_job" }, { label: "治理看板", path: "/govern_dash" }]
</script>
