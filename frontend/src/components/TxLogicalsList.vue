<script setup lang="ts">
import axios from "axios";
import { ref, reactive, nextTick, watchEffect } from "vue"
import TxLogicalListItem from '@/components/TxLogicalListItem.vue'
import { displayAddress, displayTimestamp, txIconUrl } from '@/utils.ts'
import type { Entity } from "@/model_types";
import { useQuasar } from 'quasar'

const props = defineProps<{
  entity: Entity
}>()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
const quasar = useQuasar()

let page_num = ref(0)
let items_per_page = ref(100)

let fetch_url = `http://localhost:8001/entities/${props.entity.id}/tx_logicals`
let tx_logicals = ref<TxLogical[]>([])
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

let showForm = ref(false)
let editingTxLedgerLogical = ref<TxLogical>(null)
let editingTxLedger = ref({} as TxLedger)

const handleEditClick = (txLogicalId, txLedgerId) => {
  // Find the tx ledger
  const txLogical = tx_logicals.value.find(tlo => tlo.id == txLogicalId)
  editingTxLedgerLogical.value = txLogical
  const txLedger = [...txLogical.ins, ...txLogical.outs].find(tle => tle.id == txLedgerId)
  editingTxLedger.value = Object.assign({}, txLedger)
  editingTxLedger.value.txLogical = txLogical
  showForm.value = true
}

const updateLedgerPrice = async () => {
  const txLedger = editingTxLedger.value
  const url = `${BACKEND_URL}/tx_ledgers/${txLedger.id}/tx_ledger_price/${txLedger.price_usd}`
  const result = await axios.put(url, {}, { withCredentials: true })
  quasar.notify({
    type: 'positive',
    message: 'Ledger item price updated.'
  })

  // Find the txLedger inside the txLogical it belongs to, and update it's price_usd
  const txLogical = txLedger.txLogical
  const txLedgers = txLedger.direction == 'in' ? txLogical.ins : txLogical.outs
  const index = txLedgers.findIndex(tle => tle.id == txLedger.id)
  const updatedTxLedger = Object.assign(txLedgers[index], {price_usd: Number(txLedger.price_usd)})
  txLedgers[index] = updatedTxLedger

  // Reset form
  editingTxLedger.value = null
  showForm.value = false
}

</script>

<template>
  <q-table
      title="Transactions"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :rows-per-page-options="[0]"
  >
    <template v-slot:header="props">
      <q-tr :props="props">
        <q-th auto-width> Toggle </q-th>
        <q-th key="date"> Date </q-th>
        <q-th key="type"> Type </q-th>
        <q-th key="transactions"> Transactions </q-th>
      </q-tr>
    </template>

    <template v-slot:body="props">
      <q-tr :props="props">
        <q-td auto-width>
          <q-btn size="sm" color="accent" round dense @click="props.expand = !props.expand" :icon="props.expand ? 'remove' : 'add'" />
        </q-td>

        <q-td key="date_and_time" :props="props">
          <div>
            {{dateAndTime(props.row)[0]}} <br/> {{dateAndTime(props.row)[1]}}
          </div>
        </q-td>

        <q-td key="type" :props="props">
          {{props.row.tx_logical_type}}
        </q-td>


        <q-td key="transactions" :props="props">
          <div class="logicalOut row items-center q-pb-sm" v-for="tx_ledger in props.row.outs">
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
            &nbsp;<span v-if="tx_ledger.price_source">
              via {{tx_ledger.price_source }}
            </span>
            <q-btn flat size="xs" label="Edit" @click="handleEditClick(props.row.id, tx_ledger.id)" color="secondary" />
          </div>

          <div class="logicalIn row items-center q-pb-sm" v-for="tx_ledger in props.row.ins">
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
            &nbsp;<span v-if="tx_ledger.price_source">
              via {{tx_ledger.price_source }}
            </span>
            <q-btn flat size="xs" label="Edit" @click="handleEditClick(props.row.id, tx_ledger.id)" color="secondary" />
          </div>

        </q-td>
      </q-tr>

      <q-tr v-show="props.expand" :props="props">
        <q-td colspan="100%">
          <div class="text-left row inline">
              <span>Unit prices:</span>
              <q-input type="text" v-model="props.row.foo" label="foo" stacked />
              <q-btn label="Update" color="secondary" />
          </div>
        </q-td>
      </q-tr>
    </template>


    <!-- <template v-slot:body-cell-date_and_time="props">
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
    </template> -->

    <template v-slot:bottom>
      <q-btn style="background: #efefef; color: black" @click="loadNextPage">
        {{ loading ? "Loading..." : "Load More"}}
      </q-btn>
    </template>

  </q-table>

  <q-dialog v-model="showForm">
    <q-card>
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Edit price for ledger entry</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup />
      </q-card-section>
      <q-card-section>
        <div>
            <div> {{dateAndTime(editingTxLedgerLogical)[0]}} at {{dateAndTime(editingTxLedgerLogical)[1]}} </div>
            <div> {{editingTxLedgerLogical.tx_logical_type}} </div>
            <div>
              <img class="txIcon" :src="txIconUrl(editingTxLedger)" />
              &nbsp;+
              &nbsp;{{editingTxLedger.amount.toFixed(2)}}
              &nbsp;<span class="text-weight-bold">{{editingTxLedger.symbol}}</span>
              &nbsp;<span>
                from {{editingTxLedger.from_address}}
              </span>
            </div>

        </div>
        <q-input
          label="Price"
          type="text"
          v-model="editingTxLedger.price_usd"
        /> <!-- TODO: Validation -->
        <q-btn label="Save Price" type="submit" color="primary" @click="updateLedgerPrice" />
      </q-card-section>
    </q-card>
  </q-dialog>


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
.q-table th {
  text-align:left;
}
</style>
