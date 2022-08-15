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
  <q-page padding class="row items-left">
      <div class="col-7">

        <CrudTable
          v-if="allEntities !== null"
          title="Entities"
          :records="allEntities"
          :form="EntityForm"
          :delete-url="r => `${BACKEND_URL}/entities/${r.id}`"
          :store="entityStore"
        >
          <template #otherActions="context">
              <q-btn dense flat @click="router.push({name: 'entity', params: {entityId: context.row.id}})" icon="settings" label="Manage"></q-btn>
              <q-btn dense flat @click="router.push({name: 'transactions', params: {entityId: context.row.id}})" icon="receipt" label="Transactions"></q-btn>
              <q-btn dense flat @click="router.push({name: 'balances', params: {entityId: context.row.id}})" icon="account_balance" label="Balances"></q-btn>
          </template>
        </CrudTable>

      </div>
  </q-page>
</template>

<style scoped>
</style>
