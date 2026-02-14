import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { readJsonl, runCliJson } from "./helpers.js";

test("run-cycle publishes due posts and writes run summary", () => {
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-x-cycle-"));

  try {
    runCliJson(["init"], workDir);
    runCliJson(["queue", "add", "--content", "run-cycle対象", "--scheduled-at", "2026-02-10T09:00:00.000Z"], workDir);
    runCliJson(["queue", "add", "--content", "未来投稿", "--scheduled-at", "2026-02-20T09:00:00.000Z"], workDir);

    const run = runCliJson(["run-cycle", "--now", "2026-02-10T10:00:00.000Z"], workDir);
    assert.equal(run.status, "ok");
    assert.equal(run.published_count, 1);

    const runsPath = path.join(workDir, "workspace", "state", "runs.jsonl");
    const runs = readJsonl(runsPath);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].published_count, 1);

    const summaryPath = path.join(workDir, "workspace", "memory", "latest_summary.md");
    assert.equal(fs.existsSync(summaryPath), true);
    const summary = fs.readFileSync(summaryPath, "utf8");
    assert.equal(summary.includes("published_count: 1"), true);
  } finally {
    fs.rmSync(workDir, { recursive: true, force: true });
  }
});
