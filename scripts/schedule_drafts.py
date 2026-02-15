#!/usr/bin/env python3
"""Schedule drafts for auto publishing (JST-friendly).

Opt-in behavior:
- Requires AUTO_PUBLISH=1 and AUTO_SCHEDULE=1.

What it does:
- If there is already a future scheduled draft with `auto_publish: true`, do nothing.
- Otherwise, pick one draft without `scheduled_at` and set:
  - auto_publish: true
  - scheduled_at: next configured slot in SCHEDULE_TZ (default Asia/Tokyo), converted to UTC (Z)

Draft selection:
- Oldest draft file (by filename sort) that is not already scheduled.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sys

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


DEFAULT_TZ = "Asia/Tokyo"
DEFAULT_SLOTS = "07:30,12:10,20:30"
DEFAULT_BUFFER_MINUTES = 10
DEFAULT_MAX_POSTS_PER_DAY = 2
DEFAULT_MIN_POST_INTERVAL_MINUTES = 180
DEFAULT_MAX_LATE_MINUTES = 720


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _is_truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_iso_any(s: str) -> _dt.datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return _dt.datetime.fromisoformat(s[:-1] + "+00:00")
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _as_utc(dt: _dt.datetime) -> _dt.datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


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


def _read_frontmatter(path: pathlib.Path) -> tuple[dict[str, str], list[str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines(keepends=False)
    if not lines or lines[0].strip() != "---":
        return {}, lines

    fm: dict[str, str] = {}
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
        fm[key] = val

    return fm, lines


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


def _published_drafts_set(account_root: pathlib.Path) -> set[str]:
    posts_path = account_root / "workspace" / "state" / "posts.jsonl"
    rows = _read_jsonl(posts_path)
    out: set[str] = set()
    for row in rows:
        p = row.get("draft_path")
        if isinstance(p, str) and p:
            out.add(p)
    return out


def _post_times(account_root: pathlib.Path, now_utc: _dt.datetime) -> tuple[_dt.datetime | None, int, _dt.datetime | None]:
    posts_path = account_root / "workspace" / "state" / "posts.jsonl"
    rows = _read_jsonl(posts_path)
    times: list[_dt.datetime] = []
    for row in rows:
        ts = row.get("published_at")
        if not isinstance(ts, str):
            continue
        dt = _parse_iso_any(ts)
        if dt is None:
            continue
        times.append(_as_utc(dt))
    if not times:
        return None, 0, None

    last_post = max(times)
    times_24h = [t for t in times if (now_utc - t) <= _dt.timedelta(hours=24)]
    if not times_24h:
        return last_post, 0, None
    oldest_24h = min(times_24h)
    return last_post, len(times_24h), oldest_24h


def _replace_or_insert_frontmatter(
    lines: list[str],
    updates: dict[str, str],
) -> list[str]:
    if not lines or lines[0].strip() != "---":
        # Create a new frontmatter block.
        out = ["---"]
        for k, v in updates.items():
            out.append(f"{k}: {v}")
        out.append("---")
        out.extend(lines)
        return out

    # Find end of frontmatter.
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        # Malformed; bail out rather than corrupt.
        return lines

    fm_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1 :]

    # Map existing keys to line indices.
    key_to_idx: dict[str, int] = {}
    for i, line in enumerate(fm_lines):
        if ":" not in line:
            continue
        k = line.split(":", 1)[0].strip()
        if k:
            key_to_idx[k] = i

    # Apply replacements.
    for k, v in updates.items():
        if k in key_to_idx:
            fm_lines[key_to_idx[k]] = f"{k}: {v}"

    # Insert missing keys in a stable location: after created_at if present, else at top.
    insert_at = 0
    if "created_at" in key_to_idx:
        insert_at = key_to_idx["created_at"] + 1

    for k, v in updates.items():
        if k not in key_to_idx:
            fm_lines.insert(insert_at, f"{k}: {v}")
            insert_at += 1

    return ["---", *fm_lines, "---", *body_lines]


def _parse_slots(spec: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in (spec or "").split(","):
        p = part.strip()
        if not p:
            continue
        if ":" not in p:
            continue
        hh, mm = p.split(":", 1)
        try:
            h = int(hh)
            m = int(mm)
        except ValueError:
            continue
        if not (0 <= h <= 23 and 0 <= m <= 59):
            continue
        out.append((h, m))
    return out


def _get_tz(name: str) -> _dt.tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    # Fixed JST fallback.
    if name == "Asia/Tokyo":
        return _dt.timezone(_dt.timedelta(hours=9))
    return _dt.timezone.utc


def _next_slot_utc(
    earliest_utc: _dt.datetime,
    tz_name: str,
    slots: list[tuple[int, int]],
) -> _dt.datetime:
    if earliest_utc.tzinfo is None:
        earliest_utc = earliest_utc.replace(tzinfo=_dt.timezone.utc)

    tz = _get_tz(tz_name)
    earliest_local = earliest_utc.astimezone(tz)

    # Search the next 7 days for the earliest slot >= earliest_local.
    for day_offset in range(0, 8):
        d = (earliest_local.date() + _dt.timedelta(days=day_offset))
        for (h, m) in slots:
            candidate_local = _dt.datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
            if candidate_local >= earliest_local:
                return candidate_local.astimezone(_dt.timezone.utc)

    raise RuntimeError("no slot found within 7 days")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-dir", help="Account root dir (e.g., accounts/agent-x). Defaults to CWD inference.")
    ap.add_argument("--tz", default=os.environ.get("SCHEDULE_TZ", DEFAULT_TZ), help="Schedule timezone (default: Asia/Tokyo)")
    ap.add_argument(
        "--slots",
        default=os.environ.get("SCHEDULE_SLOTS", DEFAULT_SLOTS),
        help="Comma-separated local time slots (HH:MM) in --tz (default: 07:30,12:10,20:30)",
    )
    ap.add_argument(
        "--buffer-minutes",
        type=int,
        default=int(os.environ.get("SCHEDULE_BUFFER_MINUTES", str(DEFAULT_BUFFER_MINUTES))),
        help="Minimum minutes from now for scheduled_at (default: 10)",
    )
    args = ap.parse_args()

    if not _is_truthy(os.environ.get("AUTO_PUBLISH")):
        print("schedule: disabled (AUTO_PUBLISH!=1)")
        return 0
    if not _is_truthy(os.environ.get("AUTO_SCHEDULE", "1")):
        print("schedule: disabled (AUTO_SCHEDULE!=1)")
        return 0
    if _is_truthy(os.environ.get("STOP_PUBLISH")):
        print("schedule: stopped (STOP_PUBLISH=1)")
        return 0

    account_root = _infer_account_root(args.account_dir)
    drafts_dir = account_root / "workspace" / "drafts"
    if not drafts_dir.is_dir():
        print("schedule: no drafts dir")
        return 0

    now_utc = _dt.datetime.now(tz=_dt.timezone.utc)
    slots = _parse_slots(args.slots)
    if not slots:
        _die(f"Invalid slots: {args.slots}")

    max_per_day = int(os.environ.get("MAX_POSTS_PER_DAY", str(DEFAULT_MAX_POSTS_PER_DAY)))
    min_interval_min = int(os.environ.get("MIN_POST_INTERVAL_MINUTES", str(DEFAULT_MIN_POST_INTERVAL_MINUTES)))
    max_late_min = int(os.environ.get("MAX_LATE_MINUTES", str(DEFAULT_MAX_LATE_MINUTES)))

    last_post_at, count_24h, oldest_24h = _post_times(account_root, now_utc)
    earliest_publish_utc = now_utc
    if last_post_at is not None:
        earliest_publish_utc = max(
            earliest_publish_utc,
            last_post_at + _dt.timedelta(minutes=max(0, min_interval_min)),
        )
    if max_per_day > 0 and count_24h >= max_per_day and oldest_24h is not None:
        earliest_publish_utc = max(earliest_publish_utc, oldest_24h + _dt.timedelta(hours=24))

    earliest_schedule_utc = max(
        earliest_publish_utc,
        now_utc + _dt.timedelta(minutes=max(0, args.buffer_minutes)),
    )

    published_drafts = _published_drafts_set(account_root)
    paths = sorted(drafts_dir.glob("*.md"))

    queued_future: list[pathlib.Path] = []
    broken_auto: list[pathlib.Path] = []
    active_auto: list[pathlib.Path] = []

    for path in paths:
        fm, _ = _read_frontmatter(path)
        if not _is_truthy(fm.get("auto_publish")):
            continue
        try:
            rel = path.relative_to(account_root).as_posix()
        except ValueError:
            rel = ""
        if rel and rel in published_drafts:
            fm2, lines2 = _read_frontmatter(path)
            new_lines = _replace_or_insert_frontmatter(
                lines2,
                {"auto_publish": "false", "scheduled_at": "\"\""},
            )
            path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            continue

        active_auto.append(path)
        scheduled = _parse_iso_any(fm.get("scheduled_at", ""))
        if scheduled is None:
            broken_auto.append(path)
            continue
        scheduled_utc = _as_utc(scheduled)
        if scheduled_utc > now_utc:
            queued_future.append(path)

    # If multiple drafts are marked auto_publish, keep only one (earliest scheduled if possible).
    if len(active_auto) > 1:
        def _sort_key(p: pathlib.Path) -> tuple[int, str]:
            fm, _ = _read_frontmatter(p)
            dt = _parse_iso_any(fm.get("scheduled_at", ""))
            if dt is None:
                return (0, p.name)
            return (1, _as_utc(dt).isoformat())

        active_auto.sort(key=_sort_key)
        keep = active_auto[0]
        for extra in active_auto[1:]:
            fm, lines = _read_frontmatter(extra)
            new_lines = _replace_or_insert_frontmatter(lines, {"auto_publish": "false", "scheduled_at": "\"\""})
            extra.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        active_auto = [keep]

    # If there is an active auto draft, repair/reschedule it and return.
    if active_auto:
        path = active_auto[0]
        fm, lines = _read_frontmatter(path)
        scheduled = _parse_iso_any(fm.get("scheduled_at", ""))
        scheduled_utc = _as_utc(scheduled) if scheduled is not None else None

        # If it is due and can be published now, leave it for auto_publish.py.
        if scheduled_utc is not None:
            too_old = (now_utc - scheduled_utc) > _dt.timedelta(minutes=max(0, max_late_min))
            can_publish_now = earliest_publish_utc <= now_utc
            if scheduled_utc <= now_utc and (not too_old) and can_publish_now:
                print(f"schedule: leaving due draft={path.name}")
                return 0

        # Otherwise, reschedule to the next allowed slot.
        target_utc = _next_slot_utc(earliest_schedule_utc, args.tz, slots)
        target_str = target_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        new_lines = _replace_or_insert_frontmatter(
            lines,
            {"scheduled_at": f"\"{target_str}\"", "auto_publish": "true"},
        )
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"schedule: rescheduled draft={path.name} scheduled_at={target_str} tz={args.tz}")
        return 0

    # Pick a draft to schedule.
    pick: pathlib.Path | None = None
    pick_lines: list[str] = []

    for path in paths:
        fm, lines = _read_frontmatter(path)
        if not lines or lines[0].strip() != "---":
            continue
        if _is_truthy(fm.get("auto_publish")):
            continue
        if fm.get("scheduled_at"):
            continue
        pick = path
        pick_lines = lines
        break

    if pick is None:
        print("schedule: no unscheduled drafts")
        return 0

    scheduled_utc = _next_slot_utc(earliest_schedule_utc, args.tz, slots)
    scheduled_str = scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    updates = {
        "scheduled_at": f"\"{scheduled_str}\"",
        "auto_publish": "true",
    }
    new_lines = _replace_or_insert_frontmatter(pick_lines, updates)
    pick.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    print(f"schedule: set draft={pick.name} scheduled_at={scheduled_str} tz={args.tz}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
