<script setup lang="ts">
import { useRoute } from 'vue-router';
const route = useRoute()
</script>

<template>
  <q-page padding class="row items-left">
    <div class="row">
      <div class="col-12">
          <router-view :key="route.path" />
      </div>
    </div>
  </q-page>
</template>
