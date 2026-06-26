<script setup lang="ts">
import { computed } from 'vue'
import type { TaskStatus } from '@/types/api'

const props = defineProps<{ status: TaskStatus | string | null }>()

const label = computed(() => {
  switch (props.status) {
    case 'queued':    return '排队中'
    case 'running':   return '运行中'
    case 'completed': return '已完成'
    case 'failed':    return '失败'
    case null:
    case '':
    case undefined:   return '未知'
    default:           return String(props.status)
  }
})

const cls = computed(() => {
  switch (props.status) {
    case 'queued':    return 'badge badge--queued'
    case 'running':   return 'badge badge--running'
    case 'completed': return 'badge badge--completed'
    case 'failed':    return 'badge badge--failed'
    default:           return 'badge badge--muted'
  }
})
</script>

<template>
  <span :class="cls">{{ label }}</span>
</template>
