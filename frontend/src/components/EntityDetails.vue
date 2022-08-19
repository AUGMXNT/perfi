<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import axios from 'axios';
import EntityForm from '@/components/EntityForm.vue'
import type { Entity } from '@/model_types'
import { useRouter, useRoute } from 'vue-router'
import { RouterLink } from 'vue-router';
import CrudTable from '@/components/CrudTable.vue'
import AddressForm from '@/components/AddressForm.vue'
import { useEntityStore } from '@/stores/entities'
import { useAddressStore } from '@/stores/addresses'
import { useNavigationContextStore } from '@/stores/navigation_context'
import { storeToRefs } from 'pinia'
import { backendUrl } from '@/utils';

const emit = defineEmits<{
  (e: 'updated', record: Entity): void
  (e: 'deleted', record: Entity): void
}>()

const entityStore = useEntityStore()
const addressStore = useAddressStore()
await addressStore.fetch()
const navContextStore = useNavigationContextStore()


const router = useRouter()

const usdFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const BACKEND_URL = backendUrl()
// let entity = ref(props.entity)
let entity = storeToRefs(navContextStore).entity
let exchangeImportForm = ref({fileType: '', file: '', accountId: ''})
let exchangeFileUploadInProgress = ref(false)
let calculateTaxInfoForm = ref({year: ''})
let taxCalculationInProgress = ref(false)
let farmHelperClaimables = ref({})

// we need the entity to get addresses for it
let entity_id = entity.value.id
const allAddresses = storeToRefs(addressStore).all
const predicate = (record) => {
  return record.entity_id == entity_id
}

let generatedTaxFiles = ref([])
const fetchListOfGeneratedTaxFiles = async () => {
  const url = `${BACKEND_URL}/entities/${entity.value.id}/calculateTaxInfo/`
  const result = await axios.get(url, { withCredentials: true })
  generatedTaxFiles.value = result.data
}

const fetchFarmHelperClaimables = async () => {
  const url = `${BACKEND_URL}/entities/${entity.value.id}/farm_helper`
  const result = await axios.get(url, { withCredentials: true })
  farmHelperClaimables.value = result.data
}


const handleUpdated = (updatedEntity: Entity) => {
  emit('updated', updatedEntity)
  entity.value = updatedEntity
}

const handleDelete = async () => {
  if (!confirm(`Are you sure you want to delete the entity '${entity.value.name}'?`)) return;
  const url = `${BACKEND_URL}/labels/${entity.value.id}`
  let response = await axios.delete(url, { withCredentials: true })
  emit('deleted', entity.value.id)
}

let addressColumns = ref<{name: string, label: string}[] | null>([])
watchEffect(async () => {
  if (!entity.value || !entity.value.addresses || entity.value.addresses.length == 0) return;
  let address = entity.value.addresses[0];

  addressColumns.value = Object.keys(address).map(prop => { return {
    name: prop,
    label: prop,
    field: prop,
  }})
  .filter(o => ['id', 'entity_id', 'ord'].indexOf(o.name) == -1)
  .concat([{ name: 'actions', label: 'Actions', field: '', align:'center' }])

  await fetchListOfGeneratedTaxFiles()

  await fetchFarmHelperClaimables()
})

const handleExchangeFileUpload = async () => {
  const formData = new FormData();
  const file = exchangeImportForm.value.file
  formData.append("file", file);
  const url = `${BACKEND_URL}/entities/${entity.value.id}/import_from_exchange/${exchangeImportForm.value.fileType.toLowerCase().replace(' ', '')}/${exchangeImportForm.value.accountId}`
  exchangeFileUploadInProgress.value = true
  const result = await axios.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
  })
  exchangeFileUploadInProgress.value = false
}

const handleCalculateTaxes = async () => {
  const url = `${BACKEND_URL}/entities/${entity.value.id}/calculateTaxInfo/${calculateTaxInfoForm.value.year}`
  taxCalculationInProgress.value = true
  const result = await axios.post(url, { withCredentials: true, responseType: 'blob' })
  await fetchListOfGeneratedTaxFiles()
  taxCalculationInProgress.value = false
}

</script>

