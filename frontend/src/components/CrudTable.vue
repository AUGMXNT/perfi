<script setup lang="ts">
import { onUpdated, ref, watchEffect, computed } from 'vue'
import axios from 'axios';
import { useRouter, useRoute } from 'vue-router'
import { backendUrl } from '@/utils';


const props = defineProps<{
  title: string,
  subtitle?: string,
  records: any[],
  filter?: () => boolean,
  form: any,
  formContext?: any,
  store: any,
  deleteUrl: (record: any) => string,
  onlyColumns?: string[],
  hideAddButton?: boolean
}>()

const emit = defineEmits<{
  (e: 'created', record: any): void
  (e: 'updated', record: any): void
  (e: 'deleted', record: any): void
}>()

const router = useRouter()
const route = useRoute()

const BACKEND_URL = backendUrl()

let showForm = ref(false)
let formRecord = ref({} as any)
let records = ref(props.records)
if (props.filter) {
  records.value = records.value.filter(props.filter)
}

const handleAdd = () => {
 showForm.value = true
 formRecord.value = {} as any
}

const handleUpdated = (record:any) => {
  showForm.value = false;
  console.log('updating store', record)
  emit('updated', record)
  props.store.update(record)
  window.location.reload();
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
  window.location.reload();
}

let columns = (!props.records || props.records.length == 0) ? [] : Object.keys(props.records[0])
  .map(prop => { return {
    name: prop,
    label: prop,
    field: prop,
    align: 'left',
  }})
  .filter(o => ['id'].indexOf(o.name) == -1)
  .filter(o => props.onlyColumns == undefined ? true : props.onlyColumns.indexOf(o.name) != -1)
  .concat([{ name: 'actions', label: 'Actions', field: '', align:'left' }])

</script>

<template>
  <div class="q-mb-lg">
    <q-table
      :rows="records"
      :columns="columns"
      hide-pagination
      :rows-per-page-options="[0]"
    >
      <template v-slot:top>
          <div class="col-10">
            <div class="q-table__title">{{props.title}}</div>
            <q-space/>
            <div v-if="props.subtitle" class="q-table__subtitle text-subtitle">{{props.subtitle}}</div>
          </div>

          <div class="col-2 text-right">
            <q-btn v-if="!showForm && !props.hideAddButton" data-test="addRecord" outline color="primary" icon="add" label="Add" @click="handleAdd" />
          </div>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense round flat color="grey" @click="handleEdit(props)" icon="edit"></q-btn>
          <q-btn dense round flat color="grey" @click="handleDelete(props)" icon="delete"></q-btn>
          <slot name="otherActions" :row="props.row" />
        </q-td>
      </template>
    </q-table>

    <q-dialog full-width v-model="showForm">
      <q-card>
        <q-card-section>
          <component :is="props.form" :record="formRecord" :context="formContext" @canceled="showForm=false" @created="handleCreated" @updated="handleUpdated" />
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>
