import { loadConfig } from "../src/config.js";
import { appendState, ensureState, readState, writeState } from "../src/state_store.js";
import { createId, nowIso, parseIsoDate, sha256Hex, toPositiveInt } from "../src/util.js";
import { postNow } from "./x_post_skill.js";

function contentHash(text) {
  return sha256Hex(String(text || "").trim());
}

function normalizeNow(value) {
  if (!value) {
    return new Date();
  }

  return parseIsoDate(value, "now");
}

export async function enqueuePost(rootDir, input = {}) {
  await ensureState(rootDir);

  const content = String(input.content || "").trim();
  if (!content) {
    throw new Error("content is required");
  }

  if (content.length > 280) {
    throw new Error("content must be 280 characters or fewer");
  }

  const scheduledAtDate = parseIsoDate(input.scheduledAt, "scheduled_at");

  const record = {
    id: createId("schedule"),
    content,
    content_hash: contentHash(content),
    scheduled_at: scheduledAtDate.toISOString(),
    status: "queued",
    retries: 0,
    created_at: nowIso(),
    updated_at: nowIso(),
    source: String(input.source || "agent")
  };

  await appendState(rootDir, "queue", record);

  return {
    schedule_id: record.id,
    status: record.status,
    scheduled_at: record.scheduled_at
  };
}

export async function listQueue(rootDir, options = {}) {
  await ensureState(rootDir);

  const items = await readState(rootDir, "queue");
  const status = options.status ? String(options.status) : null;

  const filtered = status ? items.filter((item) => item.status === status) : items;
  return filtered.sort((a, b) => String(a.scheduled_at).localeCompare(String(b.scheduled_at)));
}

export async function publishDue(rootDir, options = {}) {
  await ensureState(rootDir);

  const config = await loadConfig(rootDir);
  const maxRetries = Math.max(0, Number(config.queue?.maxRetries || 5));
  const now = normalizeNow(options.nowIso);
  const limit = toPositiveInt(options.limit, Number(config.runtime?.publishLimitPerCycle || 5));

  const queue = await readState(rootDir, "queue");
  const posts = await readState(rootDir, "posts");

  const byContentHash = new Set(posts.map((post) => post.content_hash));

  const dueIndexes = [];
  for (let i = 0; i < queue.length; i += 1) {
    const item = queue[i];
    const due = new Date(item.scheduled_at).getTime() <= now.getTime();
    const retryable = item.status === "queued" || (item.status === "publish_failed" && Number(item.retries || 0) < maxRetries);

    if (due && retryable) {
      dueIndexes.push(i);
    }
  }

  dueIndexes.sort((a, b) => String(queue[a].scheduled_at).localeCompare(String(queue[b].scheduled_at)));

  let published = 0;
  let failed = 0;
  let skipped = 0;
  const items = [];

  for (const index of dueIndexes.slice(0, limit)) {
    const item = queue[index];
    const hash = item.content_hash || contentHash(item.content);

    if (byContentHash.has(hash)) {
      skipped += 1;
      queue[index] = {
        ...item,
        status: "skipped_duplicate",
        updated_at: nowIso()
      };
      items.push({
        schedule_id: item.id,
        status: "skipped_duplicate"
      });
      continue;
    }

    try {
      const posted = await postNow(rootDir, {
        text: item.content,
        idempotencyKey: item.id
      });
      const postedAt = options.nowIso ? now.toISOString() : posted.posted_at;

      const postRecord = {
        id: createId("post"),
        tweet_id: posted.tweet_id,
        content: item.content,
        content_hash: hash,
        source_schedule_id: item.id,
        posted_at: postedAt
      };

      byContentHash.add(hash);
      posts.push(postRecord);

      queue[index] = {
        ...item,
        content_hash: hash,
        status: "published",
        tweet_id: posted.tweet_id,
        posted_at: postedAt,
        last_error: null,
        updated_at: nowIso()
      };

      published += 1;
      items.push({
        schedule_id: item.id,
        status: "published",
        tweet_id: posted.tweet_id
      });
    } catch (error) {
      queue[index] = {
        ...item,
        content_hash: hash,
        status: "publish_failed",
        retries: Number(item.retries || 0) + 1,
        last_error: String(error.message || error),
        updated_at: nowIso()
      };

      failed += 1;
      items.push({
        schedule_id: item.id,
        status: "publish_failed",
        error: String(error.message || error)
      });
    }
  }

  await writeState(rootDir, "queue", queue);
  await writeState(rootDir, "posts", posts);

  return {
    published,
    failed,
    skipped,
    items
  };
}
