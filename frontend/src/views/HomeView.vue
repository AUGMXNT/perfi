<script setup lang="ts">
import TxLogicalsList from '@/components/TxLogicalsList.vue'

import { date } from 'quasar'

const displayTimestamp = (timestamp: string) => date.formatDate(timestamp, 'YYYY-MM-DDTHH:mm:ss.SSSZ')

const entity = 'Tetranode'
</script>

<template>
  <q-page padding>
    <div class="row">
      <div class="col-12">

        <div clsss="row">
          <div class="col">
            <span class="text-h5">Home</span>
          </div>
        </div>

        <div class="row">
          <div class="col">
            Home
          </div>
        </div>

      </div>
    </div>
  </q-page>
</template>
