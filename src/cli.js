import { runCycle } from "./cycle.js";
import { ensureConfig, getConfigPath } from "./config.js";
import { ensureState } from "./state_store.js";
import { postNow } from "../skills/x_post_skill.js";
import { authStatus, completeAuth, refreshAuth, revokeAuth, startAuth } from "../skills/x_auth_skill.js";
import { fetchMetrics, syncMetrics } from "../skills/x_metrics_skill.js";
import { enqueuePost, listQueue, publishDue } from "../skills/x_schedule_skill.js";

const ROOT_DIR = process.cwd();

function parseArgs(tokens) {
  const args = { _: [] };

  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i];

    if (token.startsWith("--")) {
      const key = token.slice(2);
      const next = tokens[i + 1];

      if (!next || next.startsWith("--")) {
        args[key] = true;
      } else {
        args[key] = next;
        i += 1;
      }

      continue;
    }

    args._.push(token);
  }

  return args;
}

function assertArg(args, key) {
  const value = args[key];
  if (value === undefined || value === null || value === "") {
    throw new Error(`Missing required option: --${key}`);
  }

  return value;
}

function toJson(payload) {
  return JSON.stringify(payload, null, 2);
}

async function commandInit() {
  await ensureConfig(ROOT_DIR);
  await ensureState(ROOT_DIR);

  console.log(toJson({
    ok: true,
    config_path: getConfigPath(ROOT_DIR)
  }));
}

async function commandRunCycle(args) {
  const result = await runCycle(ROOT_DIR, {
    nowIso: args.now || null,
    publishLimit: args["publish-limit"] || null,
    metricsLimit: args["metrics-limit"] || null
  });

  console.log(toJson(result));
}

async function commandAuth(args) {
  const action = args._[0] || "status";

  if (action === "status") {
    console.log(toJson(await authStatus(ROOT_DIR)));
    return;
  }

  if (action === "start") {
    const started = await startAuth(ROOT_DIR, {
      redirectUri: args["redirect-uri"] || null
    });
    console.log(toJson(started));
    return;
  }

  if (action === "complete") {
    const completed = await completeAuth(ROOT_DIR, {
      code: assertArg(args, "code"),
      state: assertArg(args, "state"),
      redirectUri: args["redirect-uri"] || null
    });
    console.log(toJson(completed));
    return;
  }

  if (action === "refresh") {
    console.log(toJson(await refreshAuth(ROOT_DIR)));
    return;
  }

  if (action === "revoke") {
    console.log(toJson(await revokeAuth(ROOT_DIR)));
    return;
  }

  throw new Error(`Unknown auth action: ${action}`);
}

async function commandPost(args) {
  const action = args._[0] || "now";
  if (action !== "now") {
    throw new Error(`Unknown post action: ${action}`);
  }

  const posted = await postNow(ROOT_DIR, {
    text: assertArg(args, "content"),
    idempotencyKey: args["idempotency-key"] || null
  });

  console.log(toJson(posted));
}

async function commandQueue(args) {
  const action = args._[0] || "list";

  if (action === "add") {
    const created = await enqueuePost(ROOT_DIR, {
      content: assertArg(args, "content"),
      scheduledAt: assertArg(args, "scheduled-at"),
      source: args.source || "agent"
    });
    console.log(toJson(created));
    return;
  }

  if (action === "list") {
    const items = await listQueue(ROOT_DIR, {
      status: args.status || null
    });
    console.log(toJson(items));
    return;
  }

  if (action === "publish-due") {
    const published = await publishDue(ROOT_DIR, {
      nowIso: args.now || null,
      limit: args.limit || null
    });
    console.log(toJson(published));
    return;
  }

  throw new Error(`Unknown queue action: ${action}`);
}

async function commandMetrics(args) {
  const action = args._[0] || "sync";

  if (action === "sync") {
    const synced = await syncMetrics(ROOT_DIR, {
      nowIso: args.now || null,
      limit: args.limit || null
    });

    console.log(toJson(synced));
    return;
  }

  if (action === "fetch") {
    const payload = await fetchMetrics(ROOT_DIR, {
      tweetId: assertArg(args, "tweet-id")
    });
    console.log(toJson(payload));
    return;
  }

  throw new Error(`Unknown metrics action: ${action}`);
}

function printUsage() {
  console.log("Usage: node src/cli.js <command> [subcommand] [options]");
  console.log("Core:");
  console.log("  init");
  console.log("  run-cycle [--now <ISO>] [--publish-limit N] [--metrics-limit N]");
  console.log("Auth:");
  console.log("  auth status");
  console.log("  auth start [--redirect-uri <url>]");
  console.log("  auth complete --code <code> --state <state> [--redirect-uri <url>]");
  console.log("  auth refresh");
  console.log("  auth revoke");
  console.log("Post:");
  console.log("  post now --content <text>");
  console.log("Queue:");
  console.log("  queue add --content <text> --scheduled-at <ISO> [--source agent|manual]");
  console.log("  queue list [--status <status>]");
  console.log("  queue publish-due [--now <ISO>] [--limit N]");
  console.log("Metrics:");
  console.log("  metrics sync [--now <ISO>] [--limit N]");
  console.log("  metrics fetch --tweet-id <id>");
}

async function main() {
  const [command, ...rest] = process.argv.slice(2);

  if (!command || command === "help" || command === "--help") {
    printUsage();
    return;
  }

  const args = parseArgs(rest);

  switch (command) {
    case "init":
      await commandInit();
      return;
    case "run-cycle":
      await commandRunCycle(args);
      return;
    case "auth":
      await commandAuth(args);
      return;
    case "post":
      await commandPost(args);
      return;
    case "queue":
      await commandQueue(args);
      return;
    case "metrics":
      await commandMetrics(args);
      return;
    default:
      throw new Error(`Unknown command: ${command}`);
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
