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
import { storeToRefs } from 'pinia'

const props = defineProps<{
  entity: Entity
}>()

const emit = defineEmits<{
  (e: 'updated', record: Entity): void
  (e: 'deleted', record: Entity): void
}>()

const entityStore = useEntityStore()
const addressStore = useEntityStore()

const router = useRouter()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
let entity = ref(props.entity)
let exchangeImportForm = ref({fileType: '', file: '', accountId: ''})
let exchangeFileUploadInProgress = ref(false)
let calculateTaxInfoForm = ref({year: ''})
let taxCalculationInProgress = ref(false)

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
watchEffect(() => {
  if (!entity.value || !entity.value.addresses || entity.value.addresses.length == 0) return;
  let address = entity.value.addresses[0];

  addressColumns.value = Object.keys(address).map(prop => { return {
    name: prop,
    label: prop,
    field: prop,
  }})
  .filter(o => ['id', 'entity_id', 'ord'].indexOf(o.name) == -1)
  .concat([{ name: 'actions', label: 'Actions', field: '', align:'center' }])
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

let generatedTaxFiles = ref([])
const fetchListOfGeneratedTaxFiles = async () => {
  const url = `${BACKEND_URL}/entities/${entity.value.id}/calculateTaxInfo/`
  const result = await axios.get(url, { withCredentials: true })
  generatedTaxFiles.value = result.data
}
watchEffect(async () => {
  await fetchListOfGeneratedTaxFiles()
})

</script>

<template>
  <CrudTable
    :title="entity.name"
    :records="[entity]"
    :form="EntityForm"
    :delete-url="r => `${BACKEND_URL}/entities/${r.id}`"
    :store="entityStore"
    hide-add-button
    @updated="handleUpdated"
    >
      <template #otherActions="otherActionsProps">
        <q-btn flat @click="router.push({name: 'transactions', params: {entityId: otherActionsProps.entityId}})" label="View Transactions"></q-btn>
      </template>
  </CrudTable>

  <CrudTable
    v-if="entity.addresses"
    title="Addresses"
    :records="entity.addresses"
    :form="AddressForm"
    :delete-url="r => `${BACKEND_URL}/addresses/${r.id}`"
    :store="addressStore"
  />

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
</template>
