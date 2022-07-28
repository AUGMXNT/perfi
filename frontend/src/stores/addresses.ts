import { defineStore } from 'pinia'
import type { Address } from '@/model_types'
import axios from 'axios'
import { backendUrl } from '@/utils'

const BACKEND_URL = backendUrl()
const fetchUrl = `${BACKEND_URL}/addresses`

export const useAddressStore = defineStore({
  id: 'addresses',

  state: () => ({
    items: <Address[]>[]
  }),

  getters: {
    all: (state): Address[] => { return state.items }
  },

  actions: {
    async fetch() {
      let response = await axios.get(fetchUrl, { withCredentials: true })
      this.items = response.data
    },

    add(item: Address) {
      this.items.push(item)
    },

    updateAttribute(id: number, updatedProp: keyof Address, updatedValue: string) {
      let item = this.items.find(i => i.id == id)
      if (item) {
        item[updatedProp] = updatedValue
      }
    },

    update(item: Address) {
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
