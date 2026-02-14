import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { authStatus, completeAuth, refreshAuth, revokeAuth, startAuth } from "../skills/x_auth_skill.js";

function createTokenServer() {
  let refreshCount = 0;

  const server = http.createServer(async (req, res) => {
    if (req.method !== "POST" || req.url !== "/token") {
      res.writeHead(404);
      res.end();
      return;
    }

    let body = "";
    for await (const chunk of req) {
      body += String(chunk);
    }

    const params = new URLSearchParams(body);
    const grantType = params.get("grant_type");

    if (grantType === "authorization_code") {
      res.writeHead(200, {
        "content-type": "application/json"
      });
      res.end(
        JSON.stringify({
          token_type: "bearer",
          access_token: "access_auth_code",
          refresh_token: "refresh_token_1",
          expires_in: 1,
          scope: "tweet.read tweet.write users.read offline.access"
        })
      );
      return;
    }

    if (grantType === "refresh_token") {
      refreshCount += 1;
      res.writeHead(200, {
        "content-type": "application/json"
      });
      res.end(
        JSON.stringify({
          token_type: "bearer",
          access_token: `access_refresh_${refreshCount}`,
          refresh_token: "refresh_token_1",
          expires_in: 3600,
          scope: "tweet.read tweet.write users.read offline.access"
        })
      );
      return;
    }

    res.writeHead(400, {
      "content-type": "application/json"
    });
    res.end(JSON.stringify({ error: "unsupported_grant" }));
  });

  return {
    server,
    getRefreshCount: () => refreshCount
  };
}

test("auth start/complete/status/refresh/revoke workflow", async () => {
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-x-auth-"));
  const previousKey = process.env.AGENT_X_SECRETS_KEY;
  process.env.AGENT_X_SECRETS_KEY = "unit-test-secret";

  const { server, getRefreshCount } = createTokenServer();

  try {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const tokenPort = server.address().port;

    const configDir = path.join(workDir, "config");
    fs.mkdirSync(configDir, { recursive: true });
    fs.writeFileSync(
      path.join(configDir, "config.json"),
      `${JSON.stringify(
        {
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
            mode: "live",
            clientId: "test-client-id",
            tokenUrl: `http://127.0.0.1:${tokenPort}/token`,
            authBaseUrl: "https://example.com/oauth/authorize",
            redirectUri: "http://127.0.0.1:8787/callback",
            scopes: ["tweet.read", "tweet.write", "users.read", "offline.access"],
            timeoutMs: 10000
          }
        },
        null,
        2
      )}\n`,
      "utf8"
    );

    const started = await startAuth(workDir);
    assert.equal(Boolean(started.state), true);
    assert.equal(started.authorization_url.includes("test-client-id"), true);

    const completed = await completeAuth(workDir, {
      code: "dummy",
      state: started.state
    });
    assert.equal(completed.connected, true);

    const status = await authStatus(workDir);
    assert.equal(status.connected, true);
    assert.equal(status.refreshable, true);

    const refreshed = await refreshAuth(workDir);
    assert.equal(refreshed.connected, true);
    assert.equal(getRefreshCount() > 0, true);

    const revoked = await revokeAuth(workDir);
    assert.equal(revoked.connected, false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    if (previousKey === undefined) {
      delete process.env.AGENT_X_SECRETS_KEY;
    } else {
      process.env.AGENT_X_SECRETS_KEY = previousKey;
    }
    fs.rmSync(workDir, { recursive: true, force: true });
  }
});
