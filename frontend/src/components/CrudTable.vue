<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import axios from 'axios';
import EntityForm from '@/components/EntityForm.vue'
import type { Entity, Address } from '@/model_types'
import { useRouter, useRoute } from 'vue-router'


const props = defineProps<{
  records: Address[],
  form: any,
}>()

const emit = defineEmits<{
  (e: 'created', record: Address): void
  (e: 'updated', record: Address): void
  (e: 'deleted', record: Address): void
}>()

const router = useRouter()
const route = useRoute()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

let isEditing = ref(false)
let editingRecord = ref({label: 'test'})

const handleUpdated = (id: number, record:Address) => {
  isEditing.value = false;
  emit('updated', id, record)
}

const handleDelete = async (record) => {
  if (!confirm(`Are you sure you want to delete the record with id '${record.name}'?`)) return;
  const url = `${BACKEND_URL}/addresses/${record.id}`
  let response = await axios.delete(url, { withCredentials: true })
  emit('deleted', record)
}

const columns = Object.keys(props.records[0])
  .map(prop => { return {
    name: prop,
    label: prop,
    field: prop,
  }})
  .filter(o => ['id'].indexOf(o.name) == -1)
  .concat([{ name: 'actions', label: 'Actions', field: '', align:'center' }])


const editRow = (props) => {
  console.log(props)
  editingRecord.value = props.row
  isEditing.value = true
}

</script>

<template>
  <q-table
    title="Addresses"
    :rows="props.records"
    :columns="columns"
    hide-pagination
  >
    <template v-slot:body-cell-actions="props">
      <q-td :props="props">
        <q-btn dense round flat color="grey" @click="editRow(props)" icon="edit"></q-btn>
        <q-btn dense round flat color="grey" @click="deleteRow(props)" icon="delete"></q-btn>
      </q-td>
    </template>
  </q-table>

  <q-dialog full-width v-model="isEditing">
    <q-card>
      <q-card-section>
        <component :is="props.form" :record="editingRecord" @canceled="isEditing=false" @created="isEditing=false" @updated="isEditing = false" />
      </q-card-section>
    </q-card>
  </q-dialog>
</template>
