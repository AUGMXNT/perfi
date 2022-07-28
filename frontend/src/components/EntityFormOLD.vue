<script setup lang="ts">
import { ref, reactive, nextTick, watchEffect, computed } from "vue"
import axios from "axios";
import type { Entity } from '@/model_types'
import { backendUrl } from "@/utils";

const props = defineProps<{
  entity?: Entity
}>()

const emit = defineEmits<{
  (e: 'updated', id: number, name: string, note: string): void
  (e: 'created', entity: Entity): void
  (e: 'canceled'): void
}>()

const BACKEND_URL = backendUrl()

const formLabel = computed(() => { return props.entity ? 'Edit Entity' : 'Add Entity' })

const submitLabel = computed(() => { return props.entity ? 'Update Entity' : 'Submit Entity' })

let form = ref(null)
let formData = ref<{name: string, note: string}>({
  name: props.entity?.name || '',
  note: props.entity?.note || ''
})

const handleSubmit = async () => {
  if (props.entity) {
    const updateUrl = `${BACKEND_URL}/entities/${props.entity.id}`
    const result = await axios.put(updateUrl, { name: formData.value.name, note: formData.value.note }, { withCredentials: true })
    emit('updated', props.entity.id, formData.value.name, formData.value.note)
  }
  else {
    const createUrl = `${BACKEND_URL}/entities`
    const result = await axios.post(createUrl, { name: formData.value.name, note: formData.value.note }, { withCredentials: true })
    emit('created', result.data)
    formData.value = { name: '', note: '' }

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
        v-model="formData.note"
        label="Notes"
      />

      <q-btn :label="entity?.id ? 'Update' : 'Add'" type="submit" color="primary" />
      <q-btn flat label="Cancel" color="black" @click="formData={name: '', note: ''}; emit('canceled')" />
    </div>
  </q-form>
</template>

<style scoped>
</style>
