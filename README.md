<p align="center">
  <img src="assets/baidu.png" width="40%" alt="Baidu Inc." />
</p>

<hr>

<h1 align="center">Unlimited OCR Works</h1>

<div align="center">
  <a href="https://github.com/baidu/Unlimited-OCR">
    <img alt="GitHub" src="https://img.shields.io/badge/GitHub-Code-181717?logo=github&logoColor=white" />
  </a>
  <a href="https://huggingface.co/baidu/Unlimited-OCR">
    <img alt="Hugging Face" src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Model-ffc107?color=ffc107&logoColor=white" />
  </a>
</div>

<div align="center">
    <a href="https://arxiv.org/abs/2606.23050">
    <img alt="arXiv" src="https://img.shields.io/badge/arXiv-Unlimited OCR Works-b31b1b?logo=arxiv&logoColor=white" />
  </a>
  <a href="https://x.com/Baidu_Inc" target="_blank">
    <img alt="Twitter Follow" src="https://img.shields.io/badge/Twitter-Baidu Inc.-white?logo=x&logoColor=white" />
  </a>
</div>

<h3 align="center">Welcome the Era of One-shot Long-horizon Parsing.</h3>

<p align="center">
    <img src="assets/Unlimited-OCR.png" width="1000" alt="Unlimited OCR overview" />
</p>

## What this fork adds

