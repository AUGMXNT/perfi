<script setup lang="ts">
import { ref, reactive, nextTick, watchEffect, computed } from "vue"
import axios from "axios";
import type { AssetBalance } from '@/model_types'

const props = defineProps<{
  context: any,
  record: AssetBalance
}>()

const emit = defineEmits<{
  (e: 'updated', record: AssetBalance): void
  (e: 'created', record: AssetBalance): void
  (e: 'canceled'): void
}>()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

const formLabel = computed(() => { return props.record ? 'Edit' : 'Add' })

const submitLabel = computed(() => { return props.record ? 'Update' : 'Submit' })

let form = ref(null)
let formData = ref(props.record)

const handleSubmit = async () => {
  if (props.record.id) {
    const updateUrl = `${BACKEND_URL}/addresses/${props.context.address.id}/manual_balances/${props.record.id}`
    const result = await axios.put(updateUrl, { ...formData.value }, { withCredentials: true })
    emit('updated', formData.value)
  }
  else {
    const createUrl = `${BACKEND_URL}/addresses/${props.context.address.id}/manual_balances`
    const result = await axios.post(createUrl, { ...formData.value }, { withCredentials: true })
    emit('created', result.data)
    resetForm({nextTick: true})
    // formData.value = {} as Address

    // // Need to wait until next tick to reset the form validation due to the submit
    // setTimeout(()=>(form.value as any).resetValidation(), 0)
  }
}

const resetForm = ({nextTick=false}={}) => {
  formData.value = {} as AssetBalance
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
          v-model="formData.symbol"
          label="Symbol"
          :rules="[val => !!val || 'Symbol can\'t be empty']"
        />

        <q-input
          outlined
          type="text"
          v-model="formData.exposure_symbol"
          label="Exposure Symbol"
          :rules="[val => !!val || 'Exposure Symbol can\'t be empty']"
        />

        <q-input
          outlined
          type="text"
          v-model="formData.price"
          label="Price"
        />

        <q-input
          outlined
          type="text"
          v-model="formData.amount"
          label="Amount"
          :rules="[val => !!val || 'Amount can\'t be empty']"
        />

        <q-btn :label="record?.id ? 'Update' : 'Add'" type="submit" color="primary" />
        <q-btn flat label="Cancel" color="black" @click="resetForm(); emit('canceled')" />
      </div>
    </q-form>
  </div>
</template>

<style scoped>
</style>
