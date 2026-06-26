import type {
  HealthResponse,
  TaskInfo,
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
