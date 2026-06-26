<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { LocalTaskMeta, TaskInfo } from '@/types/api'
import { ApiClientError, useApi } from '@/composables/useApi'
import { useSettings } from '@/composables/useSettings'
import { useTaskStore } from '@/composables/useTaskStore'
import { useToast } from '@/composables/useToast'
import TaskCard from './TaskCard.vue'

const { settings } = useSettings()
const taskStore = useTaskStore()
const toast = useToast()

const selectedId = ref<string | null>(null)
const expanded = ref<Record<string, boolean>>({})
const deleting = ref<Record<string, boolean>>({})

interface Entry {
  meta: LocalTaskMeta
  info: TaskInfo | null
  loading: boolean
}

const entries = reactive<Record<string, Entry>>({})
let pollTimer: number | null = null

const api = () => useApi(settings.value.serverUrl, settings.value.token)

function rebuildEntries(): void {
  for (const m of taskStore.store.items) {
    if (!entries[m.task_id]) {
      entries[m.task_id] = { meta: m, info: null, loading: false }
    } else {
      entries[m.task_id].meta = m
    }
  }
  for (const id of Object.keys(entries)) {
    if (!taskStore.get(id)) delete entries[id]
  }
}

async function pollOne(meta: LocalTaskMeta, entry: Entry): Promise<void> {
  entry.loading = true
  try {
    const info = await api().getTask(meta.task_id)
    entry.info = info
    taskStore.setStatus(meta.task_id, info.status)
  } catch (e) {
    if (e instanceof ApiClientError && e.status === 404) {
      // server forgot the task; mark as failed locally so the UI is honest
      entry.info = {
        task_id: meta.task_id,
        status: 'failed',
        progress: 0,
        current_page: 0,
        total_pages: 0,
        image_mode: meta.image_mode,
        concurrency: 0,
        error: '服务端已无此任务记录 (404),可能 server 重启后丢失',
        created_at: meta.created_local,
        started_at: null,
        finished_at: null,
      }
      taskStore.setStatus(meta.task_id, 'failed')
    } else {
      // transient error, just leave previous info
    }
  } finally {
    entry.loading = false
  }
}

async function pollAll(): Promise<void> {
  rebuildEntries()
  const tasks = Object.values(entries)
  await Promise.all(tasks.map((e) => pollOne(e.meta, e)))
}

function startPolling(): void {
  stopPolling()
  void pollAll()
  pollTimer = window.setInterval(() => {
    if (hasActive()) void pollAll()
  }, 3000)
}

function stopPolling(): void {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function hasActive(): boolean {
  return Object.values(entries).some(
    (e) => e.info?.status === 'queued' || e.info?.status === 'running',
  )
}

function select(id: string): void {
  selectedId.value = id
}

async function refresh(meta: LocalTaskMeta): Promise<void> {
  const e = entries[meta.task_id]
  if (e) await pollOne(meta, e)
}

async function download(meta: LocalTaskMeta): Promise<void> {
  try {
    await api().downloadResult(meta.task_id, `${meta.task_id}.zip`)
    toast.success(`已下载 ${meta.task_id}.zip`)
  } catch (e) {
    if (e instanceof ApiClientError) {
      toast.error(`下载失败 · ${e.status} · ${e.detail}`)
    } else {
      toast.error(`下载失败 · ${String((e as Error).message ?? e)}`)
    }
  }
}

async function remove(meta: LocalTaskMeta): Promise<void> {
  if (!confirm(`确认删除任务 ${meta.task_id}?\n对应文件与 ZIP 都会从服务器移除。`)) return
  deleting.value[meta.task_id] = true
  try {
    await api().deleteTask(meta.task_id)
    taskStore.remove(meta.task_id)
    delete entries[meta.task_id]
    if (selectedId.value === meta.task_id) selectedId.value = null
    toast.success(`已删除 ${meta.task_id}`)
  } catch (e) {
    if (e instanceof ApiClientError) {
      toast.error(`删除失败 · ${e.status} · ${e.detail}`)
    } else {
      toast.error(`删除失败 · ${String((e as Error).message ?? e)}`)
    }
  } finally {
    deleting.value[meta.task_id] = false
  }
}

function clearAll(): void {
  if (!confirm('仅清空本机浏览器缓存的任务列表 (不会删服务器上的任务)。确认?')) return
  taskStore.clear()
  for (const id of Object.keys(entries)) delete entries[id]
  selectedId.value = null
}

defineExpose({
  select,
  getSelectedId: () => selectedId.value,
  getSelected: (): TaskInfo | null => {
    const id = selectedId.value
    if (!id) return null
    return entries[id]?.info ?? null
  },
})

onMounted(() => {
  rebuildEntries()
  if (Object.keys(entries).length > 0) selectedId.value = Object.keys(entries)[0] ?? null
  startPolling()
})

onBeforeUnmount(stopPolling)

watch(
  () => taskStore.store.items.length,
  () => {
    rebuildEntries()
    if (!selectedId.value && Object.keys(entries).length > 0) {
      selectedId.value = Object.keys(entries)[0] ?? null
    }
  },
)

watch(
  () => [settings.value.serverUrl, settings.value.token],
  () => {
    startPolling()
  },
)
</script>

<template>
  <div class="list">
    <div class="list__head">
      <h3 class="list__title">任务列表</h3>
      <div class="list__head-actions">
        <span class="muted" style="font-size: 11px;">
          {{ Object.keys(entries).length }} 条 · 自动轮询 3s
        </span>
        <button v-if="Object.keys(entries).length > 0" class="btn btn--ghost btn--sm" @click="clearAll">
          清空列表
        </button>
      </div>
    </div>

    <div v-if="Object.keys(entries).length === 0" class="list__empty muted">
      还没有任务。在 <strong>新建任务</strong> 里上传一个 PDF 试试。
    </div>

    <div v-else class="list__items">
      <TaskCard
        v-for="e in Object.values(entries)"
        :key="e.meta.task_id"
        :meta="e.meta"
        :info="e.info"
        :selected="selectedId === e.meta.task_id"
        :loading="e.loading"
        :deleting="!!deleting[e.meta.task_id]"
        :expanded="!!expanded[e.meta.task_id]"
        @select="select(e.meta.task_id)"
        @toggle-expand="expanded[e.meta.task_id] = !expanded[e.meta.task_id]"
        @download="download(e.meta)"
        @delete="remove(e.meta)"
        @refresh="refresh(e.meta)"
      />
    </div>
  </div>
</template>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 4px;
}
.list__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.list__head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.list__empty {
  text-align: center;
  padding: 24px 12px;
  font-size: 13px;
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
}
.list__items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
  padding-right: 4px;
}
</style>
