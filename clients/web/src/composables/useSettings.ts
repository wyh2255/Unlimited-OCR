import { ref, watch, type Ref } from 'vue'

const STORAGE_KEY = 'unlimited-ocr.settings.v1'

export interface AppSettings {
  serverUrl: string
  fallbackUrl: string   // NEW
  token: string
  autoWatch: boolean
}

const DEFAULT_SETTINGS: AppSettings = {
  serverUrl: 'http://127.0.0.1:10001',
  fallbackUrl: '',       // empty means fallback disabled
  token: '',
  autoWatch: true,
}

function loadFromStorage(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    const parsed = JSON.parse(raw) as Partial<AppSettings>
    return { ...DEFAULT_SETTINGS, ...parsed }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

const state = ref<AppSettings>(loadFromStorage())

watch(
  state,
  (s) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    } catch {
      // ignore quota errors
    }
  },
  { deep: true },
)

export function useSettings(): { settings: Ref<AppSettings> } {
  return { settings: state }
}

export function resetSettings(): void {
  state.value = { ...DEFAULT_SETTINGS }
}

export function hasFallback(): boolean {
  return !!state.value.fallbackUrl && state.value.fallbackUrl !== state.value.serverUrl
}