This repository is a local fork of [baidu/Unlimited-OCR](https://github.com/baidu/Unlimited-OCR). Everything below the divider (`---`) is the original upstream README — the model, the Transformers / SGLang inference code, the citations, the license.

The **fork-specific additions** live in the rest of the repo and are documented separately:

| Addition | What it does | Where to start |
|----------|--------------|----------------|
| **One-click deployment scripts** | Fresh clone → usable service in 3 commands (`setup_env.sh` / `start_server.sh` / `stop_server.sh`) | **[§ One-click deployment](#one-click-deployment-a100-server-branch)** below |
| LAN HTTP gateway | Serve the model over the network so multiple laptops can share one GPU | `./start_server.sh` (details: [`README_API.md`](README_API.md) 中文) |
| CLI client | Talk to the gateway from a laptop that has no GPU | `ocr-client upload my.pdf --watch` (或 `python -m ocr_client`) |
| Browser frontend | Vue 3 SPA for non-technical users | `cd web && pnpm dev` (see [`web/README.md`](web/README.md) 中文) |
| `ocr-client` pip package | Pre-bundled version of the CLI for `uv tool install` / `pipx install` | `uv tool install ./ocr-client` (see [`ocr-client/README.md`](ocr-client/README.md) 中文) |
| Architecture overview | How the 4 paths relate | [`docs/architecture.md`](docs/architecture.md) |
| Operational runbook | Server bring-up, daily ops, disk layout, pre-flight checklist | [`AGENTS.md`](AGENTS.md) § Startup Runbook |
| Wire protocol (中文 canonical / English supplement) | Single source of truth for the HTTP API | [`API_CONTRACT.md`](API_CONTRACT.md) / [`docs/api-contract-en.md`](docs/api-contract-en.md) |
| Changelog | List of local commits vs upstream | [`CHANGELOG.md`](CHANGELOG.md) |

If you only want to use the model itself, follow the upstream "Inference" section below.

---

## One-click deployment (A100-server branch)

**一键部署** —— 本分支把整套 OCR 服务打包成「局域网共享 GPU」模式：一台 GPU 服务器跑网关，
其他电脑用 CLI / 浏览器提交 PDF、拿 Markdown 结果。**在新机器上从零到可用只需三条命令。**

> 英文速览：clone branch → `bash scripts/setup_env.sh` → `./start_server.sh`。
> 客户端见 §4；完整细节全部在下方中文手册中。

### 0. 硬件与系统要求

| 项目 | 要求 |
|------|------|
| GPU | NVIDIA 显卡，显存 ≥ 24 GB（实测 RTX 4090 24G / A100 40G）；并发随空闲显存自动分级 |
| 驱动 | NVIDIA driver ≥ 550（`nvidia-smi` 可用即可） |
| OS | Linux x86_64（Ubuntu 22.04/24.04 实测），需 root 或 sudo 装系统包 |
| 磁盘 | ≥ 20 GB（模型权重 ~6.4 GB + venv ~10 GB + 任务产物） |
| 网络 | 服务器需能访问 HuggingFace（仅首次下载模型时；离线机见下方 FAQ） |

### 1. 拉代码 → 一键装环境（首次约 10–20 分钟）

```bash
git clone -b A100-server https://github.com/wyh2255/Unlimited-OCR.git
cd Unlimited-OCR
bash scripts/setup_env.sh
```

脚本幂等，重复执行安全。它会自动完成：

1. 装系统包 `libnuma-dev g++ ninja-build`（缺了它们 sgl_kernel / JIT 编译必挂）
2. 创建 `.venv`（uv 管理，Python 3.12）
3. 安装**仓库内置的 sglang 定制 wheel**（`wheel/sglang-*.whl`，含本模型的自定义
   logit processor 补丁——严禁换成 PyPI 版 sglang）+ `requirements-api.txt`
4. 检查模型权重：缺失则自动从 HuggingFace 下载 `baidu/Unlimited-OCR` (~6.4 GB)
   到 `./Unlimited-OCR/`（模型不入 git）
5. 逐项验证 torch / sglang / pymupdf / fastapi import

### 2. 一键启动（后台守护）

```bash
./start_server.sh
```

输出形如：

```
网关已就绪: http://<服务器LAN IP>:10001  (PID 24728)
Token: <自动生成或复用 ~/.ocr_token 中的值>
日志: tail -f log/api_server.log
验证: curl -s http://127.0.0.1:10001/api/v1/health
```

- **幂等**：已在运行则直接提示退出；端口被非网关进程占用会报错并给排查命令。
- **Token**：优先 `$OCR_API_TOKEN` > `~/.ocr_token`（已有则复用）> 自动生成并持久化
  （chmod 600）。重启不变，除非你删掉 `~/.ocr_token`。
- **开机自启（可选）**：`crontab -e` 加一行
  `@reboot cd /root/Unlimited-OCR && ./start_server.sh >> log/boot.log 2>&1`
- 前台调试（看 SGLang 启动全过程）：`./start_gateway.sh`，Ctrl+C 停止。

### 3. 验证服务

```bash
# 服务器本机 —— 无需 token
curl -s http://127.0.0.1:10001/api/v1/health | python3 -m json.tool
# 期望: status=ok + 本机 GPU 型号/空闲显存/推荐并发

# 局域网其他电脑 —— 带 token
curl -s -H "Authorization: Bearer <你的token>" http://<服务器IP>:10001/api/v1/tasks/x
# 期望: HTTP 404 （说明鉴权通过、404 路径正常）

# 不带 token 访问受保护接口
curl -s -o /dev/null -w '%{http_code}\n' http://<服务器IP>:10001/api/v1/tasks/x
# 期望: 401
```

> SGLang 推理引擎是**懒启动**：网关起来后 GPU 显存占用仍很低，
> 第一个任务到达时才拉起 SGLang（首次约 30–40 s 预热），属正常现象。

### 4. 客户端使用（任意一台无 GPU 的电脑）

```bash
# 方式 A：CLI 客户端（推荐，纯 HTTP，无需 GPU）
pip install clients/python-cli        # 在克隆的本仓库里执行
export OCR_SERVER="http://<服务器IP>:10001"
export OCR_API_TOKEN="<你的token>"    # 服务器上 cat ~/.ocr_token

ocr-client health                     # 连通性检查
ocr-client upload paper.pdf --watch   # 上传→进度条→自动下载解压
# 结果在 ./paper/ 下: result.md + images/*.jpg

ocr-client status <task_id>           # 查询任务
ocr-client download <task_id> --out . # 手动下载 zip 并解压
ocr-client delete <task_id>           # 删除任务及服务器端磁盘

# 方式 B：浏览器（适合非技术用户）
cd clients/web && pnpm install && pnpm dev   # 打开 http://127.0.0.1:5173
# 右上角设置服务器地址和 token，拖入 PDF 即可
```

更多细节见 [`README_API.md`](README_API.md)（CLI/API 全量手册）、
[`clients/web/README.md`](clients/web/README.md)（前端手册）、
[`API_CONTRACT.md`](API_CONTRACT.md)（HTTP 协议契约）。

### 5. 日常运维速查

```bash
./stop_server.sh            # 优雅停止（SIGTERM，等 15s 后兜底 SIGKILL）
./start_server.sh           # 启动/重启（改完代码或配置后先 stop 再 start）
tail -f log/api_server.log                    # 网关日志
tail -f api_workdir/logs/<task_id>_sglang.log # 某任务的 SGLang 日志
watch -n 2 nvidia-smi                         # GPU 占用实时监控
```

服务器磁盘布局（默认 `--workdir ./api_workdir`）：
`tmp/<task_id>/`（任务中转，完成即删）、`outputs/<task_id>.zip`（结果，DELETE 时清）、
`logs/<task_id>_sglang.log`（推理日志，DELETE 时清）。

### 6. 常见问题（FAQ）

| 症状 | 原因与解决 |
|------|-----------|
| `FileNotFoundError: 'ninja'` | 启动时没走 `.venv/bin`。**必须用 `./start_server.sh`**（内部已 activate）；手动启动请先 `source .venv/bin/activate` |
| `Could not load any common_ops library!` | sgl_kernel 只有 sm90/sm100 变体。RTX 4090 (sm89) 需 `SGL_KERNEL_ARCH=90`（脚本已默认设置）；A100 无需理会 |
| sgl_kernel 报 `libnuma.so.1` 缺失 | `apt-get install -y libnuma-dev g++ ninja-build`（setup_env.sh 已自动处理） |
| JIT 编译报 `cannot execute 'cc1plus'` | 同上，缺 g++ |
| 模型下载不动 / 离线机器 | 有网的机器上 `hf download baidu/Unlimited-OCR --local-dir Unlimited-OCR` 后整个目录拷过去；或启动时 `MODEL_DIR=baidu/Unlimited-OCR ./start_server.sh` 直接读 HF ID |
| 401 Unauthorized | token 不对。以服务器上 `~/.ocr_token` 为准；多用户模式见 `README_API.md` |
| 端口被占 | `ps -ef | grep gateway.server` 找残留进程 kill 掉，再 `./start_server.sh` |

### 可调环境变量一览（`start_server.sh` 均支持同名覆盖）

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `10001` | 网关监听端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `GPU` | `0` | CUDA_VISIBLE_DEVICES 值 |
| `MODEL_DIR` | `./Unlimited-OCR` | 本地权重目录或 HuggingFace ID |
| `SGL_KERNEL_ARCH` | `90` | sgl_kernel 架构强制项（RTX 4090 必须；A100 可设 80） |
| `CUDA_HOME` | `/usr/local/cuda` | nvcc 路径 |
| `OCR_API_TOKEN` | 自动生成 | API Bearer token |

---

## Release
- [2026/06/24] 🤝 Thanks to [AK](https://x.com/_akhaliq) for creating a demo for us. It is now available at [Hugging Face Spaces](https://huggingface.co/spaces/baidu/Unlimited-OCR).
- [2026/06/23] 📄 Our paper is now available on [arXiv](https://arxiv.org/abs/2606.23050).
- [2026/06/23] 🤝 Thanks to the ModelScope community for their support. Our model is now available at [ModelScope](https://modelscope.cn/models/PaddlePaddle/Unlimited-OCR).
- [2026/06/22] 🚀 We present [Unlimited-OCR](https://github.com/baidu/Unlimited-OCR), aiming to push [Deepseek-OCR](https://github.com/deepseek-ai/DeepSeek-OCR) one step further.

## Inference

### Transformers
Inference using Huggingface transformers on NVIDIA GPUs. Requirements tested on python 3.12.3 + CUDA12.9：

```
torch==2.10.0
torchvision==0.25.0
transformers==4.57.1
Pillow==12.1.1
matplotlib==3.10.8
einops==0.8.2
addict==2.4.0
easydict==1.13
pymupdf==1.27.2.2
psutil==7.2.2
```

```python
import os
import torch
from transformers import AutoModel, AutoTokenizer

model_name = 'baidu/Unlimited-OCR'

tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
model = AutoModel.from_pretrained(
    model_name,
    trust_remote_code=True,
    use_safetensors=True,
    torch_dtype=torch.bfloat16,
)
model = model.eval().cuda()

# ── Single image supports two configs: gundam or base ──
# gundam: base_size=1024, image_size=640, crop_mode=True
# base: base_size=1024, image_size=1024, crop_mode=False
model.infer(
    tokenizer,
    prompt='<image>document parsing.',
    image_file='your_image.jpg',
    output_path='your/output/dir',
    base_size=1024, image_size=640, crop_mode=True,
    max_length=32768,
    no_repeat_ngram_size=35, ngram_window=128,
    save_results=True,
)

# ── Multi page / PDF only uses base (image_size=1024) ──
model.infer_multi(
    tokenizer,
    prompt='<image>Multi page parsing.',
    image_files=['page1.png', 'page2.png', 'page3.png'],
    output_path='your/output/dir',
    image_size=1024,
    max_length=32768,
    no_repeat_ngram_size=35, ngram_window=1024,
    save_results=True,
)

# ── PDF (convert pages to images, then multi-page parsing) ──
import tempfile, fitz  # PyMuPDF

def pdf_to_images(pdf_path, dpi=300):
    doc = fitz.open(pdf_path)
    tmp_dir = tempfile.mkdtemp(prefix='pdf_ocr_')
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    paths = []
    for i, page in enumerate(doc):
        out = os.path.join(tmp_dir, f'page_{i+1:04d}.png')
        page.get_pixmap(matrix=mat).save(out)
        paths.append(out)
    doc.close()
    return paths

model.infer_multi(
    tokenizer,
    prompt='<image>Multi page parsing.',
    image_files=pdf_to_images('your_doc.pdf', dpi=300),
    output_path='your/output/dir',
    image_size=1024,
    max_length=32768,
    no_repeat_ngram_size=35, ngram_window=1024,
    save_results=True,
)
```

### SGLang

Set up the environment (uv-managed virtualenv). Install the local SGLang wheel first,
then pin `kernels==0.9.0` and install PyMuPDF for PDF-to-image conversion:
```shell
uv venv --python 3.12
source .venv/bin/activate

uv pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl
uv pip install kernels==0.11.7
uv pip install pymupdf==1.27.2.2
```

Start the SGLang server:
```shell
python -m sglang.launch_server \
    --model baidu/Unlimited-OCR \
    --served-model-name Unlimited-OCR \
    --attention-backend fa3 \
    --page-size 1 \
    --mem-fraction-static 0.8 \
    --context-length 32768 \
    --enable-custom-logit-processor \
    --disable-overlap-schedule \
    --skip-server-warmup \
    --host 0.0.0.0 \
    --port 10000
```

Send streaming requests to the OpenAI-compatible API:
```python
import base64
import json
import os
import tempfile

import fitz
import requests
from sglang.srt.sampling.custom_logit_processor import DeepseekOCRNoRepeatNGramLogitProcessor

server_url = "http://127.0.0.1:10000"

session = requests.Session()
session.trust_env = False


def pdf_to_images(pdf_path, dpi=300):
    doc = fitz.open(pdf_path)
    tmp_dir = tempfile.mkdtemp(prefix="pdf_ocr_")
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    image_paths = []
    for i, page in enumerate(doc):
        image_path = os.path.join(tmp_dir, f"page_{i + 1:04d}.png")
        page.get_pixmap(matrix=mat).save(image_path)
        image_paths.append(image_path)
    doc.close()
    return image_paths


def encode_image(image_path):
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext.lstrip('.')}"
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def build_content(prompt, image_paths):
    return [{"type": "text", "text": prompt}] + [encode_image(path) for path in image_paths]


def generate(prompt, image_paths, image_mode, ngram_window):
    payload = {
        "model": "Unlimited-OCR",
        "messages": [{"role": "user", "content": build_content(prompt, image_paths)}],
        "temperature": 0,
        "skip_special_tokens": False,
        "images_config": {"image_mode": image_mode},
        "custom_logit_processor": DeepseekOCRNoRepeatNGramLogitProcessor.to_str(),
        "custom_params": {
            "ngram_size": 35,
            "window_size": ngram_window,
        },
        "stream": True,
    }
    response = session.post(
        f"{server_url}/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=1200,
        stream=True,
    )
    response.raise_for_status()

    chunks = []
    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data = line[len("data: "):]
        if data == "[DONE]":
            break
        event = json.loads(data)
        delta = event["choices"][0].get("delta", {}).get("content", "")
        if delta:
            print(delta, end="", flush=True)
            chunks.append(delta)
    print()
    return "".join(chunks)


# Single image supports two configs: gundam or base. Example below uses gundam.
generate("document parsing.", ["your_image.jpg"], image_mode="gundam", ngram_window=128)

# Multi image (base only)
generate("Multi page parsing.", ["page1.png", "page2.png"], image_mode="base", ngram_window=1024)

# PDF (base only)
generate("Multi page parsing.", pdf_to_images("your_doc.pdf", dpi=300), image_mode="base", ngram_window=1024)
```

For batch inference, `inference/cli.py` starts the SGLang server automatically and sends concurrent requests for an image directory or PDF:
```shell
# Image directory
python -m inference.cli \
    --image_dir ./examples/images \
    --output_dir ./outputs \
    --concurrency 8 \
    --image_mode gundam

# PDF pages
python -m inference.cli \
    --pdf ./examples/document.pdf \
    --output_dir ./outputs \
    --concurrency 8 \
    --image_mode gundam
```

Useful options:
```shell
--model_dir baidu/Unlimited-OCR   # Local path or Hugging Face model ID
--gpu 0                           # CUDA_VISIBLE_DEVICES value
--server_log ./log/sglang_server.log
```


## Visualization

<img src="assets/long-horizon-ocr.gif" width="100%" alt="Long-horizon OCR demo" />

## Acknowledgement

We would like to thank [Deepseek-OCR](https://github.com/deepseek-ai/DeepSeek-OCR), [Deepseek-OCR-2](https://github.com/deepseek-ai/DeepSeek-OCR-2), [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) for their valuable models and ideas.

## Citation
```bibtex
@misc{yin2026unlimitedocrworks,
      title={Unlimited OCR Works}, 
      author={Youyang Yin and Huanhuan Liu and YY and Qunyi Xie and Chaorun Liu and Shiqi Yang and Shaohua Wang and Zhanlong Liu and Hao Zou and Jinyue Chen and Shu Wei and Jingjing Wu and Mingxin Huang and Zhen Wu and Guibin Wang and Tengyu Du and Lei Jia},
      year={2026},
      eprint={2606.23050},
      archivePrefix={arXiv},
      primaryClass={cs.CV},
      url={https://arxiv.org/abs/2606.23050}, 
}
