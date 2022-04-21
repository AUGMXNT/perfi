<script setup lang="ts">
import axios from 'axios'
import { displayAddress, displayTimestamp } from '@/utils.ts'
import type { Flag, TxLogical, TxLedger } from '@/model_types.ts'

const props = defineProps<{
  tx_logical: TxLogical,
}>()

const iconUrl = (tx: TxLedger) => {
  // return `/src/assets/cryptocurrency-icons-master/svg/color/${symbol.toLowerCase()}.svg`
  // return `https://assets.coingecko.com/coins/images/279/small/${txLedger.asset_price_id?.toLowerCase()}.png`

  // const result = await axios.get(`https://api.coingecko.com/api/v3/coins/${tx.chain}/contract/0x${tx.asset_tx_id}`)
  // return result.data.image.small

  return `/coin_logos/${tx.chain}_${tx.asset_tx_id}.png`
}

const [tx_date, tx_time] = displayTimestamp(props.tx_logical.timestamp).split(' ')

</script>

<template>
  <q-item>
    <!-- Timestamp -->
    <q-item-section class="col-1">{{tx_date}} <br/> {{tx_time}}</q-item-section>

    <!-- Type -->
    <q-item-section class="col-1">
      {{tx_logical.tx_logical_type}}
    </q-item-section>

    <!-- Outs and Ins -->
    <q-item-section no-wrap class="col-4">
      <q-list>
        <q-item v-for="tx_ledger in tx_logical.outs" :key="tx_ledger.id">
          <div class="logicalOut">
            <img :src="iconUrl(tx_ledger)" />
            - {{tx_ledger.amount}} <span class="text-weight-bold">{{tx_ledger.symbol}}</span> to {{displayAddress(tx_ledger, 'to')}}

            <q-tooltip anchor="bottom middle" self="center middle">
              @ {{tx_ledger.price_usd}}
            </q-tooltip>
          </div>
        </q-item>
        <q-item v-for="tx_ledger in tx_logical.ins" :key="tx_ledger.id">
          <div class="logicalIn">
            <img :src="iconUrl(tx_ledger)" />
            + {{tx_ledger.amount}} <span class="text-weight-bold">{{tx_ledger.symbol}}</span> from {{displayAddress(tx_ledger, 'from')}}

            <q-tooltip anchor="bottom middle" self="center middle">
              @ {{tx_ledger.price_usd}}
            </q-tooltip>
          </div>
        </q-item>
      </q-list>
    </q-item-section>

    <!-- Fee -->
    <q-item-section class="col-2">
      {{tx_logical.fee}}
      <template v-if="tx_logical.fee">
        <li>Fee: {{tx_logical.fee.amount}} {{tx_logical.fee.symbol}}</li>
      </template>
    </q-item-section>

    <!-- Flags -->
    <div class="col">
      <q-chip
        v-for="flag in tx_logical.flags"
        :key="flag.id"
        outline
        color="secondary"
        text-color="black"
        :label="flag.name"
        size="sm"
      />
    </div>
  </q-item>
</template>

<style scoped lang="sass">
.logicalOut
  color: red
.logicalIn
  color: black
</style>
