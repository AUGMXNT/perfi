<script setup lang="ts">
import { ref, reactive, nextTick, watchEffect, computed } from "vue"
import axios from "axios";
import type { Entity } from '@/model_types'
import { backendUrl } from "@/utils";

const props = defineProps<{
  record: Entity
}>()

const emit = defineEmits<{
  (e: 'updated', record: Entity): void
  (e: 'created', record: Entity): void
  (e: 'canceled'): void
}>()

const BACKEND_URL = backendUrl()

const formLabel = computed(() => { return props.record ? 'Edit' : 'Add' })

const submitLabel = computed(() => { return props.record ? 'Update' : 'Submit' })

let form = ref(null)
let formData = ref(props.record)

const handleSubmit = async () => {
  if (props.record.id) {
    const updateUrl = `${BACKEND_URL}/entities/${props.record.id}`
    const result = await axios.put(updateUrl, { ...formData.value }, { withCredentials: true })
    emit('updated', Object.assign({}, formData.value))
  }
  else {
    const createUrl = `${BACKEND_URL}/entities`
    const result = await axios.post(createUrl, { ...formData.value }, { withCredentials: true })
    emit('created', result.data)
    resetForm({nextTick: true})
    // formData.value = {} as Entity

    // // Need to wait until next tick to reset the form validation due to the submit
    // setTimeout(()=>(form.value as any).resetValidation(), 0)
  }
}

const resetForm = ({nextTick=false}={}) => {
  formData.value = {} as Entity
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
          v-model="formData.name"
          label="Label"
          :rules="[val => !!val || 'Name can\'t be empty']"
        />

        <q-input
          outlined
          type="text"
          v-model="formData.note"
          label="Notes"
        />

        <q-btn :label="record?.id ? 'Update' : 'Add'" type="submit" color="primary" />
        <q-btn flat label="Cancel" color="black" @click="resetForm(); emit('canceled')" />
      </div>
    </q-form>
  </div>
</template>

<style scoped>
</style>
