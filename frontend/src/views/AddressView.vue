<script setup lang="ts">
import AddressDetails from '@/components/AddressDetails.vue'
import type { Address } from '@/model_types'
import { ref, watchEffect } from 'vue'
import axios from 'axios'
import { routerViewLocationKey, useRoute } from 'vue-router'
import { useNavigationContextStore } from '@/stores/navigation_context'

let address = ref<Address>()
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL

const route = useRoute()

const navContextStore = useNavigationContextStore()

watchEffect(async () => {
  if (route.params.addressId === undefined) return

  const response = await axios.get(`${BACKEND_URL}/addresses/${route.params.addressId}`)
  address.value = response.data
  console.log('===== hello')
  navContextStore.setAddress(address.value)
})
</script>

<template>
  <q-page padding class="row items-left">
    <div class="row">
      <div class="col-12">
          <AddressDetails v-if="address" :address="address" />
      </div>
    </div>
  </q-page>
</template>
