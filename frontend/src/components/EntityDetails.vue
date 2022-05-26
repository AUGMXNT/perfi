<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import axios from 'axios';
import EntityForm from '@/components/EntityForm.vue'
import type { Entity } from '@/model_types'
import { useRouter, useRoute } from 'vue-router'
import { RouterLink } from 'vue-router';
import CrudTable from '@/components/CrudTable.vue'
import AddressForm from '@/components/AddressForm.vue'

const props = defineProps<{
  entity: Entity
}>()

const emit = defineEmits<{
  (e: 'updated', id: number, name: string, note: string): void
  (e: 'deleted', id: number): void
}>()

const router = useRouter()
const route = useRoute()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
let entity = ref(props.entity)

let isEditing = ref(false)

let loading = ref(false)

const updateCachedEntity = (attr: keyof Entity, value: string) => {
  (entity.value as any)[attr] = value
}

const handleUpdated = (id: number, name:string, note: string) => {
  isEditing.value = false;
  emit('updated', id, name, note)
  updateCachedEntity('name', name)
  updateCachedEntity('note', note)
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
  <q-card flat bordered class="q-mb-lg">
    <q-card-section>
      <div class="row">
        <div class="col q-ml-md" v-if="!isEditing">
          <p class="text-subtitle2">
            {{entity.name}}
          </p>
          <p>
            {{entity.note}}
          </p>

          <EntityForm v-if="isEditing" :entity="entity" @updated="handleUpdated"/>
        </div>
      </div>
    </q-card-section>


    <q-card-actions align="left">
      <q-btn flat v-if="isEditing" @click="isEditing = false">Cancel</q-btn>
      <q-btn flat v-if="!isEditing" @click="isEditing = true">Edit</q-btn>
      <q-btn flat v-if="!isEditing" @click="handleDelete">Delete</q-btn>
    </q-card-actions>
  </q-card>

  <CrudTable
    v-if="entity.addresses"
    title="Addresses"
    :records="entity.addresses"
    :form="AddressForm"
    :delete-url="r => `${BACKEND_URL}/addresses/${r.id}`"
  />

  <!-- <q-table
    title="Addresses"
    :rows="entity.addresses"
    :columns="addressColumns"
    hide-pagination
  >
    <template v-slot:body-cell-actions="props">
      <q-td :props="props">
        <q-btn dense round flat color="grey" @click="editRow(props)" icon="edit"></q-btn>
        <q-btn dense round flat color="grey" @click="deleteRow(props)" icon="delete"></q-btn>
      </q-td>
    </template>
  </q-table> -->
</template>
