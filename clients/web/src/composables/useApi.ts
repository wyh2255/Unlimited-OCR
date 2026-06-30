import type {
  DownloadFormat,
  HealthResponse,
  MeResponse,
  TaskInfo,
  TaskListResponse,
  UploadOptions,
  UploadResponse,
} from '@/types/api'

export class ApiClientError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`)
    this.name = 'ApiClientError'
    this.status = status
    this.detail = detail
  }
}

export class ApiClient {
  private baseUrl: string
  private token: string

  constructor(baseUrl: string, token: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
    this.token = token
  }

  setCredentials(baseUrl: string, token: string): void {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
    this.token = token
  }

  private buildHeaders(extra?: Record<string, string>): Record<string, string> {
    const headers: Record<string, string> = { ...(extra ?? {}) }
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`
    }
    return headers
  }

  private async parseError(resp: Response): Promise<ApiClientError> {
    let detail = `HTTP ${resp.status}`
    try {
      const data = await resp.json()
      if (data && typeof data === 'object' && typeof data.detail === 'string') {
        detail = data.detail
      } else if (typeof data === 'string' && data.length > 0) {
        detail = data
      }
    } catch {
      try {
        const text = await resp.text()
        if (text) detail = text
      } catch {
        // give up
      }
    }
    return new ApiClientError(resp.status, detail)
  }

  private async check<T>(resp: Response): Promise<T> {
    if (resp.ok) {
      if (resp.status === 204) return undefined as T
      return (await resp.json()) as T
    }
    throw await this.parseError(resp)
  }

  async health(): Promise<HealthResponse> {
    const resp = await fetch(`${this.baseUrl}/api/v1/health`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    return this.check<HealthResponse>(resp)
  }

  async upload(opts: UploadOptions): Promise<UploadResponse> {
    const form = new FormData()
    form.append('file', opts.file, opts.file.name)
    form.append('image_mode', opts.imageMode)
    if (opts.concurrencyHint != null) {
      form.append('concurrency_hint', String(opts.concurrencyHint))
    }

    return new Promise<UploadResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${this.baseUrl}/api/v1/tasks`)
      if (this.token) {
        xhr.setRequestHeader('Authorization', `Bearer ${this.token}`)
      }

      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable && opts.onUploadProgress) {
          opts.onUploadProgress(Math.round((e.loaded / e.total) * 100))
        }
      })

      xhr.addEventListener('load', () => {
        const resp = new Response(xhr.responseText, {
          status: xhr.status,
          headers: new Headers(
            xhr.getAllResponseHeaders().split('\r\n').reduce<Record<string, string>>(
              (acc, line) => {
                const idx = line.indexOf(':')
                if (idx > 0) {
                  acc[line.slice(0, idx).trim().toLowerCase()] = line
                    .slice(idx + 1)
                    .trim()
                }
                return acc
              },
              {},
            ),
          ),
        })
        // Reuse the JSON body by creating a fresh Response.
        const wrapped = new Response(xhr.responseText, { status: xhr.status })
        this.check<UploadResponse>(wrapped).then(resolve, reject)
        void resp // keep the original around to silence unused warning
      })

      xhr.addEventListener('error', () => {
        reject(new ApiClientError(0, '网络错误,请检查 server URL 与 CORS 配置'))
      })
      xhr.addEventListener('abort', () => {
        reject(new ApiClientError(0, '上传被取消'))
      })

      xhr.send(form)
    })
  }

  async getTask(taskId: string): Promise<TaskInfo> {
    const resp = await fetch(`${this.baseUrl}/api/v1/tasks/${taskId}`, {
      method: 'GET',
      headers: this.buildHeaders({ Accept: 'application/json' }),
    })
    return this.check<TaskInfo>(resp)
  }

  async whoami(): Promise<MeResponse> {
    const resp = await fetch(`${this.baseUrl}/api/v1/me`, {
      method: 'GET',
      headers: this.buildHeaders({ Accept: 'application/json' }),
    })
    return this.check<MeResponse>(resp)
  }

  async listTasks(scope: 'mine' | 'all' = 'mine'): Promise<TaskListResponse> {
    const resp = await fetch(`${this.baseUrl}/api/v1/tasks?scope=${scope}`, {
      method: 'GET',
      headers: this.buildHeaders({ Accept: 'application/json' }),
    })
    return this.check<TaskListResponse>(resp)
  }

  async deleteTask(taskId: string): Promise<void> {
    const resp = await fetch(`${this.baseUrl}/api/v1/tasks/${taskId}`, {
      method: 'DELETE',
      headers: this.buildHeaders(),
    })
    await this.check<void>(resp)
  }

  /**
   * Downloads the result zip and triggers a browser save.
   * @param taskId 12-char task id
   * @param fileName suggested file name (typically `<taskId>.zip`)
   */
  async downloadResult(
    taskId: string,
    fileName: string,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<void> {
    const resp = await fetch(
      `${this.baseUrl}/api/v1/tasks/${taskId}/download`,
      { method: 'GET', headers: this.buildHeaders() },
    )
    if (!resp.ok) throw await this.parseError(resp)

    const total = Number(resp.headers.get('Content-Length') ?? 0)
    const reader = resp.body?.getReader()
    if (!reader) {
      // Fallback: just save the blob.
      const blob = await resp.blob()
      triggerDownload(blob, fileName)
      return
    }

    const chunks: Uint8Array[] = []
    let loaded = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (value) {
        chunks.push(value)
        loaded += value.byteLength
        if (onProgress) onProgress(loaded, total)
      }
    }
    const blob = new Blob(chunks, { type: 'application/zip' })
    triggerDownload(blob, fileName)
  }

  async fetchResultBlob(taskId: string): Promise<Blob> {
    const resp = await fetch(
      `${this.baseUrl}/api/v1/tasks/${taskId}/download`,
      { method: 'GET', headers: this.buildHeaders() },
    )
    if (!resp.ok) throw await this.parseError(resp)
    return resp.blob()
  }

  async downloadAs(taskId: string, fmt: DownloadFormat): Promise<void> {
    const resp = await fetch(
      `${this.baseUrl}/api/v1/tasks/${taskId}/download?format=${fmt}`,
      { method: 'GET', headers: this.buildHeaders() },
    )
    if (!resp.ok) throw await this.parseError(resp)
    const blob = await resp.blob()
    const cd = resp.headers.get('Content-Disposition') ?? ''
    const match = cd.match(/filename="([^"]+)"/)
    const ext = fmt === 'md' ? 'zip' : fmt === 'latex' ? 'tex' : fmt
    const fileName = match?.[1] ?? `${taskId}.${ext}`
    triggerDownload(blob, fileName)
  }
}

function triggerDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export class MultiServerApiClient {
  private primary: ApiClient
  private fallback: ApiClient | null
  private taskBackend: Map<string, string>

  constructor(
    primaryUrl: string,
    fallbackUrl: string,
    token: string,
  ) {
    this.primary = new ApiClient(primaryUrl, token)
    this.fallback = fallbackUrl
      ? new ApiClient(fallbackUrl, token)
      : null
    this.taskBackend = new Map()
  }

  setCredentials(primaryUrl: string, fallbackUrl: string, token: string): void {
    this.primary.setCredentials(primaryUrl, token)
    this.fallback = fallbackUrl
      ? new ApiClient(fallbackUrl, token)
      : null
    this.taskBackend.clear()
  }

  async health(): Promise<HealthResponse> {
    return this.primary.health()
  }

  async upload(opts: UploadOptions): Promise<UploadResponse & { backend?: string }> {
    interface HealthResult {
      client: ApiClient
      url: string
      health: HealthResponse | null
      error: boolean
    }

    const candidates: { client: ApiClient; url: string }[] = [
      { client: this.primary, url: getPrimaryUrl() },
    ]
    if (this.fallback) {
      candidates.push({ client: this.fallback, url: getFallbackUrl() })
    }

    const results: HealthResult[] = await Promise.all(
      candidates.map(async (c) => {
        try {
          const h = await c.client.health()
          return { client: c.client, url: c.url, health: h, error: false }
        } catch {
          return { client: c.client, url: c.url, health: null, error: true }
        }
      }),
    )

    const available = results.filter((r): r is HealthResult & { health: HealthResponse } => !r.error && r.health !== null)
    if (available.length === 0) {
      const resp = await this.primary.upload(opts)
      this.taskBackend.set(resp.task_id, getPrimaryUrl())
      return { ...resp, backend: getPrimaryUrl() }
    }

    available.sort((a, b) => {
      const aIdle = a.health.current_task === null ? 0 : 1
      const bIdle = b.health.current_task === null ? 0 : 1
      if (aIdle !== bIdle) return aIdle - bIdle
      const aQ = a.health.queue_length ?? 0
      const bQ = b.health.queue_length ?? 0
      if (aQ !== bQ) return aQ - bQ
      if (a.url === getPrimaryUrl()) return -1
      if (b.url === getPrimaryUrl()) return 1
      return 0
    })

    const chosen = available[0]
    const resp = await chosen.client.upload(opts)
    this.taskBackend.set(resp.task_id, chosen.url)
    return { ...resp, backend: chosen.url }
  }

  async getTask(taskId: string): Promise<TaskInfo> {
    return this._getClient(taskId).getTask(taskId)
  }

  async deleteTask(taskId: string): Promise<void> {
    return this._getClient(taskId).deleteTask(taskId)
  }

  async downloadResult(taskId: string, fileName: string, onProgress?: (loaded: number, total: number) => void): Promise<void> {
    return this._getClient(taskId).downloadResult(taskId, fileName, onProgress)
  }

  async fetchResultBlob(taskId: string): Promise<Blob> {
    return this._getClient(taskId).fetchResultBlob(taskId)
  }

  private _getClient(taskId: string): ApiClient {
    const url = this.taskBackend.get(taskId)
    const fallbackUrl = getFallbackUrl()
    if (url && fallbackUrl && url === fallbackUrl && this.fallback) {
      return this.fallback
    }
    return this.primary
  }
}

// Module-level helpers to read settings
let _getPrimaryUrl: () => string = () => ''
let _getFallbackUrl: () => string = () => ''

export function initMultiServer(
  getPrimaryUrlFn: () => string,
  getFallbackUrlFn: () => string,
): void {
  _getPrimaryUrl = getPrimaryUrlFn
  _getFallbackUrl = getFallbackUrlFn
}

function getPrimaryUrl(): string { return _getPrimaryUrl() }
function getFallbackUrl(): string { return _getFallbackUrl() }

let _client: ApiClient | null = null
let _clientKey = ''

export function useApi(
  baseUrl: string,
  token: string,
): ApiClient {
  const key = `${baseUrl}::${token}`
  if (!_client || _clientKey !== key) {
    _client = new ApiClient(baseUrl, token)
    _clientKey = key
  }
  return _client
}
