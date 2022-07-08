import { defineStore } from 'pinia'
import type { Entity } from '@/model_types'
import axios from 'axios'
import { backendUrl } from '@/utils'

const BACKEND_URL = backendUrl()
const fetchUrl = `${BACKEND_URL}/entities`

export const useEntityStore = defineStore({
  id: 'entities',

  state: () => ({
    items: <Entity[]>[]
  }),

  getters: {
    all: (state): Entity[] => { return state.items }
  },

  actions: {
    async fetch() {
      let response = await axios.get(fetchUrl, { withCredentials: true })
      this.items = response.data
    },

    getById(id: any) {
      let index = this.items.findIndex(i => i.id.toString() === id.toString())
      if (index != -1) {
        return this.items[index]
      }
    },

    add(item: Entity) {
      this.items.push(item)
    },

    updateAttribute(id: number, updatedProp: keyof Entity, updatedValue: string) {
      let item = this.items.find(i => i.id == id)
      if (item) {
        item[updatedProp] = updatedValue
      }
    },

    update(item: Entity) {
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
