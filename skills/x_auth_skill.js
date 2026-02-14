import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { loadConfig, resolveRuntimePath } from "../src/config.js";
import { appendState, ensureState, readState } from "../src/state_store.js";
import { decryptObject, encryptObject } from "../src/secrets_crypto.js";
import { createId, nowIso } from "../src/util.js";

const STATE_TTL_MS = 10 * 60 * 1000;

function toBase64Url(buffer) {
  return Buffer.from(buffer)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function createCodeVerifier() {
  return toBase64Url(crypto.randomBytes(48));
}

function createCodeChallenge(codeVerifier) {
  const digest = crypto.createHash("sha256").update(codeVerifier).digest();
  return toBase64Url(digest);
}

function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  return fetch(url, {
    ...options,
    signal: controller.signal
  }).finally(() => {
    clearTimeout(timeout);
  });
}

function resolveClientId(config) {
  const clientId = config.xApi?.clientId || process.env.X_CLIENT_ID || "";
  if (!clientId) {
    throw new Error("xApi.clientId is required (or X_CLIENT_ID env)");
  }

  return clientId;
}

function resolveClientSecret(config) {
  return config.xApi?.clientSecret || process.env.X_CLIENT_SECRET || "";
}

function resolveCredentialPath(rootDir, config) {
  return resolveRuntimePath(rootDir, config.auth?.credentialPath || "workspace/secrets/x_credential.enc.json");
}

async function loadCredential(rootDir, config) {
  const filePath = resolveCredentialPath(rootDir, config);

  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw);

    if (parsed?.version === 1 && parsed?.ciphertext) {
      return decryptObject(parsed);
    }

    return parsed;
  } catch (error) {
    if (error.code === "ENOENT") {
      return null;
    }

    throw error;
  }
}

async function saveCredential(rootDir, config, payload) {
  const filePath = resolveCredentialPath(rootDir, config);
  await fs.mkdir(path.dirname(filePath), { recursive: true });

  const encrypted = encryptObject(payload);
  await fs.writeFile(filePath, `${JSON.stringify(encrypted, null, 2)}\n`, "utf8");
}

async function deleteCredential(rootDir, config) {
  const filePath = resolveCredentialPath(rootDir, config);

  try {
    await fs.unlink(filePath);
  } catch (error) {
    if (error.code !== "ENOENT") {
      throw error;
    }
  }
}

async function exchangeToken(config, params) {
  const timeoutMs = Number(config.xApi?.timeoutMs || 10000);
  const clientId = resolveClientId(config);
  const clientSecret = resolveClientSecret(config);

  const body = new URLSearchParams(params);
  const headers = {
    "Content-Type": "application/x-www-form-urlencoded"
  };

  if (clientSecret) {
    const basic = Buffer.from(`${clientId}:${clientSecret}`, "utf8").toString("base64");
    headers.Authorization = `Basic ${basic}`;
  }

  const response = await fetchWithTimeout(
    config.xApi?.tokenUrl || "https://api.x.com/2/oauth2/token",
    {
      method: "POST",
      headers,
      body: body.toString()
    },
    timeoutMs
  );

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`X token exchange failed: ${response.status} ${JSON.stringify(data)}`);
  }

  return data;
}

function calculateExpiry(expiresInSec, fallbackSec = 7200) {
  const seconds = Number.isFinite(Number(expiresInSec)) ? Number(expiresInSec) : fallbackSec;
  return new Date(Date.now() + Math.max(60, seconds) * 1000).toISOString();
}

async function appendAuthEvent(rootDir, eventType, status, metadata = {}) {
  await appendState(rootDir, "authEvents", {
    id: createId("auth"),
    event_type: eventType,
    status,
    metadata,
    created_at: nowIso()
  });
}

function resolveOAuthConfig(config, overrideRedirectUri) {
  const xApi = config.xApi || {};
  const clientId = resolveClientId(config);

  return {
    clientId,
    authBaseUrl: xApi.authBaseUrl || "https://x.com/i/oauth2/authorize",
    tokenUrl: xApi.tokenUrl || "https://api.x.com/2/oauth2/token",
    redirectUri: overrideRedirectUri || xApi.redirectUri || "http://127.0.0.1:8787/callback",
    scopes: Array.isArray(xApi.scopes) && xApi.scopes.length ? xApi.scopes : ["tweet.read", "tweet.write", "users.read", "offline.access"]
  };
}

function findPendingStart(events, state) {
  const completedState = new Set(
    events
      .filter((event) => event.event_type === "oauth_complete" && event.status === "ok" && event.metadata?.state)
      .map((event) => event.metadata.state)
  );

  const candidates = events
    .filter((event) => event.event_type === "oauth_start" && event.status === "pending" && event.metadata?.state === state)
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));

  const target = candidates[0] || null;
  if (!target) {
    return null;
  }

  if (completedState.has(state)) {
    return null;
  }

  return target;
}

