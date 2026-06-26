<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import 'highlight.js/styles/github.css'
import { unzipSync, strFromU8 } from 'fflate'

import type { TaskInfo } from '@/types/api'
import { ApiClientError, useApi } from '@/composables/useApi'
import { useSettings } from '@/composables/useSettings'
import { useToast } from '@/composables/useToast'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('css', css)

const props = defineProps<{ task: TaskInfo | null }>()
const emit = defineEmits<{
  (e: 'open-image', url: string, name: string): void
}>()

const { settings } = useSettings()
const toast = useToast()
const api = computed(() => useApi(settings.value.serverUrl, settings.value.token))

const tab = ref<'markdown' | 'images' | 'raw'>('markdown')
const loading = ref(false)
const loadingText = ref('')

const markdown = ref('')
const imageFiles = ref<string[]>([])
const resultBlob = ref<Blob | null>(null)
const imageObjectUrls = ref<string[]>([])

const html = computed(() => {
  if (!markdown.value) return ''
  const raw = marked.parse(markdown.value, {
    gfm: true,
    breaks: true,
    async: false,
  }) as string
  return DOMPurify.sanitize(raw, {
    ADD_ATTR: ['target'],
  })
})

watch(
  () => props.task?.task_id,
  (id) => {
    reset()
    if (id) void load(id)
  },
  { immediate: true },
)

function reset(): void {
  markdown.value = ''
  imageFiles.value = []
  resultBlob.value = null
  imageObjectUrls.value.forEach((u) => URL.revokeObjectURL(u))
  imageObjectUrls.value = []
}

async function load(taskId: string): Promise<void> {
  if (!props.task || props.task.status !== 'completed') return
  loading.value = true
  loadingText.value = '下载结果 ZIP…'
  try {
    const blob = await api.value.fetchResultBlob(taskId)
    resultBlob.value = blob
    const { md, images } = await extractZip(blob)
    markdown.value = md
    imageFiles.value = images.map((i) => i.name)
    imageObjectUrls.value = images.map((i) => URL.createObjectURL(i.blob))
    loadingText.value = ''
  } catch (e) {
    if (e instanceof ApiClientError) {
      toast.error(`下载失败 · ${e.status} · ${e.detail}`)
    } else {
      toast.error(`解析失败 · ${String((e as Error).message ?? e)}`)
    }
  } finally {
    loading.value = false
  }
}

interface ExtractedImage {
  name: string
  blob: Blob
}

async function extractZip(blob: Blob): Promise<{ md: string; images: ExtractedImage[] }> {
  const buf = new Uint8Array(await blob.arrayBuffer())
  const files = unzipSync(buf)
  let md = ''
  const images: ExtractedImage[] = []
  for (const [name, data] of Object.entries(files)) {
    const base = name.split('/').pop() ?? name
    if (base === 'result.md' || name.endsWith('/result.md')) {
      md = strFromU8(data)
    } else if (/\.(jpe?g|png|webp|gif)$/i.test(base)) {
      images.push({ name: base, blob: new Blob([data], { type: mimeFor(base) }) })
    }
  }
  images.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  return { md, images }
}

function mimeFor(name: string): string {
  const ext = name.toLowerCase().split('.').pop() ?? ''
  if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg'
  if (ext === 'png') return 'image/png'
  if (ext === 'webp') return 'image/webp'
  if (ext === 'gif') return 'image/gif'
  return 'application/octet-stream'
}

