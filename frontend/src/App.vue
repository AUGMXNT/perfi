<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { Suspense } from 'vue'

const route = useRoute()

// The python backend dynamically finds ports to serve the api and frontend from
// The electron app starts the python backend, discovers the ports from the python server processes
// and exposes the api port via a query string var when it loads the app.
const apiPort = route.query.apiPort ? route.query.apiPort.toString() : '5001'
window.localStorage.setItem('apiPort', apiPort)

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
            <q-breadcrumbs-el label="Entities" icon="people" :to="{name: 'entities'}" />
          </q-breadcrumbs>
        </q-toolbar>

      <q-tabs align="left">
        <!-- <q-route-tab to="/" label="Transactions" />
        <q-route-tab to="/settings" label="Settings" /> -->
      </q-tabs>
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
