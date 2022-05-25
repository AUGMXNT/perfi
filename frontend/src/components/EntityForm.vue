<script setup lang="ts">
import { ref, reactive, nextTick, watchEffect, computed } from "vue"
import axios from "axios";
import type { Label } from '@/model_types'

const props = defineProps<{
  label?: Label
}>()

const emit = defineEmits<{
  (e: 'updated', id: number, name: string, description: string): void
  (e: 'created', label: Label): void
  (e: 'canceled'): void
}>()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

const formLabel = computed(() => { return props.label ? 'Edit Label' : 'Add Label' })

const submitLabel = computed(() => { return props.label ? 'Update Label' : 'Submit Label' })

let form = ref(null)
let formData = ref<{name: string, description: string}>({
  name: props.label?.name || '',
  description: props.label?.description || ''
})

const handleSubmit = async () => {
  if (props.label) {
    const updateUrl = `${BACKEND_URL}/labels/${props.label.id}`
    const result = await axios.put(updateUrl, { name: formData.value.name, description: formData.value.description }, { withCredentials: true })
    emit('updated', props.label.id, formData.value.name, formData.value.description)
  }
  else {
    const createUrl = `${BACKEND_URL}/labels`
    const result = await axios.post(createUrl, { name: formData.value.name, description: formData.value.description }, { withCredentials: true })
    emit('created', result.data)
    formData.value = { name: '', description: '' }

    // Need to wait until next tick to reset the form validation
    setTimeout(()=>(form.value as any).resetValidation(), 0)
  }
}
</script>

<template>

  <q-form ref="form" @submit="handleSubmit">
    <div class="q-gutter-md row items-start">
      <q-input
        dense
        outlined
        type="text"
        v-model="formData.name"
        label="Name"
        :rules="[val => !!val || 'Name can\'t be empty']"
      />

      <q-input
        dense
        outlined
        type="text"
        v-model="formData.description"
        label="Notes"
        :rules="[val => !!val || 'Description can\'t be empty']"
      />

      <q-btn :label="label?.id ? 'Update' : 'Add'" type="submit" color="primary" />
      <q-btn flat label="Cancel" color="black" @click="formData={name: '', description: ''}; emit('canceled')" />
    </div>
  </q-form>
</template>

<style scoped>
</style>
