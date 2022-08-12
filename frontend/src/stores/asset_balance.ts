import { defineStore } from 'pinia'
import type { AssetBalance } from '@/model_types'
import axios from 'axios'


export const useAssetBalanceStore = (addressId: string) => {
  const fetchUrl = `${import.meta.env.VITE_BACKEND_URL}/addresses/${addressId}/manual_balances`
  return defineStore({
    id: `address_${addressId}_asset_balance`,

    state: () => ({
      items: <AssetBalance[]>[]
    }),

    getters: {
      all: (state): AssetBalance[] => { return state.items }
    },

    actions: {
      async fetch() {
        let response = await axios.get(fetchUrl, { withCredentials: true })
        this.items = response.data
      },

      add(item: AssetBalance) {
        this.items.push(item)
      },

      updateAttribute(id: number, updatedProp: keyof AssetBalance, updatedValue: string) {
        let item = this.items.find(i => i.id == id)
        if (item) {
          item[updatedProp] = updatedValue
        }
      },

      update(item: AssetBalance) {
        let index = this.items.findIndex(i => i.id === item.id)
        if (index != -1) {
          this.items[index] = item
        }
      },

      delete(id: number) {
        this.items = this.items.filter(i => i.id !== id)
      }
    }
  })
}
