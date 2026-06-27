<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ImageMode, LocalTaskMeta } from '@/types/api'
import { ApiClientError, MultiServerApiClient, initMultiServer } from '@/composables/useApi'
import { useSettings } from '@/composables/useSettings'
import { useTaskStore } from '@/composables/useTaskStore'
import { useToast } from '@/composables/useToast'

const emit = defineEmits<{
  (e: 'uploaded', taskId: string): void
}>()

const { settings } = useSettings()

initMultiServer(
  () => settings.value.serverUrl,
  () => settings.value.fallbackUrl,
)
const taskStore = useTaskStore()
const toast = useToast()

const MAX_BYTES = 200 * 1024 * 1024

const file = ref<File | null>(null)
const dragOver = ref(false)
const imageMode = ref<ImageMode>('base')
const concurrencyAuto = ref(true)
const concurrencyHint = ref<number>(4)

const uploadProgress = ref<number | null>(null)
const uploading = ref(false)

const fileOk = computed(() => {
  if (!file.value) return null
  if (!file.value.name.toLowerCase().endsWith('.pdf')) return '不是 PDF 文件'
  if (file.value.size > MAX_BYTES) return `超过 200 MB 限制 (${formatSize(file.value.size)})`
  return null
})

const canUpload = computed(() => {
  return !!file.value && fileOk.value === null && !uploading.value
})

const multiApi = computed(() => {
  return new MultiServerApiClient(
    settings.value.serverUrl,
    settings.value.fallbackUrl,
    settings.value.token,
  )
})

function formatSize(b: number): string {
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(2)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${b} B`
}

function onFileInput(e: Event): void {
  const target = e.target as HTMLInputElement
  if (target.files && target.files[0]) {
    setFile(target.files[0])
  }
}

function onDrop(e: DragEvent): void {
  e.preventDefault()
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) setFile(f)
}

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  dragOver.value = true
}

function onDragLeave(): void {
  dragOver.value = false
}

function setFile(f: File): void {
  file.value = f
  uploadProgress.value = null
}

function clearFile(): void {
  file.value = null
  uploadProgress.value = null
}

async function submit(): Promise<void> {
  if (!canUpload.value || !file.value) return
  uploading.value = true
  uploadProgress.value = 0
  try {
    const resp = await multiApi.value.upload({
      file: file.value,
      imageMode: imageMode.value,
      concurrencyHint: concurrencyAuto.value ? null : concurrencyHint.value,
      onUploadProgress: (p) => {
        uploadProgress.value = p
      },
    })

    const meta: LocalTaskMeta = {
      task_id: resp.task_id,
      file_name: file.value.name,
      file_size: file.value.size,
      image_mode: resp.image_mode,
      concurrency_hint: resp.concurrency_hint,
      created_local: new Date().toISOString(),
      last_seen_status: resp.status,
      last_polled: new Date().toISOString(),
      backend_url: (resp as any).backend || settings.value.serverUrl,
    }
    taskStore.add(meta)
    toast.success(`已上传 · task ${resp.task_id} · 模式 ${resp.image_mode}`)
    emit('uploaded', resp.task_id)
    clearFile()
  } catch (e) {
    if (e instanceof ApiClientError) {
      toast.error(`上传失败 · ${e.status} · ${e.detail}`)
    } else {
      toast.error(`上传失败 · ${String((e as Error).message ?? e)}`)
    }
  } finally {
    uploading.value = false
    uploadProgress.value = null
  }
}
</script>

<template>
  <section class="upload">
    <div
      class="dropzone"
      :class="{ 'dropzone--over': dragOver, 'dropzone--has': file && !fileOk }"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <input
        id="pdf-input"
        type="file"
        accept="application/pdf,.pdf"
        class="dropzone__input"
        @change="onFileInput"
      />
      <label v-if="!file" for="pdf-input" class="dropzone__cta">
        <div class="dropzone__icon">⬆</div>
        <div class="dropzone__title">拖拽 PDF 到这里,或点击选择文件</div>
        <div class="dropzone__sub muted">最大 200 MB</div>
      </label>

      <div v-else class="dropzone__file">
        <div class="dropzone__file-icon">📄</div>
        <div class="dropzone__file-info">
          <div class="dropzone__file-name" :title="file.name">{{ file.name }}</div>
          <div class="dropzone__file-meta muted">
            {{ formatSize(file.size) }}
            <span v-if="fileOk" class="badge badge--failed" style="margin-left: 6px;">
              {{ fileOk }}
            </span>
          </div>
        </div>
        <button class="btn btn--ghost btn--sm" @click.stop="clearFile">移除</button>
      </div>

      <div
        v-if="uploadProgress != null"
        class="progress progress--indeterminate"
        style="margin-top: 16px;"
      >
        <div class="progress__bar" />
      </div>
      <div v-if="uploadProgress != null" class="muted" style="text-align: center; margin-top: 6px;">
        上传中… {{ uploadProgress }}%
      </div>
    </div>

    <div class="upload__opts">
      <div>
        <span class="label">图像模式</span>
        <div class="radio-group">
          <label class="radio">
            <input v-model="imageMode" type="radio" value="base" />
            <span>
              <strong>base</strong>
              <span class="muted"> 1024 × 1024,适合扫描件 / PDF</span>
            </span>
          </label>
          <label class="radio">
            <input v-model="imageMode" type="radio" value="gundam" />
            <span>
              <strong>gundam</strong>
              <span class="muted"> 1024 + 640,动态裁切,适合单张图</span>
            </span>
          </label>
        </div>
      </div>

      <div>
        <span class="label">并发提示</span>
        <div class="concurrency">
          <label class="check">
            <input v-model="concurrencyAuto" type="checkbox" />
            <span>使用服务器推荐值</span>
          </label>
          <div v-if="!concurrencyAuto" class="concurrency__slider">
            <input
              v-model.number="concurrencyHint"
              type="range"
              min="1"
              max="16"
              step="1"
            />
            <span class="badge badge--muted mono">{{ concurrencyHint }}</span>
          </div>
        </div>
      </div>
    </div>

    <button
      class="btn btn--primary btn--block"
      :disabled="!canUpload"
      @click="submit"
    >
      <span v-if="uploading">上传中…</span>
      <span v-else>上传并创建任务</span>
    </button>
  </section>
</template>

<style scoped>
.upload {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.dropzone {
  position: relative;
  border: 2px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  padding: 32px 20px;
  text-align: center;
  transition: all 0.15s ease;
  cursor: pointer;
}
.dropzone:hover,
.dropzone--over {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.dropzone--has {
  border-color: var(--color-danger);
  background: var(--color-danger-soft);
}
.dropzone__input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.dropzone__icon {
  font-size: 32px;
  margin-bottom: 8px;
  color: var(--color-accent);
}
.dropzone__title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.dropzone__sub {
  font-size: 12px;
  margin-top: 4px;
}
.dropzone__file {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}
.dropzone__file-icon {
  font-size: 28px;
}
.dropzone__file-info {
  flex: 1;
  min-width: 0;
}
.dropzone__file-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dropzone__file-meta {
  font-size: 12px;
  margin-top: 2px;
}

.upload__opts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 640px) {
  .upload__opts { grid-template-columns: 1fr; }
}
.radio-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.radio {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-bg);
}
.radio:hover {
  background: var(--color-accent-soft);
}
.radio input { margin: 0; }
.concurrency {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-bg);
}
.concurrency__slider {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-bg);
}
.concurrency__slider input[type='range'] {
  flex: 1;
  accent-color: var(--color-accent);
}
</style>
