# This RunPod pod template image already contains a Hunyuan3D CUDA stack.
# We wrap it with a serverless handler so Codex can call it through RunPod's
# queue API instead of running an always-on pod UI.
FROM alexkozinov/hunyan3d-2-cuda12.4:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
WORKDIR /workspace

WORKDIR /workspace/worker
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install -r requirements.txt
COPY handler.py .

CMD ["python3", "-u", "handler.py"]
