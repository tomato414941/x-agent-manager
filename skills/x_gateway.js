import { loadConfig } from "../src/config.js";
import { nowIso } from "../src/util.js";
import { ensureAccessToken, refreshAuth } from "./x_auth_skill.js";

function hashString(value) {
  let hash = 0;
  const text = String(value || "");
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
  }
  return hash;
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

function createMockGateway() {
  return {
    async publishPost({ text }) {
      const hash = hashString(`${text}:${Date.now()}`);
      return {
        tweet_id: `mock_${hash.toString(36)}`,
        posted_at: nowIso()
      };
    },

    async fetchPostMetrics(tweetId) {
      const hash = hashString(tweetId);
      const impressions = 1200 + (hash % 6000);
      const engagements = Math.max(40, Math.floor(impressions * (0.03 + (hash % 25) / 1000)));
      const reposts = Math.max(3, Math.floor(engagements * 0.14));
      const replies = Math.max(2, Math.floor(engagements * 0.09));
      const likes = Math.max(10, Math.floor(engagements * 0.53));
      const bookmarks = Math.max(5, Math.floor(engagements * 0.24));

      return {
        impressions,
        likes,
        replies,
        reposts,
        bookmarks,
        fetched_at: nowIso()
      };
    }
  };
}

function createLiveGateway(rootDir, config) {
  const apiBaseUrl = config.xApi?.apiBaseUrl || "https://api.x.com/2";
  const timeoutMs = Number(config.xApi?.timeoutMs || 10000);

  async function requestWithToken(operation, buildRequest, attempt = 1) {
    const token = await ensureAccessToken(rootDir, 120);
    const request = buildRequest(token.accessToken);

    const response = await fetchWithTimeout(request.url, request.options, timeoutMs);
    if (response.status === 401 && attempt === 1) {
      await refreshAuth(rootDir, `api_${operation}_unauthorized`);
      return requestWithToken(operation, buildRequest, attempt + 1);
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(`X API ${operation} failed: ${response.status} ${JSON.stringify(data)}`);
    }

    return data;
  }

  return {
    async publishPost({ text }) {
      const data = await requestWithToken("publish", (accessToken) => ({
        url: `${apiBaseUrl}/tweets`,
        options: {
          method: "POST",
          headers: {
            Authorization: `Bearer ${accessToken}`,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ text })
        }
      }));

      return {
        tweet_id: String(data?.data?.id || ""),
        posted_at: nowIso()
      };
    },

    async fetchPostMetrics(tweetId) {
      const query = new URLSearchParams({
        "tweet.fields": "public_metrics"
      });

      const data = await requestWithToken("metrics", (accessToken) => ({
        url: `${apiBaseUrl}/tweets/${tweetId}?${query.toString()}`,
        options: {
          headers: {
            Authorization: `Bearer ${accessToken}`
          }
        }
      }));

      const metrics = data?.data?.public_metrics || {};
      return {
        impressions: Number(metrics.impression_count || 0),
        likes: Number(metrics.like_count || 0),
        replies: Number(metrics.reply_count || 0),
        reposts: Number(metrics.retweet_count || 0),
        bookmarks: Number(metrics.bookmark_count || 0),
        fetched_at: nowIso()
      };
    }
  };
}

export async function createXGateway(rootDir) {
  const config = await loadConfig(rootDir);
  const mode = String(config.xApi?.mode || "mock").toLowerCase();

  if (mode === "live" || mode === "x_api") {
    return createLiveGateway(rootDir, config);
  }

  return createMockGateway();
}
