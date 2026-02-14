import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_CONFIG = {
  runtime: {
    publishLimitPerCycle: 5,
    metricsLimitPerCycle: 20,
    metricsWindowsHours: [24, 72]
  },
  queue: {
    maxRetries: 5
  },
  auth: {
    credentialPath: "workspace/secrets/x_credential.enc.json"
  },
  xApi: {
    mode: "mock",
    clientId: "",
    clientSecret: "",
    authBaseUrl: "https://x.com/i/oauth2/authorize",
    tokenUrl: "https://api.x.com/2/oauth2/token",
    apiBaseUrl: "https://api.x.com/2",
    redirectUri: "http://127.0.0.1:8787/callback",
    scopes: ["tweet.read", "tweet.write", "users.read", "offline.access"],
    timeoutMs: 10000
  }
};

function configPath(rootDir) {
  return path.resolve(rootDir, "config", "config.json");
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function deepMerge(base, override) {
  if (!isObject(base)) {
    return isObject(override) ? { ...override } : override;
  }

  const result = { ...base };
  for (const [key, value] of Object.entries(override || {})) {
    if (isObject(value) && isObject(base[key])) {
      result[key] = deepMerge(base[key], value);
      continue;
    }

    result[key] = value;
  }

  return result;
}

async function ensureConfigFile(filePath, content) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });

  try {
    await fs.writeFile(filePath, `${JSON.stringify(content, null, 2)}\n`, { flag: "wx" });
  } catch (error) {
    if (error.code !== "EEXIST") {
      throw error;
    }
  }
}

async function readJsonFile(filePath, fallback) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw);
  } catch (error) {
    if (error.code === "ENOENT") {
      return fallback;
    }

    throw error;
  }
}

export async function ensureConfig(rootDir) {
  await ensureConfigFile(configPath(rootDir), DEFAULT_CONFIG);
}

export async function loadConfig(rootDir) {
  await ensureConfig(rootDir);
  const loaded = await readJsonFile(configPath(rootDir), DEFAULT_CONFIG);
  return deepMerge(DEFAULT_CONFIG, loaded || {});
}

export function resolveRuntimePath(rootDir, relativePath) {
  return path.resolve(rootDir, String(relativePath || ""));
}

export function getConfigPath(rootDir) {
  return configPath(rootDir);
}
