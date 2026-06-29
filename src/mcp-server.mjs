import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

const SERVER_INFO = {
  name: "space-tycoon-asset-pipeline",
  version: "0.1.0",
};

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_OUTPUT_DIR = path.join(PROJECT_ROOT, "assets/models");
const RUNPOD_API_BASE = "https://api.runpod.ai/v2";

function loadDotEnv() {
  const envPath = path.join(PROJECT_ROOT, ".env");
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex === -1) continue;
    const key = trimmed.slice(0, separatorIndex).trim();
    const value = trimmed.slice(separatorIndex + 1).trim().replace(/^['"]|['"]$/g, "");
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

loadDotEnv();

function jsonRpcResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function jsonRpcError(id, code, message, data) {
  return { jsonrpc: "2.0", id, error: { code, message, data } };
}

function write(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

function safeAssetName(value) {
  return String(value || "generated_asset")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80) || "generated_asset";
}

function textContent(text) {
  return { content: [{ type: "text", text }] };
}

function envStatus() {
  return {
    hasRunpodApiKey: Boolean(process.env.RUNPOD_API_KEY),
    hasRunpodEndpointId: Boolean(process.env.RUNPOD_ENDPOINT_ID),
    defaultOutputDir: DEFAULT_OUTPUT_DIR,
    estimatedGpuHourlyRate: Number(process.env.RUNPOD_GPU_HOURLY_RATE || "1.10"),
    estimatedSecondsPerTexturedModel: Number(process.env.RUNPOD_SECONDS_PER_TEXTURED_MODEL || "140"),
  };
}

async function downloadToFile(url, outputPath, headers = {}) {
  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`Download failed: ${response.status} ${response.statusText}`);
  }
  const buffer = Buffer.from(await response.arrayBuffer());
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  return outputPath;
}

