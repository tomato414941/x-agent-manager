#!/usr/bin/env python3
"""Fetch X Post metrics for recently published posts and append to metrics.jsonl.

This script is account-agnostic. It reads tweet IDs from:
  <account>/workspace/state/posts.jsonl
and appends snapshots to:
  <account>/workspace/state/metrics.jsonl

Notes:
- non_public_metrics / organic_metrics require user-context auth and are only
  available for posts created within the last 30 days (per X API docs).
- Never prints secrets.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_SECRETS_ROOT = pathlib.Path.home() / ".secrets" / "x-agent-manager"


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _utc_now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(s: str) -> _dt.datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return _dt.datetime.fromisoformat(s[:-1] + "+00:00")
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _infer_account_root(account_dir: str | None) -> pathlib.Path:
    if account_dir:
        root = pathlib.Path(account_dir).expanduser().resolve()
        if not root.is_dir():
            _die(f"--account-dir not found: {root}")
        if not (root / "workspace").is_dir():
            _die(f"--account-dir missing workspace/: {root}")
        return root

    for candidate in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]:
        if (candidate / "workspace").is_dir():
            return candidate.resolve()

    _die("Could not infer account root. Pass --account-dir or run from accounts/<name>/")


def _normalize_secret_candidates(
    account_dir: pathlib.Path | None,
    secrets_file: str | None,
    secrets_root: pathlib.Path,
) -> list[pathlib.Path]:
    seen: set[pathlib.Path] = set()
    candidates: list[pathlib.Path] = []

    def _append(path: pathlib.Path) -> None:
        if path in seen:
            return
        seen.add(path)
        candidates.append(path)

    env_path = os.environ.get("X_SECRETS_FILE")
    if secrets_file:
        _append(pathlib.Path(secrets_file).expanduser())
    elif env_path:
        _append(pathlib.Path(env_path).expanduser())

    if account_dir is not None:
        _append(secrets_root / account_dir.name)

    if secrets_root.is_file():
        _append(secrets_root)
    else:
        _append(secrets_root / "config")

    return candidates


def _load_secrets_file(
    account_dir: pathlib.Path | None,
    secrets_file: str | None,
    secrets_root: pathlib.Path,
) -> None:
    for candidate in _normalize_secret_candidates(account_dir, secrets_file, secrets_root):
        if not candidate.exists() or not candidate.is_file():
            continue

        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue

            try:
                parts = shlex.split(value)
            except ValueError:
                parts = [value]
            if not parts:
                continue

            env_value = parts[0]
            if env_value in {"", "\"\"", "''"}:
                continue
            os.environ[key] = env_value


def _get_access_token() -> str:
    for key in (
        "X_ACCESS_TOKEN",
        "X_USER_ACCESS_TOKEN",
        "X_BEARER_TOKEN",
        "TWITTER_ACCESS_TOKEN",
        "BEARER_TOKEN",
    ):
        val = os.environ.get(key)
        if val:
            return val
    _die("Missing X access token env var (X_ACCESS_TOKEN recommended).", code=1)


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    if not path.is_file():
        return []
    out: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _latest_fetch_by_tweet(metrics_rows: list[dict]) -> dict[str, _dt.datetime]:
    latest: dict[str, _dt.datetime] = {}
    for row in metrics_rows:
        tid = row.get("tweet_id")
        if not isinstance(tid, str) or not tid:
            continue
        ts = row.get("fetched_at")
        if not isinstance(ts, str):
            continue
        dt = _parse_iso_utc(ts)
        if dt is None:
            continue
        prev = latest.get(tid)
        if prev is None or dt > prev:
            latest[tid] = dt
    return latest


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _get_tweets_lookup(ids: list[str], token: str, tweet_fields: str) -> dict:
    qs = urllib.parse.urlencode({"ids": ",".join(ids), "tweet.fields": tweet_fields})
    url = "https://api.x.com/2/tweets" + "?" + qs
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-dir", help="Account root dir (e.g., accounts/agent-x). Defaults to CWD inference.")
    ap.add_argument("--secrets-root", default=str(DEFAULT_SECRETS_ROOT), help="Secrets root (default: ~/.secrets/x-agent-manager)")
    ap.add_argument("--secrets-file", help="Optional explicit secret file path (export syntax)")
    ap.add_argument("--limit", type=int, default=50, help="How many recent posts to consider (default: 50)")
    ap.add_argument("--min-interval-seconds", type=int, default=900, help="Skip if fetched within this interval (default: 900)")
    args = ap.parse_args()

    account_root = _infer_account_root(args.account_dir)
    secrets_root = pathlib.Path(args.secrets_root).expanduser()
    _load_secrets_file(account_root, args.secrets_file, secrets_root)
    token = _get_access_token()

    posts_path = account_root / "workspace" / "state" / "posts.jsonl"
    metrics_path = account_root / "workspace" / "state" / "metrics.jsonl"
    posts = _read_jsonl(posts_path)
    if not posts:
        print("metrics: no posts found")
        return 0

    ids: list[str] = []
    for row in reversed(posts[-args.limit :]):
        tid = row.get("tweet_id")
        if isinstance(tid, str) and tid:
            ids.append(tid)
    ids = list(dict.fromkeys(ids))  # stable de-dupe

    existing = _read_jsonl(metrics_path)
    latest_by_id = _latest_fetch_by_tweet(existing)
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    min_interval = _dt.timedelta(seconds=max(0, args.min_interval_seconds))
    to_fetch = [
        tid
        for tid in ids
        if (now - latest_by_id.get(tid, _dt.datetime.fromtimestamp(0, tz=_dt.timezone.utc))) >= min_interval
    ]
    if not to_fetch:
        print("metrics: up to date")
        return 0

    tweet_fields_full = "created_at,public_metrics,non_public_metrics,organic_metrics"
    tweet_fields_public = "created_at,public_metrics"

    out_rows: list[dict] = []
    fetched = 0
    errors = 0

    for batch in _chunked(to_fetch, 100):
        try:
            resp = _get_tweets_lookup(batch, token, tweet_fields_full)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            # If we can't access private metrics, fall back to public only.
            if e.code in {401, 403}:
                try:
                    resp = _get_tweets_lookup(batch, token, tweet_fields_public)
                except Exception:
                    errors += len(batch)
                    continue
            else:
                errors += len(batch)
                continue
        except Exception:
            errors += len(batch)
            continue

        data = resp.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                tid = item.get("id")
                if not isinstance(tid, str) or not tid:
                    continue
                out_rows.append(
                    {
                        "fetched_at": _utc_now_iso(),
                        "tweet_id": tid,
                        "created_at": item.get("created_at"),
                        "public_metrics": item.get("public_metrics"),
                        "non_public_metrics": item.get("non_public_metrics"),
                        "organic_metrics": item.get("organic_metrics"),
                    }
                )
                fetched += 1

        # Count per-item errors if present (e.g., deleted tweets)
        resp_errors = resp.get("errors")
        if isinstance(resp_errors, list):
            errors += len(resp_errors)

        # Be gentle with rate limits in tight loops.
        time.sleep(0.2)

    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with metrics_path.open("a", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"metrics: fetched={fetched} errors={errors} wrote={len(out_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

