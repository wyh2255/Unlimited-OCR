<script setup lang="ts">
import { ref, watch } from 'vue'
import HealthBadge from './HealthBadge.vue'
import { useSettings } from '@/composables/useSettings'

const { settings } = useSettings()
const showToken = ref(false)
const editing = ref(false)
const draftUrl = ref(settings.value.serverUrl)
const draftToken = ref(settings.value.token)

watch(
  () => [settings.value.serverUrl, settings.value.token],
  ([u, t]) => {
    draftUrl.value = String(u)
    draftToken.value = String(t)
  },
)

function open() {
  draftUrl.value = settings.value.serverUrl
  draftToken.value = settings.value.token
  editing.value = true
}

function save() {
  settings.value.serverUrl = draftUrl.value.trim() || settings.value.serverUrl
  settings.value.token = draftToken.value.trim()
  editing.value = false
}

function cancel() {
  editing.value = false
}
</script>

<template>
  <header class="topbar">
    <div class="topbar__brand">
      <span class="logo">U</span>
      <div>
        <div class="topbar__title">Unlimited-OCR</div>
        <div class="topbar__sub muted">局域网 PDF OCR Web</div>
      </div>
    </div>

    <div class="topbar__center">
      <HealthBadge />
    </div>

    <div class="topbar__right">
      <div v-if="!editing" class="topbar__summary" @click="open">
        <span class="mono summary-url" :title="settings.serverUrl">{{ settings.serverUrl }}</span>
        <span class="badge badge--muted">
          {{ settings.token ? 'token 已设置' : '未设 token' }}
        </span>
        <button class="btn btn--ghost btn--sm">编辑</button>
      </div>

      <div v-else class="topbar__form">
        <div class="topbar__form-row">
          <span class="label">Server URL</span>
          <input
            v-model="draftUrl"
            class="input"
            placeholder="http://127.0.0.1:10001"
            @keyup.enter="save"
          />
        </div>
        <div class="topbar__form-row">
          <span class="label">Token (Bearer)</span>
          <div class="topbar__token">
            <input
              v-model="draftToken"
              class="input"
              :type="showToken ? 'text' : 'password'"
              placeholder="从 server 启动日志里抄过来"
              autocomplete="off"
              @keyup.enter="save"
            />
            <button
              class="btn btn--ghost btn--sm"
              type="button"
              @click="showToken = !showToken"
            >
              {{ showToken ? '隐藏' : '显示' }}
            </button>
          </div>
        </div>
        <div class="topbar__form-actions">
          <button class="btn btn--secondary btn--sm" @click="cancel">取消</button>
          <button class="btn btn--primary btn--sm" @click="save">保存</button>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--header-height);
  background: var(--color-bg);
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: minmax(200px, 1fr) minmax(280px, auto) minmax(280px, 2fr);
  align-items: center;
  gap: 16px;
  padding: 0 20px;
}
.topbar__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-accent);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 18px;
}
.topbar__title {
  font-weight: 600;
  font-size: 15px;
  line-height: 1.2;
}
.topbar__sub {
  font-size: 11px;
}
.topbar__center {
  display: flex;
  justify-content: center;
  min-width: 0;
}
.topbar__right {
  display: flex;
  justify-content: flex-end;
  min-width: 0;
}
.topbar__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  max-width: 100%;
}
.topbar__summary:hover {
  background: var(--color-card);
}
.summary-url {
  font-size: 12px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar__form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
  min-width: 320px;
}
.topbar__form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.topbar__token {
  display: flex;
  gap: 4px;
  align-items: center;
}
.topbar__form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 4px;
}
</style>