async function callRunpodJob(input, pollSeconds) {
  const apiKey = process.env.RUNPOD_API_KEY;
  const endpointId = process.env.RUNPOD_ENDPOINT_ID;
  if (!apiKey || !endpointId) {
    throw new Error("Missing RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID.");
  }

  const runResponse = await fetch(`${RUNPOD_API_BASE}/${endpointId}/run`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input }),
  });

  const runPayload = await runResponse.json().catch(() => ({}));
  if (!runResponse.ok) {
    throw new Error(`RunPod run request failed: ${runResponse.status} ${JSON.stringify(runPayload)}`);
  }

  const jobId = runPayload.id;
  if (!jobId) {
    return runPayload;
  }

  const deadline = Date.now() + pollSeconds * 1000;
  let lastPayload = runPayload;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const statusResponse = await fetch(`${RUNPOD_API_BASE}/${endpointId}/status/${jobId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const statusPayload = await statusResponse.json().catch(() => ({}));
    if (!statusResponse.ok) {
      throw new Error(`RunPod status request failed: ${statusResponse.status} ${JSON.stringify(statusPayload)}`);
    }
    lastPayload = statusPayload;
    if (["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(statusPayload.status)) {
      return statusPayload;
    }
  }

  return {
    ...lastPayload,
    status: lastPayload.status || "POLL_TIMEOUT",
    message: `Job did not finish within ${pollSeconds}s. Poll later with RunPod job id ${jobId}.`,
  };
}

function resolveOutputFromRunpod(payload) {
  const output = payload?.output || payload;
  if (!output || typeof output !== "object") return {};
  return {
    glbBase64: output.glb_base64 || output.model_base64 || output.file_base64,
    glbUrl: output.glb_url || output.model_url || output.output_url || output.file_url,
    rawOutput: output,
  };
}

const tools = [
  {
    name: "check_config",
    description: "Check whether the local MCP server has RunPod cloud credentials configured.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {},
    },
  },
  {
    name: "estimate_runpod_cost",
    description: "Estimate textured-model batch cost for a RunPod/Hunyuan3D worker.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        models: { type: "number", description: "Number of models to generate." },
        seconds_per_model: { type: "number", description: "Expected warm generation seconds per model." },
        hourly_rate: { type: "number", description: "GPU hourly rate in USD." },
        cold_start_seconds: { type: "number", description: "One-time cold start/load overhead." },
      },
    },
  },
  {
    name: "generate_roblox_asset_from_image",
    description: "Send a local concept image to the RunPod Hunyuan3D worker and save the returned GLB.",
    inputSchema: {
      type: "object",
      required: ["image_path", "asset_name"],
      additionalProperties: false,
      properties: {
        image_path: { type: "string", description: "Absolute path to the source concept image." },
        asset_name: { type: "string", description: "Roblox-friendly asset name." },
        output_dir: { type: "string", description: "Directory for generated GLB files." },
        textured: { type: "boolean", default: true },
        target_polycount: { type: "number", default: 8000 },
        output_format: { type: "string", enum: ["glb", "obj", "zip"], default: "glb" },
        poll_seconds: { type: "number", default: 900 },
        roblox_optimized: { type: "boolean", default: true },
      },
    },
  },
];

async function handleToolCall(name, args = {}) {
  if (name === "check_config") {
    const status = envStatus();
    const missing = [];
    if (!status.hasRunpodApiKey) missing.push("RUNPOD_API_KEY");
    if (!status.hasRunpodEndpointId) missing.push("RUNPOD_ENDPOINT_ID");
    return textContent(JSON.stringify({ ...status, ready: missing.length === 0, missing }, null, 2));
  }

  if (name === "estimate_runpod_cost") {
    const models = Number(args.models || 1);
    const secondsPerModel = Number(args.seconds_per_model || process.env.RUNPOD_SECONDS_PER_TEXTURED_MODEL || 140);
    const hourlyRate = Number(args.hourly_rate || process.env.RUNPOD_GPU_HOURLY_RATE || 1.1);
    const coldStartSeconds = Number(args.cold_start_seconds || 180);
    const billableSeconds = coldStartSeconds + models * secondsPerModel;
    const estimatedUsd = (billableSeconds / 3600) * hourlyRate;
    return textContent(JSON.stringify({
      models,
      billableSeconds,
      hourlyRate,
      estimatedUsd: Number(estimatedUsd.toFixed(4)),
      estimatedUsdPerModel: Number((estimatedUsd / models).toFixed(4)),
      note: "This is an estimate. Actual RunPod billing depends on GPU type, cold starts, retries, and idle timeout.",
    }, null, 2));
  }

  if (name === "generate_roblox_asset_from_image") {
    const imagePath = path.resolve(String(args.image_path));
    if (!fs.existsSync(imagePath)) throw new Error(`Image not found: ${imagePath}`);

    const assetName = safeAssetName(args.asset_name);
    const outputFormat = args.output_format || "glb";
    const outputDir = path.resolve(args.output_dir || DEFAULT_OUTPUT_DIR);
    const outputPath = path.join(outputDir, `${assetName}.${outputFormat === "zip" ? "zip" : "glb"}`);
    const imageBase64 = fs.readFileSync(imagePath).toString("base64");

    const payload = await callRunpodJob({
      image_base64: imageBase64,
      image_filename: path.basename(imagePath),
      asset_name: assetName,
      textured: args.textured !== false,
      target_polycount: Number(args.target_polycount || 8000),
      output_format: outputFormat,
      roblox_optimized: args.roblox_optimized !== false,
    }, Number(args.poll_seconds || 900));

    fs.mkdirSync(outputDir, { recursive: true });
    const { glbBase64, glbUrl, rawOutput } = resolveOutputFromRunpod(payload);

    let savedPath = null;
    if (glbBase64) {
      fs.writeFileSync(outputPath, Buffer.from(glbBase64, "base64"));
      savedPath = outputPath;
    } else if (glbUrl) {
      savedPath = await downloadToFile(glbUrl, outputPath);
    } else {
      const jobPath = path.join(PROJECT_ROOT, "assets/jobs", `${assetName}.json`);
      fs.mkdirSync(path.dirname(jobPath), { recursive: true });
      fs.writeFileSync(jobPath, JSON.stringify(payload, null, 2));
      return textContent(JSON.stringify({
        status: payload.status || "UNKNOWN",
        savedJob: jobPath,
        message: "RunPod did not return a direct GLB/base64 URL yet. Inspect the saved job payload.",
        output: rawOutput,
      }, null, 2));
    }

    return textContent(JSON.stringify({
      status: payload.status || "COMPLETED",
      assetName,
      savedPath,
      sourceImage: imagePath,
      output: rawOutput,
    }, null, 2));
  }

  throw new Error(`Unknown tool: ${name}`);
}

async function handleMessage(message) {
  const { id, method, params } = message;
  try {
    if (method === "initialize") {
      write(jsonRpcResult(id, {
        protocolVersion: params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO,
      }));
      return;
    }

    if (method === "notifications/initialized") return;

    if (method === "tools/list") {
      write(jsonRpcResult(id, { tools }));
      return;
    }

    if (method === "tools/call") {
      const result = await handleToolCall(params?.name, params?.arguments || {});
      write(jsonRpcResult(id, result));
      return;
    }

    write(jsonRpcError(id, -32601, `Method not found: ${method}`));
  } catch (error) {
    write(jsonRpcError(id, -32000, error.message, { stack: error.stack }));
  }
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  if (!line.trim()) return;
  try {
    handleMessage(JSON.parse(line));
  } catch (error) {
    write(jsonRpcError(null, -32700, error.message));
  }
});
