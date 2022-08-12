<script setup lang="ts">
import { onBeforeMount, ref, watchEffect } from 'vue'
import axios from 'axios';
import type { Address, AssetBalance } from '@/model_types'
import { useRouter, useRoute } from 'vue-router'
import { RouterLink } from 'vue-router';
import CrudTable from '@/components/CrudTable.vue'
import AssetBalanceForm from '@/components/AssetBalanceForm.vue'
import { useAssetBalanceStore } from '@/stores/asset_balance'
import { storeToRefs } from 'pinia'
import { useNavigationContextStore } from '@/stores/navigation_context';

const navContextStore = useNavigationContextStore()

const route = useRoute()

const assetBalanceStore = useAssetBalanceStore(route.params.addressId.toString())()
await assetBalanceStore.fetch()

let address = storeToRefs(navContextStore).address

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL
let allAssetBalances = storeToRefs(assetBalanceStore).all

let addressAssetBalances = ref<AssetBalance[]>([])

watchEffect(() => {
  if (address.value === null) return
  addressAssetBalances.value = allAssetBalances.value.filter(ab => ab.address === address.value.address)
})




const handleUpdatedAssetBalance = () => {
  // Intentional no-op for now
  return
 }

</script>

<template>
  <div v-if="address">
    <div class="q-mb-lg">
      <div class="text-h5">
        {{address.label}}
      </div>
      <div class="text-subtitle">
        {{address.chain}} @ {{address.address}}
      </div>
    </div>

    <CrudTable
      title="Manual Asset Balances"
      subtitle="Use this space to track balances for assets that perfi doesn't (or can't) ingest yet."
      :records="addressAssetBalances"
      :only-columns="['symbol', 'exposure_symbol', 'amount', 'price',]"
      :form="AssetBalanceForm"
      :form-context="{address: address}"
      :delete-url="r => `${BACKEND_URL}/addresses/${address.id}/manual_balances/${r.id}`"
      :store="assetBalanceStore"
      @updated="handleUpdatedAssetBalance"
      >
    </CrudTable>
  </div>
</template>
