import { reactive } from 'vue'

export type ToastKind = 'info' | 'success' | 'warn' | 'error'

export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
  ttl: number
}

const state = reactive<{ items: ToastItem[] }>({ items: [] })
let _id = 0

export function useToast() {
  return {
    state,
    push(text: string, kind: ToastKind = 'info', ttl = 4500): void {
      const id = ++_id
      state.items.push({ id, kind, text, ttl })
      setTimeout(() => {
        const i = state.items.findIndex((t) => t.id === id)
        if (i >= 0) state.items.splice(i, 1)
      }, ttl)
    },
    info(text: string, ttl?: number) { this.push(text, 'info', ttl) },
    success(text: string, ttl?: number) { this.push(text, 'success', ttl) },
    warn(text: string, ttl?: number) { this.push(text, 'warn', ttl) },
    error(text: string, ttl?: number) { this.push(text, 'error', ttl ?? 7000) },
  }
}
