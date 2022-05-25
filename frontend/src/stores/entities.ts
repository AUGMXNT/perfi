import { defineStore } from 'pinia'
import type { Entity } from '@/model_types'
import axios from 'axios'

const fetchUrl = `${import.meta.env.VITE_BACKEND_URL}/entities`

export const useEntitiesStore = defineStore({
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

    add(item: Entity) {
      this.items.push(item)
    },

    update(id: number, updatedProp: keyof Label, updatedValue: string) {
      let l = this.items.find(i => i.id == id)
      if (i) {
        i[updatedProp] = updatedValue
      }
    },

    delete(id: number) {
      this.items = this.items.filter(i => i.id !== id)
    }
  }
})
