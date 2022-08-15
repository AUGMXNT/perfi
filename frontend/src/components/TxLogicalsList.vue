<script setup lang="ts">
import axios from "axios";
import { ref, reactive, nextTick, watchEffect } from "vue"
import TxLogicalListItem from '@/components/TxLogicalListItem.vue'
import { displayAddress, displayTimestamp, txIconUrl } from '@/utils.ts'
import type { Entity } from "@/model_types";
import { useQuasar } from 'quasar'
import { copyToClipboard } from 'quasar'
import { backendUrl } from "@/utils";

const props = defineProps<{
  entity: Entity
}>()

const BACKEND_URL = backendUrl()
const quasar = useQuasar()

let page_num = ref(0)
let items_per_page = ref(100)

let fetch_url = `${BACKEND_URL}/entities/${props.entity.id}/tx_logicals`
let tx_logicals = ref<TxLogical[]>([])
let hiddenLogicalIds = ref([])
let loading = ref(false)
let txLogicalTypes = ref<string[]>([])

const loadTxLogicals = async () => {
  loading.value = true
  let response = await axios.get(fetch_url, { params: { page: page_num.value, limit: items_per_page.value } })
  tx_logicals.value = response.data

  response = await axios.get(`${BACKEND_URL}/tx_logical_types`)
  txLogicalTypes.value = response.data

  loading.value = false
}

watchEffect(async () => {
  loadTxLogicals()
})

const loadNextPage = () => {
  page_num.value += 1;
}

const dateAndTime = (txl: TxLogical) => displayTimestamp(txl.timestamp).split(' ')


const columns = [
   { name: 'date_and_time', align: 'left', label: 'Date', field: txl => dateAndTime(txl)  },
   { name: 'type', align: 'left', label: 'Type', field: 'tx_logical_type' },
   { name: 'transactions', align: 'left', label: 'Transactions', field: txl => txl },
   { name: 'fee', align: 'left', label: 'Fee', field: 'fee' },
]

const rows = tx_logicals

let showEditPriceForm = ref(false)
let showEditTxLogicalTypeForm = ref(false)
let editingTxLogical = ref<TxLogical>(null)
let editingTxLedgerLogical = ref<TxLogical>(null)
let editingTxLedger = ref({} as TxLedger)
let showMoveTransactionForm = ref(false)
let newTxLogicalId = ref('')

const setEditingTxLedger = (txLogicalId, txLedgerId) => {
  // Find the tx ledger
  const txLogical = tx_logicals.value.find(tlo => tlo.id == txLogicalId)
  editingTxLedgerLogical.value = txLogical
  const txLedger = [...txLogical.ins, ...txLogical.outs].find(tle => tle.id == txLedgerId)
  editingTxLedger.value = Object.assign({}, txLedger)
  editingTxLedger.value.txLogical = txLogical
}

const handleEditClick = (txLogicalId, txLedgerId) => {
  setEditingTxLedger(txLogicalId, txLedgerId)
  showEditPriceForm.value = true
}

const handleEditTxLogicalTypeClick = (txLogicalId) => {
  const txLogical = tx_logicals.value.find(tlo => tlo.id == txLogicalId)
  editingTxLogical.value = Object.assign({}, txLogical)
  showEditTxLogicalTypeForm.value = true
}

const handleCopyValue = (prefix, value) => {
  copyToClipboard(value)
  quasar.notify({
    type: 'positive',
    message: `${prefix} ${value} copied to clipboard.`
  })
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
  const txLedgers = txLedger.direction.toLowerCase() == 'in' ? txLogical.ins : txLogical.outs
  const index = txLedgers.findIndex(tle => tle.id == txLedger.id)
  const updatedTxLedger = Object.assign(txLedgers[index], {price_usd: Number(txLedger.price_usd)})
  txLedgers[index] = updatedTxLedger

  // Reset form
  editingTxLedger.value = null
  showEditPriceForm.value = false
}

const updateLogicalType = async () => {
  const txLogical = editingTxLogical.value
  const url = `${BACKEND_URL}/tx_logicals/${txLogical.id}/tx_logical_type/${txLogical.tx_logical_type}`
  const result = await axios.put(url, {}, { withCredentials: true })
  quasar.notify({
    type: 'positive',
    message: 'Logical type updated.'
  })

  // Find the logical and update it's type
  const index = tx_logicals.value.findIndex(tlo => tlo.id == txLogical.id)
  const updatedTxLogical = Object.assign(tx_logicals.value[index], {tx_logical_type: txLogical.tx_logical_type})
  tx_logicals.value[index] = updatedTxLogical

  // Reset form
  editingTxLogical.value = null
  showEditTxLogicalTypeForm.value = false
}

const handleMoveClick = (txLogicalId, txLedgerId) => {
  showMoveTransactionForm.value = true
  setEditingTxLedger(txLogicalId, txLedgerId)
}

const moveTxLedger = async (txLedgerId, txLogicalId) => {
  const url = `${BACKEND_URL}/tx_ledgers/${txLedgerId}/tx_logical_id/${txLogicalId}`
  const result = await axios.put(url, {}, { withCredentials: true })
  quasar.notify({
    type: 'positive',
    message: `Transaction moved to logical group ${txLogicalId}.`
  })

  // Reload the list of TxLogicals
  await loadTxLogicals()

  // Reset form
  newTxLogicalId.value = ''
  showMoveTransactionForm.value = false
}

