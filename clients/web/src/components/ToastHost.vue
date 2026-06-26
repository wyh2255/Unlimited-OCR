<script setup lang="ts">
import { useToast } from '@/composables/useToast'

const toast = useToast()
</script>

<template>
  <div class="toast-host">
    <div
      v-for="t in toast.state.items"
      :key="t.id"
      class="toast"
      :class="{
        'toast--success': t.kind === 'success',
        'toast--error': t.kind === 'error',
        'toast--warn': t.kind === 'warn',
      }"
    >
      <span>
        <template v-if="t.kind === 'success'">✓</template>
        <template v-else-if="t.kind === 'error'">✕</template>
        <template v-else-if="t.kind === 'warn'">!</template>
        <template v-else>i</template>
      </span>
      <span style="flex: 1;">{{ t.text }}</span>
    </div>
  </div>
</template>
