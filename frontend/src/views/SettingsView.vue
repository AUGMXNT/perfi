<script setup lang="ts">
import LabelsList from '@/components/LabelsList.vue'
import EntitiesList from '@/components/EntitiesList.vue'

</script>

<template>
  <q-page padding class="row items-left">
    <div class="row">
      <div class="col-12">

        <div class="row">
          <div class="col">
            <EntitiesList />
          </div>
        </div>

      </div>
    </div>
  </q-page>
</template>
