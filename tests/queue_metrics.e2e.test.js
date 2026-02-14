import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { readJsonl, runCliJson } from "./helpers.js";

test("queue publish-due posts in mock mode and avoids duplicate content", () => {
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-x-min-"));

  try {
    runCliJson(["init"], workDir);

    runCliJson(
      ["queue", "add", "--content", "同じ内容の投稿", "--scheduled-at", "2026-02-10T09:00:00.000Z", "--source", "agent"],
      workDir
    );
    runCliJson(
      ["queue", "add", "--content", "同じ内容の投稿", "--scheduled-at", "2026-02-10T09:01:00.000Z", "--source", "agent"],
      workDir
    );

    const published = runCliJson(["queue", "publish-due", "--now", "2026-02-10T10:00:00.000Z", "--limit", "10"], workDir);
    assert.equal(published.published, 1);
    assert.equal(published.skipped, 1);

    const queuePath = path.join(workDir, "workspace", "state", "queue.jsonl");
    const queue = readJsonl(queuePath);
    assert.equal(queue.length, 2);
    assert.equal(queue.some((item) => item.status === "published"), true);
    assert.equal(queue.some((item) => item.status === "skipped_duplicate"), true);

    const postsPath = path.join(workDir, "workspace", "state", "posts.jsonl");
    const posts = readJsonl(postsPath);
    assert.equal(posts.length, 1);
    assert.equal(posts[0].tweet_id.startsWith("mock_"), true);
  } finally {
    fs.rmSync(workDir, { recursive: true, force: true });
  }
});

test("metrics sync stores 24h and 72h windows", () => {
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-x-min-"));

  try {
    runCliJson(["init"], workDir);
    runCliJson(["queue", "add", "--content", "計測テスト投稿", "--scheduled-at", "2026-02-10T09:00:00.000Z"], workDir);
    runCliJson(["queue", "publish-due", "--now", "2026-02-10T09:10:00.000Z"], workDir);

    const synced = runCliJson(["metrics", "sync", "--now", "2026-02-14T09:10:00.000Z"], workDir);
    assert.equal(synced.created >= 2, true);

    const metricsPath = path.join(workDir, "workspace", "state", "metrics.jsonl");
    const metrics = readJsonl(metricsPath);
    assert.equal(metrics.some((item) => item.window === "24h"), true);
    assert.equal(metrics.some((item) => item.window === "72h"), true);
  } finally {
    fs.rmSync(workDir, { recursive: true, force: true });
  }
});