const hideLogical = (id) => {
  hiddenLogicalIds.value.push(id)
  tx_logicals.value = tx_logicals.value.filter(txlo => hiddenLogicalIds.value.indexOf(txlo.id) == -1)
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
        <q-th key="date"> Date </q-th>
        <q-th key="type"> Type </q-th>
        <q-th key="transactions"> Transactions </q-th>
        <q-th key="fee"> Fee </q-th>
      </q-tr>
    </template>

    <template v-slot:body="props">
      <q-tr :props="props">
        <q-td key="date_and_time" :props="props" style="width: 200px;">
          <div class="row items-center">
            <div class="col">
              {{dateAndTime(props.row)[0]}} <br/> {{dateAndTime(props.row)[1]}}
            </div>

            <div class="col">
              <q-btn class="hoverEdit" flat size="xs" label="Copy ID" @click="handleCopyValue('Logical ID', props.row.id)" color="secondary" />
            </div>
          </div>
        </q-td>

        <q-td key="type" :props="props" style="width: 200px;">
          <div class="row items-center">
            <div class="col">
              {{props.row.tx_logical_type}}
            </div>

            <div class="col">
              <q-btn class="hoverEdit" flat size="xs" label="Edit Type" @click="handleEditTxLogicalTypeClick(props.row.id)" color="secondary" />
            </div>
          </div>
        </q-td>


        <q-td key="transactions" :props="props" style="width: 600px">
            <div class="logicalOut row items-center q-pb-sm" v-for="tx_ledger in props.row.outs" :key="tx_ledger.id">
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
              <q-btn class="hoverEdit on-right" flat size="xs" label="Edit Price" @click="handleEditClick(props.row.id, tx_ledger.id)" color="secondary" />
              <q-btn class="hoverEdit on-right" flat size="xs" label="Move" @click="handleMoveClick(props.row.id, tx_ledger.id)" color="secondary" />
            </div>

            <div class="logicalIn row items-center q-pb-sm" v-for="tx_ledger in props.row.ins" :key="tx_ledger.id">
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

              <q-btn class="hoverEdit on-right q-py-none" flat size="xs" label="Edit Price" @click="handleEditClick(props.row.id, tx_ledger.id)" color="secondary" />
              <q-btn class="hoverEdit on-right q-py-none" flat size="xs" label="Move" @click="handleMoveClick(props.row.id, tx_ledger.id)" color="secondary" />
            </div>

            <div class="logicalOther row items-center q-pb-sm" v-for="tx_ledger in props.row.others" :key="tx_ledger.id">
              <img class="txIcon" :src="txIconUrl(tx_ledger)" />

              &nbsp;{{ tx_ledger.tx_ledger_type == 'approval' ? 'Approve' : '' }}
              &nbsp;{{tx_ledger.amount.toFixed(2)}}
              &nbsp;
              <div><span class="text-weight-bold">{{tx_ledger.symbol}}</span> for {{tx_ledger.to_address_name}}
                &nbsp;
                <q-tooltip anchor="bottom middle" self="center middle" :hide-delay="1000">
                  {{tx_ledger.to_address}}
                </q-tooltip>
              </div>
            </div>
        </q-td>

        <q-td key="fee" :props="props" style="xwidth: 200px;">
          <template v-if="props.row.fee">
            {{props.row.fee.amount}}
            {{props.row.fee.symbol}}
          </template>
        </q-td>

      </q-tr>
    </template>

    <template v-slot:bottom>
      <q-btn style="background: #efefef; color: black" @click="loadNextPage">
        {{ loading ? "Loading..." : "Load More"}}
      </q-btn>
    </template>

  </q-table>

  <q-dialog v-model="showEditPriceForm">
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

  <q-dialog v-model="showEditTxLogicalTypeForm">
    <q-card>
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Edit logical type</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup />
      </q-card-section>
      <q-card-section>
        <div>
            <div> {{dateAndTime(editingTxLogical)[0]}} at {{dateAndTime(editingTxLogical)[1]}} </div>
        </div>
        <q-select
          label="Type"
          v-model="editingTxLogical.tx_logical_type"
          :options="txLogicalTypes"
        />
        <q-btn label="Save Logical Type" type="submit" color="primary" @click="updateLogicalType" />
      </q-card-section>
    </q-card>
  </q-dialog>


  <q-dialog v-model="showMoveTransactionForm">
    <q-card>
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Move transaction to a different logical group</div>
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
          label="Logical ID"
          type="text"
          v-model="newTxLogicalId"
        /> <!-- TODO: Validation -->
        <q-btn label="Move" type="submit" color="primary" @click="moveTxLedger(editingTxLedger.id, newTxLogicalId)" />
      </q-card-section>
    </q-card>
  </q-dialog>

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
.q-table tbody td:hover .hoverEdit {
  display: inherit;
}

.hoverEdit {
  display: none;
}
</style>
