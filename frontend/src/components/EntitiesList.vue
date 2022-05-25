<script setup lang="ts">
import { ref, reactive, nextTick, onMounted, watchEffect, computed, onBeforeMount } from "vue"
import axios from "axios";
import EntityForm from '@/components/EntityForm.vue'
import { useRouter, useRoute, onBeforeRouteLeave } from 'vue-router'
import type { Entity } from "@/model_types";

import { useEntitiesStore } from '@/stores/entities'
import { storeToRefs } from 'pinia'


const router = useRouter()
const route = useRoute()

const store = useEntitiesStore()
store.fetch()
const allEntities = storeToRefs(store).all

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
let entities = ref<Entity[]>([])
let loading = ref<boolean>(false)
let isAdding = ref<boolean>(false)

const columns = [
  { name: 'name', align: 'left', label: 'Name', field: 'name', sortable: true },
  { name: 'note', align: 'left', label: 'Note', field: 'note' }
]

const handleDeleted = (id: number) => {
  store.delete(id)
  entities.value = entities.value.filter(l => l.id !== id)
}

const handleSave = async (original: Entity, updatedPropName: string, updatedPropValue: string) => {
  const updated = {...original, [updatedPropName]: updatedPropValue }
  const url = `${BACKEND_URL}/entities/${original.id}`
  const response = await axios.put(url, { ...updated }, { withCredentials: true })
  store.update(original.id, updatedPropName, updatedPropValue)
}

const handleAdd = () => {
 isAdding.value = true
}

const handleCreated = (entity: Entity) => {
  entities.value = [entity, ...entities.value]
  isAdding.value = false;
  store.add(entity)
}

const handleCanceled = () => {
  isAdding.value = false;
}

</script>

<template>
  <q-table
    title="Entities"
    :rows="allEntities"
    :columns="columns"
    row-key="name"
    data-test="entities"
  >

    <template v-slot:top>
      <div class="q-table__title">Entities</div>
      <q-space/>
      <q-btn v-if="!isAdding" data-test="addEntity" outline color="primary" :disable="loading" icon="add" label="Add" @click="handleAdd" />

    </template>

      <template v-slot:header v-if="isAdding">
        <q-tr>
          <q-th colspan="100%">
            <EntityForm @created="handleCreated" @canceled="handleCanceled" />
          </q-th>
        </q-tr>
      </template>

    <template v-if="!isAdding" v-slot:body="props">
          <q-tr :props="props" data-clas="entity">
            <q-td key="name" :props="props">
              {{ props.row.name }}
              <q-popup-edit v-model="props.row.name" title="Name" buttons v-slot="scope" @save="(updatedValue, _) => handleSave(props.row, 'name', updatedValue)">
                <q-input v-model="scope.value" dense autofocus @keyup.enter="scope.set" />
              </q-popup-edit>
            </q-td>

            <q-td key="note" :props="props">
              {{ props.row.note }}
              <q-popup-edit v-model="props.row.note" title="Note" buttons v-slot="scope" @save="(updatedValue, _) => handleSave(props.row, 'note', updatedValue)">
                <q-input v-model="scope.value" dense autofocus @keyup.enter="scope.set" />
              </q-popup-edit>
            </q-td>
          </q-tr>
    </template>
  </q-table>
</template>

<style scoped>
</style>
