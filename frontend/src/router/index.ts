import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import SettingsView from '@/views/SettingsView.vue'
import EntityView from '@/views/EntityView.vue'
import TransactionsView from '@/views/TransactionsView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: SettingsView
    },
    {
      path: '/entity/:entityId',
      name: 'entity',
      component: EntityView
    },
    {
      path: '/entities',
      name: 'entities',
      component: SettingsView
    },
    {
      path: '/entities/:entityId/transactions',
      name: 'transactions',
      component: TransactionsView
    },
    {
      path: '/about',
      name: 'about',
      // route level code-splitting
      // this generates a separate chunk (About.[hash].js) for this route
      // which is lazy-loaded when the route is visited.
      component: () => import('../views/AboutView.vue')
    }
  ]
})

export default router
