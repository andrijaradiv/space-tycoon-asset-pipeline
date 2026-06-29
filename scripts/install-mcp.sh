#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_PATH="$ROOT_DIR/src/mcp-server.mjs"

codex mcp remove Space3D_Assets >/dev/null 2>&1 || true
codex mcp add Space3D_Assets -- node "$SERVER_PATH"

echo "Installed Codex MCP server: Space3D_Assets"
codex mcp get Space3D_Assets
