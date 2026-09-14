import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '总览' } },
  { path: '/novels/:name/outline', name: 'outline', component: () => import('../views/Outline.vue'), meta: { title: '大纲/章名' } },
  { path: '/novels/:name/chapters', name: 'chapters', component: () => import('../views/Chapters.vue'), meta: { title: '章节' } },
  { path: '/novels/:name/console', name: 'console', component: () => import('../views/Console.vue'), meta: { title: '生成控制台' } },
  { path: '/novels/:name/bible', name: 'bible', component: () => import('../views/Bible.vue'), meta: { title: '知识库' } },
  { path: '/novels/:name/model', name: 'model', component: () => import('../views/ModelConfig.vue'), meta: { title: '模型配置' } },
  { path: '/style', name: 'style', component: () => import('../views/StyleKit.vue'), meta: { title: '风格工坊' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export const novelRoute = (name, view) => ({
  name: view,
  params: { name },
})

export default router
