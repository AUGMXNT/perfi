<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import HelloWorld from '@/components/HelloWorld.vue'

import { ref } from 'vue'
import SignInWithEthereum from '@/components/SignInWithEthereum.vue'

</script>

<template>
  <q-layout view="hHh lpR fFf">

    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-toolbar-title>
          <q-avatar>
            <q-icon name="insights" />
          </q-avatar>
          perfi
        </q-toolbar-title>
        <!-- <SignInWithEthereum /> -->
      </q-toolbar>

      <q-tabs align="left">
        <q-route-tab to="/" label="Transactions" />
        <q-route-tab to="/settings" label="Settings" />
      </q-tabs>
    </q-header>

    <q-page-container>
      <!-- page content -->
      <RouterView />
    </q-page-container>

  </q-layout>
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
