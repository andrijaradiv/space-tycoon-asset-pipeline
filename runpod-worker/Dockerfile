FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    build-essential \
    python3.10 \
    python3.10-dev \
    python3-pip \
    python3.10-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3.10 -m pip install --upgrade pip setuptools wheel
RUN python3.10 -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124

RUN git clone --depth 1 https://github.com/tencent-hunyuan/hunyuan3d-2.1.git Hunyuan3D-2.1
WORKDIR /workspace/Hunyuan3D-2.1
RUN python3.10 -m pip install -r requirements.txt
RUN cd hy3dpaint/custom_rasterizer && python3.10 -m pip install -e .
RUN cd hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh
RUN wget https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth -P hy3dpaint/ckpt

WORKDIR /workspace/worker
COPY requirements.txt .
RUN python3.10 -m pip install -r requirements.txt
COPY handler.py .

CMD ["python3.10", "-u", "handler.py"]
