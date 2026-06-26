---
日期: 2026-06-26
文档类型: 用户使用手册
文档概述: Unlimited-OCR 局域网服务的浏览器前端 — Vue 3 + Vite,与 server.py / client.py 同一分支(feature/web-frontend)开发
---

# Unlimited-OCR Web 前端

针对 `client.py` 的浏览器版本。提供上传、状态轮询、结果在线预览(渲染 Markdown + 提取图片)三个主要流程,以及 token / server URL 等设置的本地保存。

## 1. 启动

### 1.1 启动后端(server.py)

先确认 `server.py` 已经启用了 CORS(本分支已经加上,默认 `*`)。

```bash
# 默认 CORS=* (LAN 任意来源)
python server.py --port 10001

# 收紧来源(可选,推荐在生产 LAN 上限定到具体 IP/端口)
python server.py --port 10001 \
    --cors-origin http://192.168.1.10:5173 \
    --cors-origin http://192.168.1.20:5173
```

启动后,从 stdout 抄下自动生成的 `OCR_API_TOKEN`(如果没设环境变量的话)。

### 1.2 启动前端(web/)

```bash
cd web
pnpm install            # 或 npm install
pnpm dev                # 开发模式,http://127.0.0.1:5173
# 或
pnpm build && pnpm preview    # 生产构建并本地预览
```

默认监听 `0.0.0.0:5173`,局域网其他机器也能访问。

## 2. 配置

打开 `http://127.0.0.1:5173` → 顶部 **编辑** 按钮:

| 字段 | 说明 |
|---|---|
| Server URL | 默认 `http://127.0.0.1:10001`,局域网里换成 `http://<server-ip>:10001` |
| Token (Bearer) | `server.py` 启动时打印的 `OCR_API_TOKEN` |
| 自动轮询 | 任务进入 `queued` / `running` 后,前端每 3 秒拉一次状态,直到 `completed` 或 `failed` |

设置保存在 `localStorage`,刷新页面不会丢。

## 3. 功能

### 3.1 新建任务

- 拖拽 / 选择 PDF(≤ 200 MB)
- 图像模式:`base`(PDF/扫描件)/ `gundam`(单张图,动态裁切)
- 并发提示:勾选「使用服务器推荐值」就交给 `server.py` 按 GPU 空闲显存自动选;不勾则手动指定 1~16
- 点击「上传并创建任务」,成功后自动跳到「任务列表」并选中刚上传的任务

### 3.2 任务列表

- 卡片显示 `task_id` (12 位 hex,前 6 + 后 4)、文件名 / 大小、状态徽章、进度条、当前页 / 总页、运行耗时、并发数
- 活动中的任务(queued / running)有蓝底高亮,失败任务有红框
- 任务完成后出现「下载 ZIP」按钮,直接走 `GET /api/v1/tasks/{id}/download` 拿结果

### 3.3 结果预览

切到「结果预览」标签页,前端自动:

1. 调 `/api/v1/tasks/{id}/download` 拿到 ZIP
2. 用 `fflate` 解压,提取 `result.md` 和 `images/`
3. `marked` + `DOMPurify` 渲染 Markdown,内置 `highlight.js` 语法高亮
4. 图片网格展示,点击放大

底栏「下载 ZIP」按钮可以重新触发浏览器下载。

### 3.4 顶部健康检查

- 启动 / 改 server URL / 改 token 后自动重拉
- 每 8 秒轮询一次 `GET /api/v1/health`
- 显示 GPU 型号、空闲显存、推荐并发、当前队列长度

## 4. 目录结构

```
web/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── index.html
├── public/
│   └── favicon.svg
└── src/
    ├── main.ts
    ├── App.vue                    # 顶层布局 + 三个 tab
    ├── env.d.ts
    ├── types/
    │   └── api.ts                 # 与 API_CONTRACT.md 对齐的 TS 类型
    ├── composables/
    │   ├── useApi.ts              # fetch 封装,带 Auth 头与错误解析
    │   ├── useSettings.ts         # localStorage 持久化
    │   ├── useTaskStore.ts        # 本地任务元数据
    │   └── useToast.ts            # 全局 toast
    ├── components/
    │   ├── SettingsBar.vue        # 顶部 server/token/健康条
    │   ├── HealthBadge.vue
    │   ├── UploadPanel.vue
    │   ├── TaskList.vue
    │   ├── TaskCard.vue
    │   ├── ResultViewer.vue
    │   ├── StatusBadge.vue
    │   └── ToastHost.vue
    └── styles/
        └── main.css               # 设计系统 token(CLAUDE.md 配色)
```

## 5. 常见问题

**Q1. 浏览器控制台报 `CORS policy: No 'Access-Control-Allow-Origin' header`。**
确认 `server.py` 启动日志里有 `[server] CORS allow_origins=...`,且列表里包含你前端页面的 origin。也可以用 `--cors-origin` 显式声明,或者直接传 `*`(LAN 默认)。

**Q2. 401 invalid token。**
顶部「编辑」检查 Token 字段,确保和 `OCR_API_TOKEN` 环境变量(或 server 启动时打印的随机串)一致。

**Q3. 上传一直转圈。**
打开浏览器 DevTools → Network,看 `/api/v1/tasks` 的 POST 是不是返回了非 2xx。最常见是 server 端没装 `python-multipart` (`pip install python-multipart`)。

**Q4. 「结果预览」里 PDF 没有图片。**
原 PDF 本来就没有可提取的位图,或者 `postprocess_sglang.py` 没截到 bbox(模型对某些排版漏检)。这属于后端问题,不在前端范围。

**Q5. `pnpm install` 在国内网络慢。**
设置镜像:`pnpm config set registry https://registry.npmmirror.com`,或直接用 `npm install`。

## 6. 与 `client.py` 的关系

| 操作 | client.py | Web |
|---|---|---|
| 上传 + 自动轮询 | `python client.py upload doc.pdf --watch` | 「新建任务」tab → 上传 |
| 查询 | `python client.py status <id>` | 「任务列表」自动轮询 |
| 下载 | `python client.py download <id> --out ./out` | 「任务列表」→ 下载 ZIP,或「结果预览」在线看 |
| 删除 | `python client.py delete <id>` | 「任务列表」→ 删除按钮 |
| 健康 | `python client.py health` | 顶部常驻 |

`client.py` 的所有能力 Web 都有覆盖;`client.py` 的优势是无 GUI、可写脚本。
