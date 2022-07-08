<script setup lang="ts">
import { ref, reactive, nextTick, onMounted, watchEffect, computed, onBeforeMount } from "vue"
import axios from "axios";
import EntityForm from '@/components/EntityForm.vue'
import CrudTable from '@/components/CrudTable.vue'
import { useRouter, useRoute, onBeforeRouteLeave } from 'vue-router'
import type { Entity } from "@/model_types";

import { useEntityStore } from '@/stores/entities'
import { storeToRefs } from 'pinia'
import { backendUrl } from "@/utils";


const router = useRouter()
const route = useRoute()

const entityStore = useEntityStore()
await entityStore.fetch()
const allEntities = storeToRefs(entityStore).all

const BACKEND_URL = backendUrl()

</script>

<template>
  <CrudTable
    title="Entities"
    :records="allEntities"
    :form="EntityForm"
    :delete-url="r => `${BACKEND_URL}/entities/${r.id}`"
    :store="entityStore"
  >
    <template #otherActions="otherActionsProps">
      <q-btn flat @click="router.push({name: 'entity', params: {entityId: otherActionsProps.entityId}})" label="Manage"></q-btn>
      <q-btn flat @click="router.push({name: 'transactions', params: {entityId: otherActionsProps.entityId}})" label="View Transactions"></q-btn>
    </template>
  </CrudTable>
</template>

<style scoped>
</style>
