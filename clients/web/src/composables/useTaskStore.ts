import { reactive, watch } from 'vue'
import type { LocalTaskMeta, TaskStatus } from '@/types/api'

const STORAGE_KEY = 'unlimited-ocr.tasks.v1'

interface Store {
  items: LocalTaskMeta[]
}

function load(): Store {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { items: [] }
    const items = JSON.parse(raw) as LocalTaskMeta[]
    return { items: Array.isArray(items) ? items : [] }
  } catch {
    return { items: [] }
  }
}

const store = reactive<Store>(load())

watch(
  store,
  (s) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s.items))
    } catch {
      // ignore
    }
  },
  { deep: true },
)

export function useTaskStore() {
  return {
    store,
    add(meta: LocalTaskMeta): void {
      const idx = store.items.findIndex((m) => m.task_id === meta.task_id)
      if (idx >= 0) {
        store.items[idx] = { ...store.items[idx], ...meta }
      } else {
        store.items.unshift(meta)
      }
    },
    update(taskId: string, patch: Partial<LocalTaskMeta>): void {
      const idx = store.items.findIndex((m) => m.task_id === taskId)
      if (idx >= 0) {
        store.items[idx] = { ...store.items[idx], ...patch }
      }
    },
    setStatus(taskId: string, status: TaskStatus): void {
      this.update(taskId, {
        last_seen_status: status,
        last_polled: new Date().toISOString(),
      })
    },
    remove(taskId: string): void {
      const idx = store.items.findIndex((m) => m.task_id === taskId)
      if (idx >= 0) store.items.splice(idx, 1)
    },
    clear(): void {
      store.items.splice(0, store.items.length)
    },
    get(taskId: string): LocalTaskMeta | undefined {
      return store.items.find((m) => m.task_id === taskId)
    },
  }
}
