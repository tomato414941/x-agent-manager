#!/usr/bin/env python3
"""Summarize recent post performance into workspace/memory/performance.md.

This script is account-agnostic and reads:
  <account>/workspace/state/posts.jsonl
  <account>/workspace/state/metrics.jsonl
and writes:
  <account>/workspace/memory/performance.md

Notes:
- impression_count is taken from organic_metrics or non_public_metrics when present.
- If private impression metrics are unavailable, the summary still reports public metrics.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys


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


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists() or not path.is_file():
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


def _get_int(d: object, key: str) -> int | None:
    if not isinstance(d, dict):
        return None
    v = d.get(key)
    return v if isinstance(v, int) else None


def _impressions(row: dict) -> int | None:
    organic = row.get("organic_metrics")
    val = _get_int(organic, "impression_count")
    if isinstance(val, int):
        return val
    non_public = row.get("non_public_metrics")
    val = _get_int(non_public, "impression_count")
    if isinstance(val, int):
        return val
    return None


def _public_metric(row: dict, key: str) -> int:
    public = row.get("public_metrics")
    return _get_int(public, key) or 0


def _best_metrics_by_tweet(metrics_rows: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for row in metrics_rows:
        tid = row.get("tweet_id")
        if not isinstance(tid, str) or not tid:
            continue

        prev = best.get(tid)
        if prev is None:
            best[tid] = row
            continue

        imp = _impressions(row)
        prev_imp = _impressions(prev)
        if imp is not None and (prev_imp is None or imp > prev_imp):
            best[tid] = row
            continue

        # If no private impressions, keep the latest fetched_at snapshot.
        if imp is None and prev_imp is None:
            ts = _parse_iso_utc(str(row.get("fetched_at") or ""))
            prev_ts = _parse_iso_utc(str(prev.get("fetched_at") or ""))
            if ts is not None and (prev_ts is None or ts > prev_ts):
                best[tid] = row
    return best


def _read_frontmatter(path: pathlib.Path) -> dict[str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        val = v.strip()
        if not key:
            continue
        if val.startswith(("\"", "'")) and val.endswith(("\"", "'")) and len(val) >= 2:
            val = val[1:-1]
        out[key] = val
    return out


def _topics_for_draft(account_root: pathlib.Path, draft_rel: str) -> str:
    try:
        draft_path = (account_root / draft_rel).resolve()
    except Exception:
        return ""
    if not draft_path.exists() or not draft_path.is_file():
        return ""
    fm = _read_frontmatter(draft_path)
    topics = fm.get("topics", "")
    return topics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-dir", help="Account root dir (e.g., accounts/agent-x). Defaults to CWD inference.")
    ap.add_argument("--limit", type=int, default=50, help="How many recent posts to consider (default: 50)")
    args = ap.parse_args()

    account_root = _infer_account_root(args.account_dir)
    state_dir = account_root / "workspace" / "state"
    memory_dir = account_root / "workspace" / "memory"
    posts_path = state_dir / "posts.jsonl"
    metrics_path = state_dir / "metrics.jsonl"

    posts = _read_jsonl(posts_path)
    metrics = _read_jsonl(metrics_path)

    if not posts:
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "performance.md").write_text(
            "# Performance Summary\n\n"
            f"updated_at: `{_utc_now_iso()}`\n\n"
            "- no posts found yet\n",
            encoding="utf-8",
        )
        print("performance: no posts found")
        return 0

    best_by_id = _best_metrics_by_tweet(metrics)

    recent = list(reversed(posts[-args.limit :]))
    rows: list[dict] = []
    for post in recent:
        tid = post.get("tweet_id")
        if not isinstance(tid, str) or not tid:
            continue
        m = best_by_id.get(tid, {})
        rows.append(
            {
                "tweet_id": tid,
                "published_at": str(post.get("published_at") or ""),
                "draft_path": str(post.get("draft_path") or ""),
                "topics": _topics_for_draft(account_root, str(post.get("draft_path") or "")),
                "impressions": _impressions(m) if isinstance(m, dict) else None,
                "replies": _public_metric(m, "reply_count") if isinstance(m, dict) else 0,
                "likes": _public_metric(m, "like_count") if isinstance(m, dict) else 0,
                "reposts": _public_metric(m, "retweet_count") if isinstance(m, dict) else 0,
                "quotes": _public_metric(m, "quote_count") if isinstance(m, dict) else 0,
            }
        )

    def _imp_sort_key(r: dict) -> tuple[int, int]:
        imp = r.get("impressions")
        if isinstance(imp, int):
            return (1, imp)
        return (0, 0)

    top_by_imp = sorted(rows, key=_imp_sort_key, reverse=True)[:10]
    top_by_reply = sorted(rows, key=lambda r: int(r.get("replies") or 0), reverse=True)[:10]

    def _render_table(items: list[dict]) -> list[str]:
        out = [
            "| rank | impressions | replies | likes | reposts | quotes | published_at | topics | draft |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for i, r in enumerate(items, start=1):
            imp = r.get("impressions")
            imp_s = f"{imp:,}" if isinstance(imp, int) else "-"
            out.append(
                "| "
                + " | ".join(
                    [
                        str(i),
                        imp_s,
                        str(r.get("replies") or 0),
                        str(r.get("likes") or 0),
                        str(r.get("reposts") or 0),
                        str(r.get("quotes") or 0),
                        str(r.get("published_at") or ""),
                        str(r.get("topics") or ""),
                        str(r.get("draft_path") or ""),
                    ]
                )
                + " |"
            )
        return out

    md_lines: list[str] = [
        "# Performance Summary",
        "",
        f"updated_at: `{_utc_now_iso()}`",
        "",
        "## Top Posts By Impressions (Observed)",
        "- `impressions` is a lower bound (API limitations apply).",
        "",
        *_render_table(top_by_imp),
        "",
        "## Top Posts By Replies",
        "",
        *_render_table(top_by_reply),
        "",
    ]

    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "performance.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"performance: wrote={memory_dir / 'performance.md'} posts={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

