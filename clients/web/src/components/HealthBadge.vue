<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { HealthResponse } from '@/types/api'
import { ApiClientError, useApi } from '@/composables/useApi'
import { useSettings } from '@/composables/useSettings'

const { settings } = useSettings()

const data = ref<HealthResponse | null>(null)
const loading = ref(false)
const errorText = ref<string | null>(null)
let timer: number | null = null

const api = computed(() => useApi(settings.value.serverUrl, settings.value.token))

async function refresh(): Promise<void> {
  loading.value = true
  try {
    data.value = await api.value.health()
    errorText.value = null
  } catch (e) {
    if (e instanceof ApiClientError) {
      errorText.value = `${e.status} · ${e.detail}`
    } else {
      errorText.value = String((e as Error).message ?? e)
    }
    data.value = null
  } finally {
    loading.value = false
  }
}

const state = computed<'ok' | 'err' | 'loading' | 'idle'>(() => {
  if (loading.value) return 'loading'
  if (errorText.value) return 'err'
  if (data.value) return 'ok'
  return 'idle'
})

const dotClass = computed(() => {
  if (state.value === 'ok') return 'dot dot--ok'
  if (state.value === 'err') return 'dot dot--err'
  if (state.value === 'loading') return 'dot dot--warn'
  return 'dot dot--idle'
})

const statusText = computed(() => {
  if (state.value === 'ok' && data.value) {
    const d = data.value
    return `GPU ${d.gpu.name} · ${formatMb(d.gpu.free_mb)} / ${formatMb(d.gpu.total_mb)} free · 推荐并发 ${d.concurrency_recommended}`
  }
  if (state.value === 'err') return errorText.value ?? '连接失败'
  if (state.value === 'loading') return '检查中…'
  return '未连接'
})

const queueText = computed(() => {
  if (!data.value) return ''
  const d = data.value
  if (d.queue_length === 0 && !d.current_task) return '队列空闲'
  if (d.current_task) return `正在处理 ${d.current_task} · 排队 ${d.queue_length}`
  return `排队 ${d.queue_length}`
})

const peerSummary = computed(() => {
  if (!data.value?.peers) return null
  const entries = Object.entries(data.value.peers)
  if (entries.length === 0) return null
  return entries
    .map(([id, peer]) => {
      if (!peer.online) return `${id} · offline`
      return `${peer.name} · ${formatMb(peer.free_mb)} free`
    })
    .join(' | ')
})

function formatMb(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

function startPolling(): void {
  stopPolling()
  timer = window.setInterval(() => {
    void refresh()
  }, 8000)
}

function stopPolling(): void {
  if (timer != null) {
    window.clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  void refresh()
  startPolling()
})

onUnmounted(stopPolling)

watch(
  () => [settings.value.serverUrl, settings.value.token],
  () => {
    void refresh()
  },
)

defineExpose({ refresh })
</script>

<template>
  <div class="health">
    <span :class="dotClass" :title="statusText" />
    <div class="health__text">
      <div class="health__line">
        <span v-if="state === 'ok'">{{ statusText }}</span>
        <span v-else-if="state === 'err'" class="muted">{{ statusText }}</span>
        <span v-else-if="state === 'loading'" class="muted">检查中…</span>
        <span v-else class="muted">未连接</span>
      </div>
      <div v-if="data" class="health__sub muted">
        {{ queueText }} ·
        <a href="#" @click.prevent="refresh">{{ loading ? '刷新中…' : '手动刷新' }}</a>
      </div>
      <div v-if="peerSummary" class="health__peers muted">
        {{ peerSummary }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.health {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.health__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.health__line {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 460px;
}
.health__sub {
  font-size: 11px;
  margin-top: 2px;
}
.health__peers {
  font-size: 11px;
  margin-top: 2px;
}
</style>
