<script setup lang="ts">
import { ref } from 'vue'
import axios from 'axios';
import LabelForm from '@/components/LabelForm.vue'
import type { Label } from '@/model_types'
import { useRouter, useRoute } from 'vue-router'
import { RouterLink } from 'vue-router';

const props = defineProps<{
  label: Label
}>()

const emit = defineEmits<{
  (e: 'updated', id: number, name: string, description: string): void
  (e: 'deleted', id: number): void
}>()

const router = useRouter()
const route = useRoute()

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
let label = ref(props.label)

let isEditing = ref(false)

let loading = ref(false)

const updateCachedLabel = (attr: keyof Label, value: string) => {
  (label.value as any)[attr] = value
}

const handleUpdated = (id: number, name:string, description: string) => {
  isEditing.value = false;
  emit('updated', id, name, description)
  updateCachedLabel('name', name)
  updateCachedLabel('description', description)
}

const handleDelete = async () => {
  if (!confirm(`Are you sure you want to delete the label '${label.value.name}'?`)) return;
  const url = `${BACKEND_URL}/labels/${label.value.id}`
  let response = await axios.delete(url, { withCredentials: true })
  emit('deleted', label.value.id)
}

</script>

<template>
  <q-card flat bordered class="q-mb-lg">
    <q-card-section>
      <div class="row">
        <div class="col q-ml-md" v-if="!isEditing">
          <p class="text-subtitle2">
            {{label.name}}
          </p>
          <p>
            {{label.description}}
          </p>

          <LabelForm v-if="isEditing" :label="label" @updated="handleUpdated"/>
        </div>
      </div>
    </q-card-section>

    <q-card-actions align="left">
      <q-btn flat v-if="isEditing" @click="isEditing = false">Cancel</q-btn>
      <q-btn flat v-if="!isEditing" @click="isEditing = true">Edit</q-btn>
      <q-btn flat v-if="!isEditing" @click="handleDelete">Delete</q-btn>
    </q-card-actions>
  </q-card>
</template>
