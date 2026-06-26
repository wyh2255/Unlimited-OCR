<script setup lang="ts">
import { computed } from 'vue'
import type { LocalTaskMeta, TaskInfo } from '@/types/api'
import StatusBadge from './StatusBadge.vue'

const props = defineProps<{
  meta: LocalTaskMeta
  info: TaskInfo | null
  selected: boolean
  loading: boolean
  deleting: boolean
  expanded: boolean
}>()

const emit = defineEmits<{
  (e: 'select'): void
  (e: 'toggle-expand'): void
  (e: 'download'): void
  (e: 'delete'): void
  (e: 'refresh'): void
}>()

const status = computed(() => props.info?.status ?? props.meta.last_seen_status ?? null)
const isTerminal = computed(() => status.value === 'completed' || status.value === 'failed')
const isActive = computed(() => status.value === 'queued' || status.value === 'running')

const progressPct = computed(() => {
  if (!props.info) return 0
  return Math.round((props.info.progress ?? 0) * 100)
})

const pageText = computed(() => {
  if (!props.info) return '— / —'
  if (props.info.total_pages > 0) {
    return `${props.info.current_page} / ${props.info.total_pages}`
  }
  if (props.info.status === 'running') return `${props.info.current_page} / ?`
  if (props.info.status === 'completed') {
    return `${props.info.total_pages} / ${props.info.total_pages}`
  }
  return '— / —'
})

const durationText = computed(() => {
  if (!props.info) return ''
  const started = props.info.started_at ? new Date(props.info.started_at) : null
  const ended = props.info.finished_at ? new Date(props.info.finished_at) : null
  if (!started) return ''
  const end = ended ?? new Date()
  const sec = Math.max(0, Math.floor((end.getTime() - started.getTime()) / 1000))
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}m ${s}s`
})

const createdText = computed(() => {
  const t = new Date(props.meta.created_local)
  return t.toLocaleTimeString()
})

function formatSize(b: number): string {
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${b} B`
}

function shortId(id: string): string {
  if (id.length <= 12) return id
  return `${id.slice(0, 6)}…${id.slice(-4)}`
}

async function copyId(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.meta.task_id)
  } catch {
    // ignore
  }
}
</script>

<template>
  <div
    class="task"
    :class="{ 'task--selected': selected, 'task--active': isActive, 'task--failed': status === 'failed' }"
    @click="emit('select')"
  >
    <div class="task__head">
      <div class="task__id">
        <span class="mono" :title="meta.task_id">{{ shortId(meta.task_id) }}</span>
        <button
          class="btn btn--ghost btn--sm copy-btn"
          @click.stop="copyId"
        >
          复制 ID
        </button>
      </div>
      <StatusBadge :status="status" />
    </div>

    <div class="task__file muted">
      📄 {{ meta.file_name }} · {{ formatSize(meta.file_size) }} · {{ meta.image_mode }}
    </div>

    <div v-if="info" class="task__progress">
      <div class="progress">
        <div class="progress__bar" :style="{ width: progressPct + '%' }" />
      </div>
      <div class="task__progress-meta">
        <span class="mono">{{ pageText }} 页</span>
        <span class="muted">{{ progressPct }}%</span>
        <span v-if="durationText" class="muted">⏱ {{ durationText }}</span>
        <span v-if="info.concurrency > 0" class="muted">⚙ 并发 {{ info.concurrency }}</span>
      </div>
    </div>
    <div v-else-if="loading" class="task__loading muted">查询中…</div>
    <div v-else class="task__loading muted">未拉取状态</div>

    <div v-if="expanded && info?.error" class="task__error">
      <strong>错误:</strong> {{ info.error }}
    </div>

    <div class="task__foot">
      <div class="task__time muted">
        创建 {{ createdText }}
      </div>
      <div class="task__actions" @click.stop>
        <button
          v-if="!isTerminal"
          class="btn btn--ghost btn--sm"
          :disabled="loading"
          @click="emit('refresh')"
        >
          刷新
        </button>
        <button
          v-if="status === 'completed'"
          class="btn btn--primary btn--sm"
          @click="emit('download')"
        >
          下载 ZIP
        </button>
        <button
          v-if="status === 'failed'"
          class="btn btn--ghost btn--sm"
          @click="emit('toggle-expand')"
        >
          {{ expanded ? '收起错误' : '查看错误' }}
        </button>
        <button
          class="btn btn--danger btn--sm"
          :disabled="deleting"
          @click="emit('delete')"
        >
          {{ deleting ? '删除中…' : '删除' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.task:hover {
  border-color: var(--color-border-strong);
  background: var(--color-card);
}
.task--selected {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-soft);
}
.task--active {
  background: var(--color-accent-soft);
}
.task--active.task--selected {
  background: var(--color-accent-soft);
}
.task--failed {
  border-color: var(--color-danger);
}

.task__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.task__id {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
}
.copy-btn {
  font-size: 10px;
  padding: 2px 8px;
  color: var(--color-text-muted);
}
.task__file {
  font-size: 12px;
}
.task__progress {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.task__progress-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  flex-wrap: wrap;
}
.task__loading {
  font-size: 11px;
}
.task__error {
  font-size: 12px;
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  word-break: break-all;
}
.task__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  gap: 8px;
}
.task__time {
  font-size: 11px;
}
.task__actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
