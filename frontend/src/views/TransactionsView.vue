<script setup lang="ts">
import TxLogicalsList from '@/components/TxLogicalsList.vue'
import { ref, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import type { Entity } from "@/model_types";
import { useEntityStore } from '@/stores/entities'
import { storeToRefs } from 'pinia'
import { date } from 'quasar'

const displayTimestamp = (timestamp: string) => date.formatDate(timestamp, 'YYYY-MM-DDTHH:mm:ss.SSSZ')

const entityStore = useEntityStore()
const route = useRoute()

let entity = ref()

watchEffect(async () => {
  await entityStore.fetch()
  entity.value = entityStore.getById(route.params.entityId)
})

</script>

<template>
  <q-page padding v-if="entity">
    <div class="row">
      <div class="col-12">

        <div clsss="row">
          <div class="col">
            <span class="text-h5">{{entity.name}}</span>
          </div>
        </div>

        <div class="row">
          <div class="col">
            <TxLogicalsList :entity="entity"/>
          </div>
        </div>

      </div>
    </div>
  </q-page>
</template>
