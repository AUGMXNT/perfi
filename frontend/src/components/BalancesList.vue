<script setup lang="ts">
import axios from "axios";
import { ref, reactive, nextTick, watchEffect } from "vue"
import { displayAddress, displayTimestamp, txIconUrl } from '@/utils.ts'
import type { Entity, AssetBalance } from "@/model_types";
import { format } from 'quasar'

const props = defineProps<{
  entity: Entity
}>()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

let balances = ref<AssetBalance[]>([])
let exposure = ref({assets: [], loans: [], total_usd_value: null})
let loading = ref(false)
let filter = ref()

const loadBalances = async () => {
  loading.value = true
  let response = await axios.get(`${BACKEND_URL}/entities/${props.entity.id}/balances`, { withCredentials: true })
  balances.value = response.data
  loading.value = false
}

const loadExposue = async () => {
  let response = await axios.get(`${BACKEND_URL}/entities/${props.entity.id}/exposure`, { withCredentials: true })
  exposure.value = response.data
}

watchEffect(async () => {
  loadBalances()
  loadExposue()
})

const usdFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat('en-US', {
  style: 'decimal',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

let column_names = [
    // 'address',
    // 'chain',
    'source',
    'symbol',
    'exposure_symbol',
    'protocol',
    'label',
    'price',
    'amount',
    'usd_value',
    // 'updated',
    // 'type',
    'locked',
    // 'proxy',
    // 'extra',
    'stable',
]
let column_value_overrides = {
  'stable': (r => r.stable == 1 ? 'stable' : '' ),
}
let column_format_overrides = {
  'amount': numberFormatter.format,
  'price': usdFormatter.format,
  'usd_value': usdFormatter.format,
}
let columns = column_names
  .map(name => { return {
    name: name,
    label: name,
    field: column_value_overrides[name] ? column_value_overrides[name] : name,
    format: column_format_overrides[name] ? column_format_overrides[name] : (v, r) => v,
    align: 'left',
    sortable: true,
  }})

const rows = balances

const refreshBalances = async () => {
  loading.value = true
  let response = await axios.post(`${BACKEND_URL}/entities/${props.entity.id}/balances/refresh`, {}, { withCredentials: true })
  balances.value = response.data
  loading.value = false
}

const exposureAsChartSeries = (key: string) => {
  // key can be 'assets' or 'loans'
  const items = exposure.value[key]

  const getColor = (symbol: string) : string | null => {
    // TODO: add color to assets config file?
    const colors = {
      ETH: '#3c3c3d',
      BTC: '#FF9900',
      DAI: '#6acebb',
      USDC: '#2775ca',
      USDT: '#50AF95',
      MATIC: '#8247e5',
      AVAX: '#e84142',
    }

    return colors[symbol] ? colors[symbol] : null
  }

  return !items ? [] : items.map(o => { return { x: o.asset, y: o.usd_value, fillColor: getColor(o.asset) }})
}

const chartOptions = (title) => {
    return {
    chart: {
      animations: { enabled: false },
      toolbar: {
        tools: {
          download: false
        },
      },
    },
    title: {
      text: title
    },
  }
}

</script>

<template>
  <div class="row">
    <div class="col">
      <div class="row text-h5">Balances for {{props.entity.name}}</div>
      <div class="row" v-if="exposure.total_usd_value !== null">
        <table class="exposure">
          <tr>
            <td>Total Value</td>
            <td class="value">
              {{usdFormatter.format(exposure.total_usd_value)}}
            </td>
          </tr>
          <tr>
            <td>Total Stables</td>
            <td class="value">
              {{usdFormatter.format(exposure.total_stables)}}
            </td>
          </tr>
          <tr>
            <td>Total Loans</td>
            <td class="value">
              {{usdFormatter.format(exposure.total_loans)}}
            </td>
          </tr>
        </table>
      </div>
    </div>
  </div>
  <div class="row" v-if="exposure.total_usd_value !== null">
    <apexchart class="on-left" v-if="exposure.assets.length > 0" width="500" type="treemap" :options="chartOptions('Asset Exposure')" :series="[{data: exposureAsChartSeries('assets')}]"></apexchart>

    <apexchart v-if="exposure.loans.length > 0" width="500" type="treemap" :options="chartOptions('Loan Exposure')" :series="[{data: exposureAsChartSeries('loans')}]"></apexchart>
  </div>

  <q-table
      :rows="rows"
      :columns="columns"
      row-key="id"
      :filter="filter"
      :rows-per-page-options="[0]"
      hide-pagination
      :loading="loading"
      v-if="exposure.total_usd_value !== null"
  >
    <template v-slot:top-left>
    </template>

    <template v-slot:top-right>
      <q-input dense debounce="300" v-model="filter" placeholder="Search">
        <template v-slot:append>
          <q-icon name="search" />
        </template>
      </q-input>
      <q-separator class="on-right" vertical />
      <q-btn class="on-right" outline label="Refresh" icon="refresh" color="secondary" @click="refreshBalances" />
    </template>

  </q-table>

  <div v-if="exposure.total_usd_value === null">
    Loading...
  </div>
</template>

<style scoped>
table.exposure td.value {
  text-align: right
}
</style>
