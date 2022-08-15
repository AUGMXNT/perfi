<script setup lang="ts">
import EntityDetails from '@/components/EntityDetails.vue'
import { useRouter, useRoute, } from 'vue-router'
import type { Entity, Address } from '@/model_types'
import { ref, watchEffect } from 'vue'
import axios from 'axios'
import { useNavigationContextStore } from '@/stores/navigation_context'
import { storeToRefs } from 'pinia'
import { backendUrl } from '@/utils'

const route = useRoute()

let entity = ref<Entity|null>(null)
const navContextStore = useNavigationContextStore()
const BACKEND_URL = backendUrl()

const loadEntity = async () => {
  if (route.params.entityId === undefined) return

  let url = `${BACKEND_URL}/entities/${route.params.entityId}`
  let response = await axios.get(url, { withCredentials: true })
  entity.value = response.data

  url = `${BACKEND_URL}/addresses/`
  response = await axios.get(url, { withCredentials: true })
  entity.value.addresses = response.data.filter(a => a.entity_id === entity.value.id)
  navContextStore.setEntity(entity.value)

  if (route.params.addressId) {
    response = await axios.get(`${BACKEND_URL}/addresses/${route.params.addressId}`)
    navContextStore.setAddress(response.data)
  }
}

await loadEntity()
</script>

<template>
  <q-page padding class="row items-left">
    <div class="row">
      <div class="col-12">
          <router-view :key="route.path"/>
      </div>
    </div>
  </q-page>
</template>
