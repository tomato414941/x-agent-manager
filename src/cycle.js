import fs from "node:fs/promises";
import path from "node:path";
import { loadConfig } from "./config.js";
import { appendState, ensureState } from "./state_store.js";
import { createId, nowIso } from "./util.js";
import { publishDue } from "../skills/x_schedule_skill.js";
import { syncMetrics } from "../skills/x_metrics_skill.js";

async function writeCycleSummary(rootDir, runRecord) {
  const memoryDir = path.resolve(rootDir, "workspace", "memory");
  await fs.mkdir(memoryDir, { recursive: true });

  const lines = [
    `# Agent-X Cycle Summary`,
    `- run_id: ${runRecord.id}`,
    `- started_at: ${runRecord.started_at}`,
    `- finished_at: ${runRecord.finished_at}`,
    `- status: ${runRecord.status}`,
    `- queued_count: ${runRecord.queued_count}`,
    `- published_count: ${runRecord.published_count}`,
    `- metrics_fetched_count: ${runRecord.metrics_fetched_count}`,
    `- metrics_created_count: ${runRecord.metrics_created_count}`
  ];

  if (runRecord.errors.length) {
    lines.push("- errors:");
    for (const error of runRecord.errors) {
      lines.push(`  - ${error}`);
    }
  }

  lines.push("", "Use this summary as context for the next agent session.");

  await fs.writeFile(path.resolve(memoryDir, "latest_summary.md"), `${lines.join("\n")}\n`, "utf8");
}

export async function runCycle(rootDir, options = {}) {
  await ensureState(rootDir);
  const config = await loadConfig(rootDir);

  const startedAt = nowIso();
  const errors = [];

  let publishResult = {
    published: 0,
    failed: 0,
    skipped: 0,
    items: []
  };

  let metricsResult = {
    created: 0,
    fetched_posts: 0,
    items: []
  };

  try {
    publishResult = await publishDue(rootDir, {
      nowIso: options.nowIso,
      limit: options.publishLimit || config.runtime?.publishLimitPerCycle
    });
  } catch (error) {
    errors.push(`publish_due: ${String(error.message || error)}`);
  }

  try {
    metricsResult = await syncMetrics(rootDir, {
      nowIso: options.nowIso,
      limit: options.metricsLimit || config.runtime?.metricsLimitPerCycle
    });
  } catch (error) {
    errors.push(`metrics_sync: ${String(error.message || error)}`);
  }

  const finishedAt = nowIso();
  const runRecord = {
    id: createId("run"),
    started_at: startedAt,
    finished_at: finishedAt,
    status: errors.length ? "partial" : "ok",
    queued_count: publishResult.items.length,
    published_count: publishResult.published,
    metrics_fetched_count: metricsResult.fetched_posts,
    metrics_created_count: metricsResult.created,
    errors
  };

  await appendState(rootDir, "runs", runRecord);
  await writeCycleSummary(rootDir, runRecord);

  return runRecord;
}