<template>
  <div v-if="entity">
  <CrudTable
    v-if="entity"
    :title="entity.name"
    :records="[entity]"
    :form="EntityForm"
    :delete-url="r => `${BACKEND_URL}/entities/${r.id}`"
    :store="entityStore"
    :only-columns="['name', 'note']"
    hide-add-button
    @updated="handleUpdated"
    >
      <template #otherActions="context">
        <q-btn dense flat @click="router.push({name: 'transactions', params: {entityId: context.row.id}})" icon="receipt" label="Transactions"></q-btn>
        <q-btn dense flat @click="router.push({name: 'balances', params: {entityId: context.row.id}})" icon="account_balance" label="Balances"></q-btn>
      </template>
  </CrudTable>

  <CrudTable
    v-if="allAddresses && entity_id"
    title="Addresses"
    :records="allAddresses"
    :filter="predicate"
    :only-columns="['label', 'chain', 'address', 'ord']"
    :form="AddressForm"
    :formContext="{entity}"
    :delete-url="r => `${BACKEND_URL}/addresses/${r.id}`"
    :store="addressStore"
  >

    <template #otherActions="context">
      <q-btn dense flat @click="router.push({name: 'address', params: {addressId: context.row.id}})" icon="attach_money" label="Manage Manual Balances"></q-btn>
    </template>
  </CrudTable>

  <!-- Farm Helper -->
  <q-card style="max-width: 550px;" class="q-mb-lg">
    <q-card-section>
      <div class="text-h6 text-weight-regular q-mb-sm">Farm Helper</div>

      <template v-for="address_label of Object.keys(farmHelperClaimables)" :key="address_label">
          <div>
            <span class="text-subtitle1">{{address_label}}</span>
            &nbsp;
            <span class="">({{farmHelperClaimables[address_label]['address']}})</span>
          </div>

          <template v-for="chain of Object.keys(farmHelperClaimables[address_label].data)" :key="chain">
              <q-markup-table class="farm_helper" separator="horizontal" flat style="max-width: 800px;">
                <thead>
                  <tr>
                    <th colspan="2" class="text-left">
                      <div class="text-subtitel2">{{chain}}</div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="protocol of Object.keys(farmHelperClaimables[address_label].data[chain])" :key="protocol">
                    <td
                      class="text-left"
                      :class="{ should_claim: farmHelperClaimables[address_label].data[chain][protocol].should_claim }"
                      style="max-width: 200px">
                        <img class="logo float-left q-mr-sm" :src="farmHelperClaimables[address_label].data[chain][protocol].logo_url" />
                        <a :href="farmHelperClaimables[address_label].data[chain][protocol].site_url">{{protocol}}</a>
                    </td>
                    <td
                      class="text-right"
                      :class="{ should_claim: farmHelperClaimables[address_label].data[chain][protocol].should_claim }">
                      {{ usdFormatter.format(farmHelperClaimables[address_label].data[chain][protocol].reward_usd_value) }}
                    </td>
                  </tr>
                </tbody>
              </q-markup-table>
          </template>
      </template>
    </q-card-section>
  </q-card>

  <!-- Import From Exchange -->
  <q-card style="max-width: 550px;" class="q-mb-lg">
    <q-card-section>
        <div class="text-h6 text-weight-regular">Import Transactions from an Exchange</div>
        <div class="text-subtitle q-mb-sm">If you have transactions from Coinbase, Coinbase Pro, Gemini, or Kraken, you can import them into perfi.</div>
        <div class="text-subtitle">
          For help learning about how to export the appropriate file for each supported exchange, <a href="">click here</a>.
        </div>
    </q-card-section>

    <q-card-section class="col">
      <q-file
        class="q-mb-sm"
        v-model="exchangeImportForm.file"
        :multiple="false"
        label="Select exchange export file"
        outlined
        dense
      />
      <q-select
        class="q-mb-sm"
        label="Exchange Export Type"
        v-model="exchangeImportForm.fileType"
        outlined
        dense
        :options="['Coinbase', 'Coinbase Pro', 'Gemini', 'Kraken']"
      />
      <q-input
        class="q-mb-sm"
        type="text"
        v-model="exchangeImportForm.accountId"
        label="Account ID"
        hint="This can be any arbitrary string to identify your account uniquely. For example: 'Coinbase 1'"
        outlined
        dense
      />
      <q-btn label="Upload" color="secondary" icon="upload" @click="handleExchangeFileUpload" />
    </q-card-section>

    <q-inner-loading
      :showing="exchangeFileUploadInProgress"
      label="Please wait. This may take a minute..."
      label-style="font-weight: bold"
    />
  </q-card>

  <!-- Regenerate Cost Basis -->
  <q-card style="max-width: 550px;">
    <q-card-section>
        <div class="text-h6 text-weight-regular">Calculate Tax Info</div>

        <div class="text-subtitle q-mb-sm">
          <p>After you have added all of your wallet addresses and imported any transactions from exchanges, you're ready to calculate your tax info.</p>
          <p>perfi will crawl all of the on-chain data from the Ethereum, Avalanche, Fantom, and Polygon networks and then calculate your short/long-term capital gains/losses and income for a given calendar year.</p>
        </div>

        <div class="row">
        <div class="col-5">
          <q-input
            class="q-mb-sm"
            type="text"
            v-model="calculateTaxInfoForm.year"
            label="Year"
            hint="Enter a 4-digit year. For example: 2021"
            outlined
            dense
            float-left
          />
        </div>
        <div class="col q-ml-sm">
          <q-btn label="Calculate Tax Info" color="secondary" icon="calculate" @click="handleCalculateTaxes" />
        </div>
        </div>
    </q-card-section>

    <q-card-section v-if="generatedTaxFiles.length > 0">
      <div class="text-subtitle2">Generarted Files</div>
      <div class="text-subtitle q-mb-sm">
        <p>Here's a list of all of your generated tax reports:</p>
      </div>
      <ul>
        <li v-for="file in generatedTaxFiles" :key="file">
          <a :href="`${BACKEND_URL}/static/${entity.id}/${file}`">{{file}}</a>
        </li>
      </ul>
    </q-card-section>

    <q-inner-loading
      :showing="taxCalculationInProgress"
      label="Please wait. This may take _several minutes_..."
      label-style="font-weight: bold"
    />
  </q-card>
  </div>
</template>

<style scoped>
.farm_helper th {
  padding-left: 0;
}
.farm_helper tbody td {
  padding-left: 0;
  color: #666;
}
.farm_helper tbody td.should_claim {
  font-weight: bold;
  color: inherit
}
.farm_helper tbody td img.logo {
  max-width: 20px;
}
</style>
