import { loadConfig } from "../src/config.js";
import { appendState, ensureState, readState } from "../src/state_store.js";
import { createId, nowIso, parseIsoDate, toPositiveInt } from "../src/util.js";
import { createXGateway } from "./x_gateway.js";

function normalizeNow(value) {
  if (!value) {
    return new Date();
  }

  return parseIsoDate(value, "now");
}

export async function fetchMetrics(rootDir, input = {}) {
  const tweetId = String(input.tweetId || "").trim();
  if (!tweetId) {
    throw new Error("tweet_id is required");
  }

  const gateway = await createXGateway(rootDir);
  return gateway.fetchPostMetrics(tweetId);
}

export async function syncMetrics(rootDir, options = {}) {
  await ensureState(rootDir);

  const config = await loadConfig(rootDir);
  const windows = Array.isArray(config.runtime?.metricsWindowsHours) && config.runtime.metricsWindowsHours.length
    ? config.runtime.metricsWindowsHours
    : [24, 72];

  const now = normalizeNow(options.nowIso);
  const limit = toPositiveInt(options.limit, Number(config.runtime?.metricsLimitPerCycle || 20));

  const posts = await readState(rootDir, "posts");
  const metrics = await readState(rootDir, "metrics");

  const existing = new Set(metrics.map((item) => `${item.tweet_id}:${item.window}`));
  const gateway = await createXGateway(rootDir);

  const targetPosts = posts
    .filter((post) => post.tweet_id && post.posted_at)
    .sort((a, b) => String(a.posted_at).localeCompare(String(b.posted_at)))
    .slice(0, limit);

  let created = 0;
  let fetchedPosts = 0;
  const items = [];

  for (const post of targetPosts) {
    const ageHours = (now.getTime() - new Date(post.posted_at).getTime()) / (1000 * 60 * 60);
    const dueWindows = windows
      .map((windowHours) => Number(windowHours))
      .filter((windowHours) => windowHours > 0)
      .map((windowHours) => `${windowHours}h`)
      .filter((windowLabel) => {
        const hours = Number(windowLabel.replace("h", ""));
        return ageHours >= hours && !existing.has(`${post.tweet_id}:${windowLabel}`);
      });

    if (!dueWindows.length) {
      continue;
    }

    const payload = await gateway.fetchPostMetrics(post.tweet_id);
    fetchedPosts += 1;

    for (const window of dueWindows) {
      const record = {
        id: createId("metric"),
        tweet_id: post.tweet_id,
        window,
        impressions: Number(payload.impressions || 0),
        likes: Number(payload.likes || 0),
        replies: Number(payload.replies || 0),
        reposts: Number(payload.reposts || 0),
        bookmarks: Number(payload.bookmarks || 0),
        fetched_at: payload.fetched_at || nowIso()
      };

      await appendState(rootDir, "metrics", record);
      existing.add(`${record.tweet_id}:${record.window}`);
      created += 1;
      items.push(record);
    }
  }

  return {
    created,
    fetched_posts: fetchedPosts,
    items
  };
}
