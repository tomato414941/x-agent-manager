#!/usr/bin/env python3
"""Compute creator revenue sharing eligibility progress and write a summary.

This focuses on the "5M organic impressions in last 3 months" requirement.

Limitations:
- organic_metrics / non_public_metrics are only available for posts created
  within the last 30 days (per X API docs). To track a 90-day window, this
  script relies on previously stored snapshots in metrics.jsonl.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys


TARGET_ORGANIC_IMPRESSIONS_90D = 5_000_000
WINDOW_DAYS = 90


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


def _get_impression_count(row: dict) -> int | None:
    organic = row.get("organic_metrics")
    if isinstance(organic, dict):
        val = organic.get("impression_count")
        if isinstance(val, int):
            return val
    non_public = row.get("non_public_metrics")
    if isinstance(non_public, dict):
        val = non_public.get("impression_count")
        if isinstance(val, int):
            return val
    return None


def _max_impressions_by_tweet(metrics: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in metrics:
        tid = row.get("tweet_id")
        if not isinstance(tid, str) or not tid:
            continue
        imp = _get_impression_count(row)
        if imp is None:
            continue
        prev = out.get(tid)
        if prev is None or imp > prev:
            out[tid] = imp
    return out


def _tweet_created_at(metrics: list[dict]) -> dict[str, _dt.datetime]:
    out: dict[str, _dt.datetime] = {}
    for row in metrics:
        tid = row.get("tweet_id")
        if not isinstance(tid, str) or not tid:
            continue
        created = row.get("created_at")
        if not isinstance(created, str) or not created:
            continue
        dt = _parse_iso_utc(created)
        if dt is None:
            continue
        prev = out.get(tid)
        # created_at is stable; keep the earliest if conflicting.
        if prev is None or dt < prev:
            out[tid] = dt
    return out


def _last_manual_record(path: pathlib.Path) -> dict | None:
    rows = _read_jsonl(path)
    if not rows:
        return None
    return rows[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-dir", help="Account root dir (e.g., accounts/agent-x). Defaults to CWD inference.")
    args = ap.parse_args()

    account_root = _infer_account_root(args.account_dir)
    state_dir = account_root / "workspace" / "state"
    memory_dir = account_root / "workspace" / "memory"
    metrics_path = state_dir / "metrics.jsonl"
    manual_path = state_dir / "manual.jsonl"

    metrics = _read_jsonl(metrics_path)
    max_by_tweet = _max_impressions_by_tweet(metrics)
    created_by_tweet = _tweet_created_at(metrics)

    now = _dt.datetime.now(tz=_dt.timezone.utc)
    window_start = now - _dt.timedelta(days=WINDOW_DAYS)

    in_window: list[str] = []
    unknown_created: list[str] = []
    for tid, imp in max_by_tweet.items():
        created = created_by_tweet.get(tid)
        if created is None:
            unknown_created.append(tid)
            continue
        if created >= window_start:
            in_window.append(tid)

    observed_impressions = sum(max_by_tweet.get(tid, 0) for tid in in_window)

    manual = _last_manual_record(manual_path) or {}
    verified_followers = manual.get("verified_followers")
    if not isinstance(verified_followers, int):
        verified_followers = None

    progress_pct = (observed_impressions / TARGET_ORGANIC_IMPRESSIONS_90D * 100.0) if TARGET_ORGANIC_IMPRESSIONS_90D else 0.0

    summary = {
        "computed_at": _utc_now_iso(),
        "window_days": WINDOW_DAYS,
        "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_organic_impressions_90d": TARGET_ORGANIC_IMPRESSIONS_90D,
        "observed_organic_impressions_90d": observed_impressions,
        "observed_progress_pct": round(progress_pct, 2),
        "tweets_with_observed_impressions": len(max_by_tweet),
        "tweets_in_window": len(in_window),
        "tweets_missing_created_at": len(unknown_created),
        "verified_followers_manual": verified_followers,
        "notes": (
            "observed_* is a lower bound based on stored snapshots in metrics.jsonl. "
            "X API only exposes organic/non-public metrics for posts created within the last 30 days."
        ),
    }

    state_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Append machine-readable history.
    with (state_dir / "eligibility.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    # Write a human-readable latest view.
    md_lines = [
        "# Eligibility Progress (Creator Revenue Sharing)",
        "",
        f"computed_at: `{summary['computed_at']}`",
        "",
        "## Organic Impressions (Last 90 Days)",
        f"- observed: `{observed_impressions:,}` / `{TARGET_ORGANIC_IMPRESSIONS_90D:,}` ({summary['observed_progress_pct']}%)",
        f"- window_start: `{summary['window_start']}`",
        f"- tweets_in_window: `{summary['tweets_in_window']}`",
        "",
        "## Verified Followers (Manual)",
        f"- verified_followers: `{verified_followers}`" if verified_followers is not None else "- verified_followers: `unknown` (set in workspace/state/manual.jsonl)",
        "",
        "## Notes",
        f"- {summary['notes']}",
        "",
        "### How To Set Manual Verified Followers",
        "Append a JSON line to `workspace/state/manual.jsonl` like:",
        "```json",
        f'{{"updated_at":"{_utc_now_iso()}","verified_followers":123}}',
        "```",
    ]
    (memory_dir / "eligibility.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(
        f"eligibility: observed_impressions_90d={observed_impressions} "
        f"progress_pct={summary['observed_progress_pct']} "
        f"tweets_in_window={summary['tweets_in_window']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
