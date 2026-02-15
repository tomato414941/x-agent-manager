#!/usr/bin/env python3
"""Auto-publish due drafts for an account (opt-in via AUTO_PUBLISH=1).

Selection rules (safe defaults):
- Only drafts under workspace/drafts/.
- Only drafts with YAML frontmatter `auto_publish: true`.
- Only drafts with `scheduled_at` set and due (<= now).
- If scheduled_at is too old, skip (MAX_LATE_MINUTES).
- Publishes at most 1 draft per run.

Publishing is delegated to scripts/publish_draft.py, which enforces additional
guardrails (host check, rate limits, duplicates, kill switch).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys


DEFAULT_SECRETS_ROOT = pathlib.Path.home() / ".secrets" / "x-agent-manager"


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


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


def _replace_or_insert_frontmatter(lines: list[str], updates: dict[str, str]) -> list[str]:
    if not lines or lines[0].strip() != "---":
        return lines

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return lines

    fm_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1 :]

    key_to_idx: dict[str, int] = {}
    for i, line in enumerate(fm_lines):
        if ":" not in line:
            continue
        k = line.split(":", 1)[0].strip()
        if k:
            key_to_idx[k] = i

    for k, v in updates.items():
        if k in key_to_idx:
            fm_lines[key_to_idx[k]] = f"{k}: {v}"

    insert_at = 0
    if "created_at" in key_to_idx:
        insert_at = key_to_idx["created_at"] + 1
    for k, v in updates.items():
        if k not in key_to_idx:
            fm_lines.insert(insert_at, f"{k}: {v}")
            insert_at += 1

    return ["---", *fm_lines, "---", *body_lines]


def _is_truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


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


def _disarm_draft(draft_path: pathlib.Path) -> None:
    raw = draft_path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines(keepends=False)
    if not lines or lines[0].strip() != "---":
        return
    updates = {
        "auto_publish": "false",
        "published_at": f"\"{_dt.datetime.now(tz=_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\"",
    }
    new_lines = _replace_or_insert_frontmatter(lines, updates)
    draft_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-dir", help="Account root dir (e.g., accounts/agent-x). Defaults to CWD inference.")
    ap.add_argument("--secrets-root", default=str(DEFAULT_SECRETS_ROOT), help="Secrets root (default: ~/.secrets/x-agent-manager)")
    ap.add_argument("--secrets-file", help="Optional explicit secret file path (export syntax)")
    ap.add_argument("--max-late-minutes", type=int, default=int(os.environ.get("MAX_LATE_MINUTES", "720")))
    args = ap.parse_args()

    if not _is_truthy(os.environ.get("AUTO_PUBLISH")):
        print("auto_publish: disabled (set AUTO_PUBLISH=1 to enable)")
        return 0

    account_root = _infer_account_root(args.account_dir)
    drafts_dir = account_root / "workspace" / "drafts"
    if not drafts_dir.is_dir():
        print("auto_publish: no drafts dir")
        return 0

    published_drafts = _published_drafts_set(account_root)

    now = _dt.datetime.now(tz=_dt.timezone.utc)
    max_late = _dt.timedelta(minutes=max(0, args.max_late_minutes))

    candidates: list[tuple[_dt.datetime, pathlib.Path]] = []
    for path in sorted(drafts_dir.glob("*.md")):
        fm = _read_frontmatter(path)
        if not fm:
            continue
        if not _is_truthy(fm.get("auto_publish")):
            continue
        try:
            draft_rel = path.relative_to(account_root).as_posix()
        except ValueError:
            continue
        if draft_rel in published_drafts:
            _disarm_draft(path)
            continue
        scheduled_at = _parse_iso_utc(fm.get("scheduled_at", ""))
        if scheduled_at is None:
            continue
        if scheduled_at > now:
            continue
        if (now - scheduled_at) > max_late:
            continue
        candidates.append((scheduled_at, path))

    if not candidates:
        print("auto_publish: no eligible drafts")
        return 0

    candidates.sort(key=lambda x: x[0])
    publish_script = (pathlib.Path(__file__).resolve().parent / "publish_draft.py").resolve()
    secrets_root = pathlib.Path(args.secrets_root).expanduser()
    last_code = 0
    for scheduled_at, draft_path in candidates:
        cmd = [
            sys.executable,
            os.fspath(publish_script),
            os.fspath(draft_path),
            "--account-dir",
            os.fspath(account_root),
            "--publish-mode",
            "auto",
            "--secrets-root",
            os.fspath(secrets_root),
        ]
        if args.secrets_file:
            cmd += ["--secrets-file", os.path.expanduser(args.secrets_file)]

        proc = subprocess.run(cmd, check=False)
        if proc.returncode == 0:
            _disarm_draft(draft_path)
            print(f"auto_publish: published scheduled_at={scheduled_at.isoformat()} draft={draft_path.name}")
            return 0

        last_code = proc.returncode
        print(f"auto_publish: publish failed code={proc.returncode} draft={draft_path.name}", file=sys.stderr)

    return last_code


if __name__ == "__main__":
    raise SystemExit(main())
