import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serverPath = path.resolve(__dirname, "../src/mcp-server.mjs");
const child = spawn(process.execPath, [serverPath], {
  stdio: ["pipe", "pipe", "pipe"],
});

let nextId = 1;
const pending = new Map();

child.stdout.setEncoding("utf8");
child.stderr.pipe(process.stderr);

child.stdout.on("data", (chunk) => {
  for (const line of chunk.split("\n")) {
    if (!line.trim()) continue;
    const message = JSON.parse(line);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  }
});

function call(method, params = {}) {
  const id = nextId++;
  child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return new Promise((resolve) => pending.set(id, resolve));
}

const init = await call("initialize", {
  protocolVersion: "2024-11-05",
  capabilities: {},
  clientInfo: { name: "space-asset-mcp-test", version: "0.1.0" },
});
if (init.error) throw new Error(JSON.stringify(init.error));

child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }) + "\n");

const tools = await call("tools/list");
if (tools.error) throw new Error(JSON.stringify(tools.error));

const config = await call("tools/call", {
  name: "check_config",
  arguments: {},
});
if (config.error) throw new Error(JSON.stringify(config.error));

console.log(JSON.stringify({ ok: true, tools: tools.result.tools.map((tool) => tool.name), config: config.result }, null, 2));
child.kill();
