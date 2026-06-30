FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3.12 python3.12-venv python3-pip git ninja-build libgl1-mesa-glx \
    pandoc libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY wheel/ wheel/
COPY requirements-api.txt .
RUN python3.12 -m venv .venv && \
    . .venv/bin/activate && \
    pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl && \
    pip install kernels==0.11.7 pymupdf==1.27.2.2 && \
    pip install -r requirements-api.txt

COPY Unlimited-OCR/ Unlimited-OCR/
COPY gateway/ gateway/
COPY inference/ inference/
COPY model/ model/

ENV OCR_API_TOKEN=""
EXPOSE 10001

CMD [".venv/bin/python", "-m", "gateway.server", "--host", "0.0.0.0", "--port", "10001", "--model-dir", "./Unlimited-OCR"]
