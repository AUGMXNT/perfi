type Flag = {
  name: string;
  description: string;
  source: string;
  created_at: number;
}

type TxLedger = {
  id?: string
  chain: string
  address: string
  hash: string
  from_address: string
  to_address: string
  from_address_name?: string
  to_address_name?: string
  asset_tx_id: string
  isfee: number
  amount: number
  timestamp: number
  direction: string
  tx_ledger_type?: string
  asset_price_id?: string
  symbol?: string
  price_usd?: number
}

type TxLogical = {
  id: string
  count: number
  timestamp: number
  tx_logical_type: number
  flags: Flag[]
  description?: string
  note?: string
  address: string
  ins: TxLedger[]
  outs: TxLedger[]
  fee?: TxLedger
  others: TxLedger[]
}

type Entity = {
  id: number
  name: string
  note: string
  addresses?: Address[]
}

type Address = {
  id: number
  label: string
  chain: string
  address: string
  type: string
  source: string
  ord: number
  entity_id: number
}

type AssetBalance = {
    id: number
    source: string
    address: string
    chain: string
    symbol: string
    exposure_symbol: string
    amount: number
    protocol?: string
    label?: string
    price?: number
    usd_value?: number
    updated?: number
    type?: string
    locked?: number
    proxy?: string
    extra?: string
    stable?: number
}



export type { Flag, TxLogical, TxLedger, Entity, Address, AssetBalance }
