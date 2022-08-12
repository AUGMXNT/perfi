import { defineStore } from 'pinia'
import type { Entity, Address } from '@/model_types'

export const useNavigationContextStore = defineStore({
  id: 'navigation_context',

  state: () => ({
    _entity: null,
    _address: null,
  }),

  getters: {
    entity: (state): Entity => { return state._entity },
    address: (state): Address => { return state._address }
  },

  actions: {
    setEntity(entity: Entity) {
      this._entity = entity
    },

    setAddress(address: Address) {
      this._address = address
    },

    clear() {
      this._entity = null
      this._address = null
    }
  }
})
