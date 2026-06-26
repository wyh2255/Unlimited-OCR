// Type definitions mirroring API_CONTRACT.md (Unlimited-OCR v1.0)

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed'

export type ImageMode = 'gundam' | 'base'

export interface GpuInfo {
  name: string
  total_mb: number
  free_mb: number
  used_mb: number
}

export interface HealthResponse {
  status: 'ok'
  gpu: GpuInfo
  concurrency_recommended: number
  queue_length: number
  current_task: string | null
}

export interface UploadResponse {
  task_id: string
  status: TaskStatus
  image_mode: ImageMode
  concurrency_hint: number | null
}

export interface TaskInfo {
  task_id: string
  status: TaskStatus
  progress: number
  current_page: number
  total_pages: number
  image_mode: ImageMode
  concurrency: number
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ApiError {
  detail: string
}

export interface UploadOptions {
  file: File
  imageMode: ImageMode
  concurrencyHint?: number | null
  onUploadProgress?: (percent: number) => void
}

// Local-only metadata, persisted in localStorage. Mirrors a subset of TaskInfo
// so the UI can render cards for tasks whose state has been forgotten by the
// server (e.g. after a server restart, those become 404 on next poll).
export interface LocalTaskMeta {
  task_id: string
  file_name: string
  file_size: number
  image_mode: ImageMode
  concurrency_hint: number | null
  created_local: string
  last_seen_status: TaskStatus | null
  last_polled: string | null
}
