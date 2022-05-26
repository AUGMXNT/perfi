<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import axios from 'axios';
import { useRouter, useRoute } from 'vue-router'


const props = defineProps<{
  title: string,
  records: any[],
  form: any,
  store: any,
  deleteUrl: (record: any) => string,
  hideAddButton?: boolean
}>()

const emit = defineEmits<{
  (e: 'created', record: any): void
  (e: 'updated', record: any): void
  (e: 'deleted', record: any): void
}>()

const router = useRouter()
const route = useRoute()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

let showForm = ref(false)
let formRecord = ref({} as any)
let records = ref(props.records)

const handleAdd = () => {
 showForm.value = true
 formRecord.value = {} as any
}

const handleUpdated = (record:any) => {
  showForm.value = false;
  console.log('updating store', record)
  emit('updated', record)
  props.store.update(record)
}

const handleCreated = (record: any) => {
  records.value = [record, ...records.value]
  showForm.value = false;
  props.store.add(record)
}

const handleEdit = (rowProps: any) => {
  formRecord.value = Object.assign({}, rowProps.row)
  showForm.value = true
}

const handleDelete = async (rowProps: any) => {
  const record = rowProps.row
  if (!confirm(`Are you sure you want to delete the record with id '${record.id}'?`)) return;
  let response = await axios.delete(props.deleteUrl(record), { withCredentials: true })
  emit('deleted', record)
  props.store.delete(record.id)
}

const columns = !props.records || props.records.length == 0 ? [] : Object.keys(props.records[0])
  .map(prop => { return {
    name: prop,
    label: prop,
    field: prop,
    align: 'left',
  }})
  .filter(o => ['id'].indexOf(o.name) == -1)
  .concat([{ name: 'actions', label: 'Actions', field: '', align:'left' }])

</script>

<template>
  <div class="q-mb-lg">
    <q-table
      title="Addresses"
      :rows="props.records"
      :columns="columns"
      hide-pagination
    >
      <template v-slot:top>
        <div class="q-table__title">{{props.title}}</div>
        <q-space/>
        <q-btn v-if="!showForm && !props.hideAddButton" data-test="addRecord" outline color="primary" icon="add" label="Add" @click="handleAdd" />

      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense round flat color="grey" @click="handleEdit(props)" icon="edit"></q-btn>
          <q-btn dense round flat color="grey" @click="handleDelete(props)" icon="delete"></q-btn>
          <slot name="otherActions" :entityId="props.row.id" />
        </q-td>
      </template>
    </q-table>

    <q-dialog full-width v-model="showForm">
      <q-card>
        <q-card-section>
          <component :is="props.form" :record="formRecord" @canceled="showForm=false" @created="handleCreated" @updated="handleUpdated" />
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>
