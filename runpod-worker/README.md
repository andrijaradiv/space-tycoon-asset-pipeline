# RunPod Hunyuan3D Worker

This folder is the cloud-side worker that Codex calls through the local MCP server.

Target shape:

```text
RunPod Serverless job input:
{
  "input": {
    "image_base64": "...",
    "asset_name": "floating_moon_base_plate",
    "textured": true,
    "target_polycount": 8000,
    "output_format": "glb",
    "roblox_optimized": true
  }
}
```

Target output:

```text
{
  "glb_base64": "...",
  "asset_name": "floating_moon_base_plate",
  "textured": true
}
```

## Deployment Notes

Use a GPU with at least 24GB VRAM for textured output. Hunyuan3D 2.1 documents roughly 10GB for shape generation, 21GB for texture generation, and 29GB total if running shape + texture together. A 4090 can be a cheap starting point; A100/L40S class GPUs are smoother.

The Dockerfile intentionally has a separate model-cache step. For low cold starts, build an image that already has the repo, compiled paint dependencies, and model weights cached.

## Local Test

The stub mode only proves RunPod handler wiring:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python handler.py --test_input '{"input":{"asset_name":"smoke","image_base64":"dGVzdA=="}}'
```

Real Hunyuan generation requires building the Docker image on a CUDA GPU environment.