function downloadRaw(): void {
  if (!resultBlob.value || !props.task) return
  const url = URL.createObjectURL(resultBlob.value)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.task.task_id}.zip`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function imageUrl(name: string): string {
  const idx = imageFiles.value.indexOf(name)
  return idx >= 0 ? imageObjectUrls.value[idx] : ''
}
</script>

<template>
  <div class="viewer">
    <div v-if="!props.task" class="viewer__empty muted">
      选择一个已完成的任务查看结果
    </div>

    <template v-else>
      <div v-if="props.task.status !== 'completed'" class="viewer__empty muted">
        任务状态: <strong>{{ props.task.status }}</strong>,完成后才能查看结果
      </div>

      <template v-else>
        <div class="viewer__tabs">
          <button
            class="tab"
            :class="{ 'tab--active': tab === 'markdown' }"
            @click="tab = 'markdown'"
          >
            渲染预览
          </button>
          <button
            class="tab"
            :class="{ 'tab--active': tab === 'images' }"
            @click="tab = 'images'"
          >
            图片 ({{ imageFiles.length }})
          </button>
          <button
            class="tab"
            :class="{ 'tab--active': tab === 'raw' }"
            @click="tab = 'raw'"
          >
            原文
          </button>
          <div class="viewer__spacer" />
          <button class="btn btn--secondary btn--sm" @click="downloadRaw">
            下载 ZIP
          </button>
        </div>

        <div v-if="loading" class="viewer__loading">
          <div class="progress progress--indeterminate"><div class="progress__bar" /></div>
          <div class="muted" style="margin-top: 8px;">{{ loadingText }}</div>
        </div>

        <div v-else-if="tab === 'markdown'" class="viewer__md" v-html="html" />

        <div v-else-if="tab === 'images'" class="viewer__images">
          <div v-if="imageFiles.length === 0" class="muted">该 PDF 没有提取到图片</div>
          <a
            v-for="name in imageFiles"
            :key="name"
            class="thumb"
            :href="imageUrl(name)"
            target="_blank"
            rel="noopener"
            @click.prevent="emit('open-image', imageUrl(name), name)"
          >
            <img :src="imageUrl(name)" :alt="name" loading="lazy" />
            <div class="thumb__name mono">{{ name }}</div>
          </a>
        </div>

        <pre v-else-if="tab === 'raw'" class="viewer__raw"><code>{{ markdown }}</code></pre>
      </template>
    </template>
  </div>
</template>

<style scoped>
.viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.viewer__empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  text-align: center;
  padding: 40px;
}
.viewer__tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 16px;
  padding-bottom: 0;
}
.tab {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-muted);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  border-radius: 0;
}
.tab:hover { color: var(--color-text); }
.tab--active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
.viewer__spacer { flex: 1; }
.viewer__loading {
  padding: 40px 20px;
  text-align: center;
}
.viewer__md {
  line-height: 1.7;
  font-size: 14px;
  color: var(--color-text);
  overflow-y: auto;
  padding: 0 4px 16px;
  flex: 1;
  min-height: 0;
}
.viewer__md :deep(h1),
.viewer__md :deep(h2),
.viewer__md :deep(h3) {
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.3;
}
.viewer__md :deep(h1) { font-size: 22px; }
.viewer__md :deep(h2) { font-size: 18px; }
.viewer__md :deep(h3) { font-size: 16px; }
.viewer__md :deep(p) { margin: 0.6em 0; }
.viewer__md :deep(ul),
.viewer__md :deep(ol) { padding-left: 1.5em; }
.viewer__md :deep(code) {
  background: var(--color-card);
  padding: 1px 5px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.9em;
}
.viewer__md :deep(pre) {
  background: var(--color-card);
  padding: 12px 14px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-size: 12.5px;
}
.viewer__md :deep(pre code) {
  background: transparent;
  padding: 0;
}
.viewer__md :deep(blockquote) {
  border-left: 3px solid var(--color-border-strong);
  margin: 0.8em 0;
  padding: 0 0 0 12px;
  color: var(--color-text-muted);
}
.viewer__md :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.8em 0;
}
.viewer__md :deep(th),
.viewer__md :deep(td) {
  border: 1px solid var(--color-border);
  padding: 6px 10px;
  text-align: left;
}
.viewer__md :deep(th) {
  background: var(--color-card);
  font-weight: 600;
}
.viewer__md :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-md);
  margin: 0.5em 0;
}
.viewer__md :deep(a) { color: var(--color-accent); }

.viewer__images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.thumb {
  display: flex;
  flex-direction: column;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  text-decoration: none;
  color: inherit;
  transition: all 0.15s ease;
}
.thumb:hover {
  border-color: var(--color-accent);
  text-decoration: none;
}
.thumb img {
  width: 100%;
  height: 120px;
  object-fit: cover;
  background: var(--color-bg);
}
.thumb__name {
  font-size: 10px;
  padding: 4px 6px;
  text-align: center;
  border-top: 1px solid var(--color-border);
  background: var(--color-bg);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.viewer__raw {
  background: var(--color-card);
  padding: 12px 14px;
  border-radius: var(--radius-md);
  overflow: auto;
  flex: 1;
  min-height: 0;
  font-size: 12px;
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