export async function startAuth(rootDir, options = {}) {
  await ensureState(rootDir);
  const config = await loadConfig(rootDir);
  const oauth = resolveOAuthConfig(config, options.redirectUri);

  const state = toBase64Url(crypto.randomBytes(24));
  const codeVerifier = createCodeVerifier();
  const codeChallenge = createCodeChallenge(codeVerifier);
  const expiresAt = new Date(Date.now() + STATE_TTL_MS).toISOString();

  const query = new URLSearchParams({
    response_type: "code",
    client_id: oauth.clientId,
    redirect_uri: oauth.redirectUri,
    scope: oauth.scopes.join(" "),
    state,
    code_challenge: codeChallenge,
    code_challenge_method: "S256"
  });

  const authorizationUrl = `${oauth.authBaseUrl}?${query.toString()}`;

  await appendAuthEvent(rootDir, "oauth_start", "pending", {
    state,
    code_verifier: codeVerifier,
    redirect_uri: oauth.redirectUri,
    scope: oauth.scopes,
    expires_at: expiresAt
  });

  return {
    connected: false,
    state,
    redirect_uri: oauth.redirectUri,
    authorization_url: authorizationUrl,
    expires_at: expiresAt
  };
}

export async function completeAuth(rootDir, options = {}) {
  await ensureState(rootDir);
  const code = String(options.code || "");
  const state = String(options.state || "");

  if (!code) {
    throw new Error("code is required");
  }

  if (!state) {
    throw new Error("state is required");
  }

  const config = await loadConfig(rootDir);
  const oauth = resolveOAuthConfig(config, options.redirectUri);
  const events = await readState(rootDir, "authEvents");
  const pending = findPendingStart(events, state);

  if (!pending) {
    throw new Error("No valid pending OAuth state found");
  }

  if (pending.metadata?.expires_at && new Date(pending.metadata.expires_at).getTime() < Date.now()) {
    throw new Error("OAuth state expired. Start auth again.");
  }

  const token = await exchangeToken(config, {
    grant_type: "authorization_code",
    code,
    redirect_uri: pending.metadata?.redirect_uri || oauth.redirectUri,
    client_id: oauth.clientId,
    code_verifier: pending.metadata?.code_verifier || ""
  });

  const credential = {
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    token_type: token.token_type || "bearer",
    scope: token.scope || oauth.scopes.join(" "),
    expires_at: calculateExpiry(token.expires_in),
    obtained_at: nowIso()
  };

  await saveCredential(rootDir, config, credential);
  await appendAuthEvent(rootDir, "oauth_complete", "ok", {
    state,
    expires_at: credential.expires_at,
    scope: credential.scope
  });

  return {
    connected: true,
    expires_at: credential.expires_at,
    scope: credential.scope
  };
}

export async function authStatus(rootDir) {
  await ensureState(rootDir);
  const config = await loadConfig(rootDir);
  const credential = await loadCredential(rootDir, config);

  if (!credential) {
    return {
      connected: false,
      refreshable: false,
      reason: "credential_not_found"
    };
  }

  const expiresAt = credential.expires_at || null;
  const expiresMs = expiresAt ? new Date(expiresAt).getTime() : 0;
  const expired = expiresAt ? expiresMs <= Date.now() : true;

  return {
    connected: true,
    refreshable: Boolean(credential.refresh_token),
    expired,
    expires_at: expiresAt,
    scope: credential.scope || null,
    credential_path: resolveCredentialPath(rootDir, config)
  };
}

export async function refreshAuth(rootDir, reason = "manual") {
  await ensureState(rootDir);
  const config = await loadConfig(rootDir);
  const oauth = resolveOAuthConfig(config);
  const credential = await loadCredential(rootDir, config);

  if (!credential?.refresh_token) {
    throw new Error("Refresh token not found. Reconnect OAuth.");
  }

  const token = await exchangeToken(config, {
    grant_type: "refresh_token",
    refresh_token: credential.refresh_token,
    client_id: oauth.clientId
  });

  const next = {
    ...credential,
    access_token: token.access_token,
    refresh_token: token.refresh_token || credential.refresh_token,
    token_type: token.token_type || credential.token_type || "bearer",
    scope: token.scope || credential.scope || oauth.scopes.join(" "),
    expires_at: calculateExpiry(token.expires_in),
    refreshed_at: nowIso()
  };

  await saveCredential(rootDir, config, next);
  await appendAuthEvent(rootDir, "oauth_refresh", "ok", {
    reason,
    expires_at: next.expires_at
  });

  return {
    connected: true,
    expires_at: next.expires_at,
    scope: next.scope
  };
}

export async function revokeAuth(rootDir) {
  await ensureState(rootDir);
  const config = await loadConfig(rootDir);
  await deleteCredential(rootDir, config);
  await appendAuthEvent(rootDir, "oauth_revoke", "ok", {});

  return {
    connected: false
  };
}

export async function ensureAccessToken(rootDir, minTtlSec = 120) {
  const config = await loadConfig(rootDir);
  const credential = await loadCredential(rootDir, config);
  if (!credential?.access_token) {
    throw new Error("X credential not connected. Run auth start/complete.");
  }

  const expiresAt = credential.expires_at ? new Date(credential.expires_at).getTime() : 0;
  const threshold = Date.now() + Number(minTtlSec) * 1000;

  if (!expiresAt || expiresAt <= threshold) {
    const refreshed = await refreshAuth(rootDir, "expiring");
    const latest = await loadCredential(rootDir, config);
    if (!latest?.access_token) {
      throw new Error("Failed to refresh access token");
    }

    return {
      accessToken: latest.access_token,
      expiresAt: refreshed.expires_at
    };
  }

  return {
    accessToken: credential.access_token,
    expiresAt: credential.expires_at || null
  };
}
