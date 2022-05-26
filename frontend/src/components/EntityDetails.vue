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

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
let entity = ref(props.entity)

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
  />

  <CrudTable
    v-if="entity.addresses"
    title="Addresses"
    :records="entity.addresses"
    :form="AddressForm"
    :delete-url="r => `${BACKEND_URL}/addresses/${r.id}`"
    :store="addressStore"
  />
</template>
