import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import ReasoningView from '@/views/ReasoningView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 固定路径必须放在 /:moduleKey 之前，否则会被动态模块路由截获。
    { path: '/reasoning', name: 'reasoning', component: ReasoningView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
