<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TaskInfo } from '@/types/api'
import ResultViewer from './components/ResultViewer.vue'
import SettingsBar from './components/SettingsBar.vue'
import TaskList from './components/TaskList.vue'
import ToastHost from './components/ToastHost.vue'
import UploadPanel from './components/UploadPanel.vue'
import { useSettings } from '@/composables/useSettings'

type Tab = 'upload' | 'tasks' | 'result'

const { settings } = useSettings()
const tab = ref<Tab>('upload')
const taskListRef = ref<InstanceType<typeof TaskList> | null>(null)

function handleUploaded(taskId: string): void {
  tab.value = 'tasks'
  // Wait one tick for the list to rebuild, then select the new task.
  setTimeout(() => taskListRef.value?.select(taskId), 50)
}

const selectedInfo = computed<TaskInfo | null>(
  () => taskListRef.value?.getSelected() ?? null,
)
</script>

<template>
  <div class="app">
    <SettingsBar />

    <nav class="tabs">
      <button
        class="tabs__item"
        :class="{ 'tabs__item--active': tab === 'upload' }"
        @click="tab = 'upload'"
      >
        新建任务
      </button>
      <button
        class="tabs__item"
        :class="{ 'tabs__item--active': tab === 'tasks' }"
        @click="tab = 'tasks'"
      >
        任务列表
      </button>
      <button
        class="tabs__item"
        :class="{ 'tabs__item--active': tab === 'result' }"
        @click="tab = 'result'"
      >
        结果预览
      </button>
      <div class="tabs__spacer" />
      <a
        v-if="settings.serverUrl"
        :href="settings.serverUrl + '/docs'"
        target="_blank"
        rel="noopener"
        class="tabs__link"
      >
        API 文档 ↗
      </a>
    </nav>

    <main class="main">
      <section v-show="tab === 'upload'" class="pane pane--narrow">
        <UploadPanel @uploaded="handleUploaded" />
      </section>

      <section v-show="tab === 'tasks'" class="pane pane--narrow">
        <TaskList ref="taskListRef" />
      </section>

      <section v-show="tab === 'result'" class="pane pane--wide">
        <ResultViewer :task="selectedInfo" />
      </section>
    </main>

    <ToastHost />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--color-bg);
}
.tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 20px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg);
}
.tabs__item {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-muted);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.tabs__item:hover { color: var(--color-text); }
.tabs__item--active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
.tabs__spacer { flex: 1; }
.tabs__link {
  font-size: 12px;
  color: var(--color-text-muted);
}

.main {
  flex: 1;
  display: flex;
  padding: 20px;
  min-height: 0;
}
.pane {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}
.pane--narrow {
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
}
.pane--wide {
  max-width: 1280px;
  margin: 0 auto;
  width: 100%;
}
</style>
