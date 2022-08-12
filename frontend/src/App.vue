<script setup lang="ts">
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { ref, Suspense, watchEffect } from 'vue'

import { useNavigationContextStore } from '@/stores/navigation_context'
import { storeToRefs } from 'pinia';

const navContextStore = useNavigationContextStore()
const navContextRefs = storeToRefs(navContextStore)

const router = useRouter()


let breadcrumbs = ref([])

const resolveNested = (path: str, obj: any) => {
  return path.split('.').reduce((prev: any, curr: any) => {
      return prev ? prev[curr] : null
  }, obj)
}

watchEffect(() => {
  breadcrumbs.value = []

  const currentRoute = router.currentRoute.value
  for (let match of currentRoute.matched) {
    let breadcrumb: any = match.meta.breadcrumb
    if (breadcrumb === undefined) continue

    if (breadcrumb.dynamicLabel) {
      breadcrumb.label = resolveNested(breadcrumb.dynamicLabel, navContextRefs)
    }

    // replace :param matches in current route path with values so links will work
    breadcrumb.to = match.path
    let pathParams = breadcrumb.to.match(/(:\w+)/g) || []
    for (let param of pathParams) {
      param = param.substring(1) // remove leading :
      if (currentRoute.params[param]) {
        breadcrumb.to = breadcrumb.to.replace(`:${param}`, currentRoute.params[param])
      }
      if (breadcrumb.noLink) {
        breadcrumb.to = null
      }
    }

    breadcrumbs.value.push(breadcrumb)
  }
})
</script>

<template>
  <Suspense>
  <q-layout view="hHh lpR fFf">

    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-toolbar-title>
          <q-avatar>
            <q-icon name="insights" />
          </q-avatar>
          perfi
        </q-toolbar-title>
      </q-toolbar>

        <q-toolbar>
          <q-breadcrumbs active-color="primary" style="font-size: 16px">
            <q-breadcrumbs-el v-for="b in breadcrumbs" :label="b.label" :icon="b.icon" :to="b.to" :key="b.label" />
            <!-- <q-breadcrumbs-el label="Entities" icon="people" :to="{name: 'entities'}" /> -->
          </q-breadcrumbs>
        </q-toolbar>

      <!-- <q-tabs align="left">
        <q-route-tab to="/" label="Transactions" />
        <q-route-tab to="/settings" label="Settings" />
      </q-tabs> -->
    </q-header>

    <q-page-container>
      <!-- page content -->
      <RouterView />
    </q-page-container>

  </q-layout>
  </Suspense>
</template>



<style>
/* @import '@/assets/base.css'; */

/* #app {
  max-width: 1280px;
  margin: 0 auto;
  padding: 2rem;

  font-weight: normal;
} */
</style>
