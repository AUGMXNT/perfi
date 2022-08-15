import { createRouter, createWebHashHistory, isNavigationFailure, RouterView } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import SettingsView from '@/views/SettingsView.vue'
import EntityView from '@/views/EntityView.vue'
import TransactionsView from '@/views/TransactionsView.vue'
import BalancesView from '@/views/BalancesView.vue'
import AddressView from '@/views/AddressView.vue'
import EntityDetailsVue from '@/components/EntityDetails.vue'
import AddressDetailsVue from '@/components/AddressDetails.vue'
import EntitiesListVue from '@/components/EntitiesList.vue'
import PassThroughView from '@/views/PassthroughView.vue'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: PassThroughView,
      meta: {
        breadcrumb: {label: 'Home', icon: 'home' }
      },
      children: [
        {
          path: '',
          name: 'home',
          component: EntitiesListVue,
        },
        {
          path: 'entities',
          component: PassThroughView,
          meta: {
            breadcrumb: { label: 'Entities', icon: 'people' }
          },
          children: [
            {
              path: '',
              name: 'entities',
              component: EntitiesListVue,
            },
            {
              path: ':entityId',
              component: EntityView,
              meta: {
                breadcrumb: { dynamicLabel: 'entity.value.name' }
              },
              children: [
                {
                  path: '',
                  name: 'entity',
                  component: EntityDetailsVue,
                },
                {
                  path: 'transactions',
                  name: 'transactions',
                  component: TransactionsView,
                  meta: {
                    breadcrumb: { label: 'Transactions', icon: 'receipt' }
                  },
                },
                {
                  path: 'balances',
                  name: 'balances',
                  component: BalancesView,
                  meta: {
                    breadcrumb: { label: 'Balances', icon: 'account_balance' }
                  },
                },
                {
                  path: 'addresses',
                  component: RouterView,
                  meta: {
                    breadcrumb: { label: 'Addresses', icon: 'alternate_email', noLink: true }
                  },
                  children: [
                {
                  path: ':addressId',
                  name: 'address',
                  component: AddressDetailsVue,
                  meta: {
                    breadcrumb: { dynamicLabel: 'address.value.address', }
                  },
                },
                  ]
                },
              ]
            },
          ]
        },
      ]
    },
    // {
    //   path: '/about',
    //   name: 'about',
    //   // route level code-splitting
    //   // this generates a separate chunk (About.[hash].js) for this route
    //   // which is lazy-loaded when the route is visited.
    //   component: () => import('../views/AboutView.vue')
    // }
  ]
})

export default router
