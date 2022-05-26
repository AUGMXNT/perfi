<script setup lang="ts">
import { ref, reactive, nextTick, onMounted, watchEffect, computed, onBeforeMount } from "vue"
import axios from "axios";
import EntityForm from '@/components/EntityForm.vue'
import CrudTable from '@/components/CrudTable.vue'
import { useRouter, useRoute, onBeforeRouteLeave } from 'vue-router'
import type { Entity } from "@/model_types";

import { useEntityStore } from '@/stores/entities'
import { storeToRefs } from 'pinia'


const router = useRouter()
const route = useRoute()

const entityStore = useEntityStore()
entityStore.fetch()
const allEntities = storeToRefs(entityStore).all

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

</script>

<template>
  <CrudTable
    v-if="allEntities.length > 0"
    title="Entities"
    :records="allEntities"
    :form="EntityForm"
    :delete-url="r => `${BACKEND_URL}/entities/${r.id}`"
    :store="entityStore"
  >
    <template #otherActions="otherActionsProps">
      <q-btn flat @click="router.push({name: 'entity', params: {entityId: otherActionsProps.entityId}})" label="Manage Addresses"></q-btn>
    </template>
  </CrudTable>


  <!-- <q-table
    title="Entities"
    :rows="allEntities"
    :columns="columns"
    row-key="name"
    data-test="entities"
    hide-pagination
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
  </q-table> -->

  <!-- <q-list>
    <q-item-label header>Entities</q-item-label>
      <q-item v-for="entity in allEntities" :key="entity.id">
        <q-item-section>
          <q-item-label>{{ entity.name }}</q-item-label>
          <q-item-label caption>{{ entity.note }}</q-item-label>
        </q-item-section>
        <q-item-section top side>
          <div class="text-grey-8 q-gutter-xs">
            <q-btn class="gt-xs" size="12px" flat dense round icon="edit" />
            <q-btn class="gt-xs" size="12px" flat dense round icon="delete" />
          </div>
        </q-item-section>
        <q-item-section top side>
          <div class="text-grey-8 q-gutter-xs">
            <q-btn size="12px" label="Manage Addresses" :to="`/settings/entity/${entity.id}`" flat dense />
          </div>
        </q-item-section>
      </q-item>
  </q-list> -->
</template>

<style scoped>
</style>
