<script setup lang="ts">
import axios from "axios";
import { ref, reactive, nextTick, watchEffect } from "vue"
import TxLogicalListItem from '@/components/TxLogicalListItem.vue'
import { displayAddress, displayTimestamp, txIconUrl } from '@/utils.ts'


const props = defineProps<{
  entity: string
}>()

let page_num = ref(0)
let items_per_page = ref(100)

let fetch_url = `http://localhost:8001/tx_logicals/${props.entity}`
let tx_logicals = ref([])
let loading = ref(false)

watchEffect(async () => {
  loading.value = true
  let response = await axios.get(fetch_url, { params: { page: page_num.value, limit: items_per_page.value } })
  tx_logicals.value = tx_logicals.value.concat(response.data)
  loading.value = false
})

const loadNextPage = () => {
  page_num.value += 1;
}

const dateAndTime = (txl: TxLogical) => displayTimestamp(txl.timestamp).split(' ')


const columns = [
   { name: 'date_and_time', align: 'left', label: 'Date', field: txl => dateAndTime(txl)  },
   { name: 'type', align: 'left', label: 'Type', field: 'tx_logical_type' },
   { name: 'transactions', align: 'left', label: 'Transactions', field: txl => txl },
]

const rows = tx_logicals

</script>

<template>
  <q-table
      title="Transactions"
      :rows="rows"
      :columns="columns"
      row-key="hash"
      :rows-per-page-options="[0]"
  >
    <template v-slot:body-cell-date_and_time="props">
      <q-td :props="props">
        <div>
          {{props.value[0]}} <br/> {{props.value[1]}}
        </div>
      </q-td>
    </template>

    <template v-slot:body-cell-type="props">
      <q-td :props="props">
        {{props.value}}
      </q-td>
    </template>

    <template v-slot:body-cell-transactions="props">
      <q-td :props="props">
        <div class="logicalOut row items-center q-pb-sm" v-for="tx_ledger in props.value.outs">
          <img class="txIcon" :src="txIconUrl(tx_ledger)" />
          &nbsp;-
          &nbsp;{{tx_ledger.amount.toFixed(2)}}
          &nbsp;<span class="text-weight-bold">{{tx_ledger.symbol}}</span>
          &nbsp;<span>
            to {{displayAddress(tx_ledger, 'to')}}
            <q-tooltip anchor="bottom middle" self="center middle">
              {{tx_ledger.to_address}}
            </q-tooltip>
          </span>
          &nbsp;<span v-if="tx_ledger.price_usd">
            @ {{tx_ledger.price_usd?.toFixed(2)}} per
          </span>
        </div>

        <div class="logicalIn row items-center q-pb-sm" v-for="tx_ledger in props.value.ins">
          <img class="txIcon" :src="txIconUrl(tx_ledger)" />
          &nbsp;+
          &nbsp;{{tx_ledger.amount.toFixed(2)}}
          &nbsp;<span class="text-weight-bold">{{tx_ledger.symbol}}</span>
          &nbsp;<span>
            from {{displayAddress(tx_ledger, 'from')}}
            <q-tooltip anchor="bottom middle" self="center middle">
              {{tx_ledger.from_address}}
            </q-tooltip>
          </span>
          &nbsp;<span v-if="tx_ledger.price_usd">
            @ {{tx_ledger.price_usd?.toFixed(2)}} per
          </span>
        </div>
      </q-td>
    </template>

    <template v-slot:bottom>
      <q-btn style="background: #efefef; color: black" @click="loadNextPage">
        {{ loading ? "Loading..." : "Load More"}}
      </q-btn>
    </template>

  </q-table>

  <!-- <q-list separator>
    <TxLogicalListItem
      v-for="tx_logical in tx_logicals"
      :tx_logical="tx_logical"
      :key="tx_logical.id"
    />
  </q-list> -->

</template>

<style scoped>
img.txIcon {
  width: 20px;
  height: 20px;
}
img.txIcon::before {
  content: '';
  width: 20px;
  height: 20px;
  background-color: #eee;
  position: absolute;
 }
</style>
