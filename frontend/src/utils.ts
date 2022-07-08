import { date } from 'quasar'
import type { Flag, TxLogical, TxLedger } from '@/model_types.ts'

const backendUrl = () => {
  const apiPort = window.localStorage.getItem('apiPort') || '5001'
  return `http://127.0.0.1:${apiPort}`
}

const displayTimestamp = (timestamp: number) => date.formatDate(timestamp * 1000, 'YYYY-MM-DD HH:mm:ss')

const displayAddress = (tx: TxLedger, prop: string) => {
  if (prop == 'to') {
    return tx.to_address_name || tx.to_address.substring(0, 5) + '...'
  }

  if (prop == 'from') {
    return tx.from_address_name || tx.from_address.substring(0, 5) + '...'
  }

  throw new Error(`Don't know how to display address ${prop}. Only 'from' and 'to' are supported.`)
}

const txIconUrl = (tx: TxLedger) => {
    // return `/src/assets/cryptocurrency-icons-master/svg/color/${symbol.toLowerCase()}.svg`
    // return `https://assets.coingecko.com/coins/images/279/small/${txLedger.asset_price_id?.toLowerCase()}.png`

    // const result = await axios.get(`https://api.coingecko.com/api/v3/coins/${tx.chain}/contract/0x${tx.asset_tx_id}`)
    // return result.data.image.small

    return `/coin_logos/${tx.chain}_${tx.asset_tx_id}.png`
  }

export {
    displayAddress, displayTimestamp, txIconUrl, backendUrl
}
