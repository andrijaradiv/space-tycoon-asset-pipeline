# Space Tycoon Asset Pipeline

This workspace turns generated concept images into Roblox-ready 3D asset files.

The intended loop is:

```text
Codex -> local MCP server -> RunPod Serverless Hunyuan3D worker -> GLB -> Roblox Studio
```

## What Is Ready

- `src/mcp-server.mjs`: local Codex MCP server.
- `runpod-worker/`: RunPod Serverless worker scaffold for Hunyuan3D 2.1.
- `scripts/install-mcp.sh`: installs the local MCP server into Codex.
- `scripts/test-mcp.mjs`: smoke-tests the MCP server without cloud credentials.

## Local Setup

Install the MCP server in Codex:

```bash
npm run mcp:install
```

Smoke-test the server:

```bash
npm run mcp:test
```

Check whether cloud credentials are configured from Codex using the MCP tool:

```text
check_config()
```

Generate an asset after RunPod is configured:

```text
generate_roblox_asset_from_image(
  image_path="/absolute/path/to/base_plate.png",
  asset_name="floating_moon_base_plate",
  textured=true,
  target_polycount=8000
)
```

The generated model is saved under:

```text
/Users/andrija/Documents/RobloxGame 2/assets/models
```

## Cloud Setup Needed

RunPod account/payment/API-key setup is the only part that cannot be completed blindly here. Once a RunPod API key and serverless endpoint ID exist, add them to your shell or `.env`:

```bash
export RUNPOD_API_KEY="..."
export RUNPOD_ENDPOINT_ID="..."
```

RunPod docs used for this scaffold:

- Serverless overview: https://docs.runpod.io/serverless/overview
- Handler functions: https://docs.runpod.io/serverless/workers/handler-functions
- Send requests: https://docs.runpod.io/serverless/endpoints/send-requests
- Endpoint settings: https://docs.runpod.io/serverless/endpoints/endpoint-configurations
- Local testing: https://docs.runpod.io/serverless/development/local-testing

Hunyuan3D 2.1 docs:

- https://github.com/tencent-hunyuan/hunyuan3d-2.1

## Worker Image

The GitHub Actions workflow builds this image for RunPod:

```text
ghcr.io/andrijaradiv/space-tycoon-hunyuan-worker:latest
```

There is also a tiny smoke-test image for validating RunPod endpoint + MCP wiring before the full CUDA/Hunyuan image finishes:

```text
ghcr.io/andrijaradiv/space-tycoon-hunyuan-worker:smoke
```

The worker intentionally lives under `runpod-worker/` so the container context does not include local secrets or generated assets.
