<script setup lang="ts">
import { ref, reactive, nextTick, watchEffect, computed } from "vue"
import axios from "axios";
import type { Address } from '@/model_types'
import { backendUrl } from '@/utils'

const props = defineProps<{
  context?: any,
  record: Address
}>()

const emit = defineEmits<{
  (e: 'updated', record: Address): void
  (e: 'created', record: Address): void
  (e: 'canceled'): void
}>()

const BACKEND_URL = backendUrl()

const formLabel = computed(() => { return props.record ? 'Edit' : 'Add' })

const submitLabel = computed(() => { return props.record ? 'Update' : 'Submit' })

let form = ref(null)
const formDefaults = {
  type: 'account',
  source: 'manual',
  ord: 99,
  entity_id: props.context?.entity.id,
}
let formData = ref({...formDefaults, ...props.record})

const chainOptions = [
  'ethereum',
].sort()


const handleSubmit = async () => {
  if (props.record.id) {
    const updateUrl = `${BACKEND_URL}/addresses/${props.record.id}`
    const result = await axios.put(updateUrl, { ...formData.value }, { withCredentials: true })
    emit('updated', formData.value)
  }
  else {
    const createUrl = `${BACKEND_URL}/addresses`
    const result = await axios.post(createUrl, { ...formData.value }, { withCredentials: true })
    emit('created', result.data)
    resetForm({nextTick: true})
    // formData.value = {} as Address

    // // Need to wait until next tick to reset the form validation due to the submit
    // setTimeout(()=>(form.value as any).resetValidation(), 0)
  }
}

const resetForm = ({nextTick=false}={}) => {
  formData.value = {} as Address
  if (nextTick) {
    setTimeout(()=>(form.value as any).resetValidation(), 0)
  }
  else {
    (form.value as any).resetValidation()
  }
}
</script>

<template>
  <div padding>
    <q-form ref="form" @submit="handleSubmit">
      <div>
        <q-input
          outlined
          type="text"
          v-model="formData.label"
          label="Label"
          :rules="[val => !!val || 'Label can\'t be empty']"
        />

        <q-select
          outlined
          :options="chainOptions"
          v-model="formData.chain"
          label="Chain"
          :rules="[val => !!val || 'Chain can\'t be empty']"
        />

        <q-input
          outlined
          type="text"
          v-model="formData.address"
          label="Address"
          :rules="[val => !!val || 'Address can\'t be empty']"
        />

        <!-- <q-input
          outlined
          type="text"
          v-model="formData.type"
          label="Type"
          :rules="[val => !!val || 'Type can\'t be empty']"
        /> -->

        <!-- <q-input
          outlined
          type="text"
          v-model="formData.source"
          label="Source"
          :rules="[val => !!val || 'Source can\'t be empty']"
        /> -->

        <q-input
          outlined
          type="text"
          v-model="formData.ord"
          label="Order"
          :rules="[val => !!val || 'Order can\'t be empty']"
        />

        <!-- <q-input
          outlined
          type="text"
          v-model="formData.entity_id"
          label="Entity ID"
          :rules="[val => !!val || 'entity_id can\'t be empty']"
        /> -->

        <q-btn :label="record?.id ? 'Update' : 'Add'" type="submit" color="primary" />
        <q-btn flat label="Cancel" color="black" @click="resetForm(); emit('canceled')" />
      </div>
    </q-form>
  </div>
</template>

<style scoped>
</style>
