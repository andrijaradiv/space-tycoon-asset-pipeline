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
    "texture_resolution": 1024,
    "texture_num_views": 8,
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

The Dockerfile wraps RunPod's `alexkozinov/hunyan3d-2-cuda12.4:latest` pod-template image with this serverless handler. That template appears in RunPod search under Pod templates, but using it as a base image lets us keep the pay-per-job serverless endpoint instead of running an always-on pod UI.

The handler searches common locations for a Hunyuan checkout. If the base image changes, set `HUNYUAN3D_ROOT` to the directory containing `hy3dshape`.

## Multiview Shape Tests

For hard-surface assets that melt from one image, use the Hunyuan3D-2mv shape model with cropped views from one shared turntable sheet:

```json
{
  "input": {
    "asset_name": "space_tycoon_item_pedestal_mv",
    "image_base64": "...front view...",
    "image_filename": "front.png",
    "view_images_base64": {
      "front": "...",
      "left": "...",
      "back": "..."
    },
    "view_image_filenames": {
      "front": "front.png",
      "left": "left.png",
      "back": "back.png"
    },
    "model_id": "tencent/Hunyuan3D-2mv",
    "texture_model_id": "tencent/Hunyuan3D-2",
    "shape_subfolder": "hunyuan3d-dit-v2-mv",
    "shape_num_inference_steps": 40,
    "shape_guidance_scale": 5,
    "octree_resolution": 380,
    "num_chunks": 20000,
    "target_polycount": 15000,
    "texture_resolution": 1024,
    "texture_num_views": 8
  }
}
```

The worker prefers the `hy3dgen` API when a multiview model id is selected. This matters because Hunyuan3D-2mv is part of the Hunyuan3D-2 family, while Hunyuan3D-2.1 uses a different single-view shape package.

Keep `model_id` and `texture_model_id` separate. Hunyuan3D-2mv is a shape model; texture generation should use a texture-capable model such as `tencent/Hunyuan3D-2`.

## Local Test

The stub mode only proves RunPod handler wiring:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python handler.py --test_input '{"input":{"asset_name":"smoke","image_base64":"dGVzdA=="}}'
```

Real Hunyuan generation requires building the Docker image on a CUDA GPU environment.
