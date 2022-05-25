<script setup lang="ts">
import { ref, reactive, nextTick, watchEffect, computed } from "vue"
import axios from "axios";
import type { Address } from '@/model_types'

const props = defineProps<{
  record: Address
}>()

const emit = defineEmits<{
  (e: 'updated', record: Address): void
  (e: 'created', record: Address): void
  (e: 'canceled'): void
}>()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

const formLabel = computed(() => { return props.record ? 'Edit' : 'Add' })

const submitLabel = computed(() => { return props.record ? 'Update' : 'Submit' })

let form = ref(null)
let formData = ref(props.record)

const handleSubmit = async () => {
  if (props.record) {
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
      <div class="q-gutter-md row items-start">
        <q-input
          dense
          outlined
          type="text"
          v-model="formData.label"
          label="Label"
          :rules="[val => !!val || 'Label can\'t be empty']"
        />

        <q-input
          dense
          outlined
          type="text"
          v-model="formData.address"
          label="Address"
          :rules="[val => !!val || 'Address can\'t be empty']"
        />

        <q-btn :label="record?.id ? 'Update' : 'Add'" type="submit" color="primary" />
        <q-btn flat label="Cancel" color="black" @click="resetForm(); emit('canceled')" />
      </div>
    </q-form>
  </div>
</template>

<style scoped>
</style>
