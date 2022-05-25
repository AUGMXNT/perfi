<script setup lang="ts">
  import EntityDetails from '@/components/EntityDetails.vue'
  import { useRouter, useRoute, onBeforeRouteLeave } from 'vue-router'
  import type { Entity, Address } from '@/model_types'
  import { ref, watchEffect } from 'vue'
  import axios from 'axios'
  const route = useRoute()

  let entity = ref<Entity|null>(null)

  watchEffect(async () => {
    let url = `${import.meta.env.VITE_BACKEND_URL}/entities/${route.params.entityId}`
    let response = await axios.get(url, { withCredentials: true })
    entity.value = response.data

    url = `${import.meta.env.VITE_BACKEND_URL}/addresses/`
    response = await axios.get(url, { withCredentials: true })
    entity.value.addresses = response.data.filter(a => a.entity_id === entity.value.id)
  })
</script>

<template>
  <q-page padding class="row items-left">
    <div v-if="entity" class="row">
      <div class="col-12">
          <EntityDetails :entity="entity" />
      </div>
    </div>
  </q-page>
</template>
