#!/usr/bin/env python3
"""Publish an approved draft to X via API v2.

Guardrails:
- Refuses to run unless hostname == 'autonomous' (configurable via EXPECTED_HOSTNAME env).
- Refuses to publish unless the draft path is explicitly present in workspace/human/messages.md.
- Never prints or writes secrets. Reads token from env vars only.
- Auto publish mode (opt-in): requires AUTO_PUBLISH=1 and draft frontmatter `auto_publish: true` + due `scheduled_at`.

Usage:
  python3 scripts/publish_draft.py accounts/agent-x/workspace/drafts/20260215_084451_guardrails_stop_mechanism.md
  python3 scripts/publish_draft.py --account-dir accounts/agent-x --draft workspace/drafts/20260215_084451_guardrails_stop_mechanism.md

Env:
  X_ACCESS_TOKEN or X_USER_ACCESS_TOKEN (OAuth2 user access token with tweet.write)
  X_BEARER_TOKEN, TWITTER_ACCESS_TOKEN, or BEARER_TOKEN (legacy fallbacks)
  EXPECTED_HOSTNAME (default: autonomous)
  You can also set variables in:
  - ~/.secrets/x-agent-manager/config (app-level config, exported shell syntax)
  - ~/.secrets/x-agent-manager/<account-name> (account-specific user token file)

Auto publish env (optional):
  AUTO_PUBLISH=1 enables auto publishing.
  STOP_PUBLISH=1 stops publishing (kill switch).
  MAX_POSTS_PER_DAY (default: 2)
  MIN_POST_INTERVAL_MINUTES (default: 180)
  MAX_LATE_MINUTES (default: 720)  # skip drafts scheduled too far in the past
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import socket
import sys
import shlex
import urllib.error
import urllib.request


DEFAULT_SECRETS_ROOT = pathlib.Path.home() / ".secrets" / "x-agent-manager"
DEFAULT_MAX_POSTS_PER_DAY = 2
DEFAULT_MIN_POST_INTERVAL_MINUTES = 180
DEFAULT_MAX_LATE_MINUTES = 720


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


def _is_truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


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
    account_dir: pathlib.Path | None = None,
    secrets_file: str | None = None,
    secrets_root: pathlib.Path | None = None,
) -> None:
    root = secrets_root or DEFAULT_SECRETS_ROOT
    candidates = _normalize_secret_candidates(account_dir, secrets_file, root)

    for candidate in candidates:
        if not candidate.exists():
            continue
        if not candidate.is_file():
            continue

        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue

            # Support quoted or plain values, and ignore inline comments when possible.
            try:
                parts = shlex.split(value)
            except ValueError:
                parts = [value]
            if not parts:
                continue

            env_value = parts[0]
            if env_value == "\"\"" or env_value == "''":
                continue
            os.environ[key] = env_value


def _read_frontmatter(draft_path: pathlib.Path) -> dict[str, str]:
    raw = draft_path.read_text(encoding="utf-8", errors="replace")
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


def _text_sha256(text: str) -> str:
    # Normalize to reduce accidental duplicates due to trailing whitespace.
    normalized = "\n".join([line.rstrip() for line in text.strip().splitlines()]).strip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_posts_jsonl(root: pathlib.Path) -> list[dict]:
    posts = root / "workspace" / "state" / "posts.jsonl"
    if not posts.exists() or not posts.is_file():
        return []
    out: list[dict] = []
    for raw in posts.read_text(encoding="utf-8", errors="replace").splitlines():
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


def _require_not_stopped(root: pathlib.Path) -> None:
    if _is_truthy(os.environ.get("STOP_PUBLISH")):
        _die("Publishing stopped by STOP_PUBLISH=1.")
    stop_path = os.environ.get("STOP_PUBLISH_PATH")
    if stop_path:
        path = pathlib.Path(stop_path).expanduser()
    else:
        path = root / "workspace" / "state" / "STOP_PUBLISH"
    if path.exists():
        _die(f"Publishing stopped by kill switch file: {path}")


def _require_rate_limits(root: pathlib.Path) -> None:
    posts = _read_posts_jsonl(root)
    now = _dt.datetime.now(tz=_dt.timezone.utc)

    max_per_day = int(os.environ.get("MAX_POSTS_PER_DAY", str(DEFAULT_MAX_POSTS_PER_DAY)))
    min_interval_min = int(os.environ.get("MIN_POST_INTERVAL_MINUTES", str(DEFAULT_MIN_POST_INTERVAL_MINUTES)))
    min_interval = _dt.timedelta(minutes=max(0, min_interval_min))

    last_post_at: _dt.datetime | None = None
    count_24h = 0

    for row in posts:
        ts = row.get("published_at")
        if not isinstance(ts, str):
            continue
        dt = _parse_iso_utc(ts)
        if dt is None:
            continue
        if last_post_at is None or dt > last_post_at:
            last_post_at = dt
        if (now - dt) <= _dt.timedelta(hours=24):
            count_24h += 1

    if max_per_day > 0 and count_24h >= max_per_day:
        _die(f"Rate limit: already posted {count_24h} times in last 24h (MAX_POSTS_PER_DAY={max_per_day}).")

    if last_post_at is not None and (now - last_post_at) < min_interval:
        remaining = min_interval - (now - last_post_at)
        mins = int(remaining.total_seconds() // 60) + 1
        _die(f"Rate limit: last post too recent. Try again in ~{mins} minutes.")


def _require_not_duplicate(root: pathlib.Path, draft_rel: str, text_hash: str) -> None:
    posts = _read_posts_jsonl(root)
    for row in posts:
        if row.get("draft_path") == draft_rel:
            _die(f"Duplicate: draft already published: {draft_rel}")
        if row.get("text_sha256") == text_hash:
            _die("Duplicate: text hash already published.")


def _infer_account_root(draft_path: pathlib.Path) -> pathlib.Path:
    current = draft_path.parent
    for parent in [draft_path, *current.parents]:
        if parent.name == "workspace":
            return parent.parent

    _die(
        "Could not infer account root from draft path. "
        "Pass --account-dir or use a path like accounts/<account>/workspace/drafts/..."
    )


def _read_draft_body(draft_path: pathlib.Path) -> str:
    raw = draft_path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            _die(f"Invalid draft: missing closing frontmatter delimiter '---': {draft_path}")
        body = "".join(lines[end_idx + 1 :]).strip()
    else:
        body = raw.strip()

    if not body:
        _die(f"Invalid draft: empty body: {draft_path}")
    return body


def _require_autonomous() -> None:
    expected = os.environ.get("EXPECTED_HOSTNAME", "autonomous")
    host = socket.gethostname().split(".", 1)[0]
    if host != expected:
        _die(f"Refusing to publish on host '{host}' (expected '{expected}').")


def _require_approved(root: pathlib.Path, draft_rel: str) -> None:
    messages = root / "workspace" / "human" / "messages.md"
    if not messages.exists():
        _die(f"Missing approval file: {messages}")
    text = messages.read_text(encoding="utf-8", errors="replace")
    if draft_rel not in text:
        _die(
            "Draft not approved in workspace/human/messages.md. "
            f"Need an explicit reference to: {draft_rel}"
        )


def _extract_error_detail(body: str) -> tuple[str, str]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "", body[:200]

    if not isinstance(data, dict):
        return "", body[:200]

    return data.get("title", ""), data.get("detail", "") or str(data)


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
    _die(
        "Missing access token env var. Set X_ACCESS_TOKEN (recommended) or X_USER_ACCESS_TOKEN "
        "with OAuth2 user context + tweet.write."
        " Also supports X_BEARER_TOKEN, TWITTER_ACCESS_TOKEN, or BEARER_TOKEN."
        " Tokens can be loaded from ~/.secrets/x-agent-manager/config or "
        "~/.secrets/x-agent-manager/<account-name>."
    )


def _require_auto_mode(root: pathlib.Path, draft_path: pathlib.Path) -> None:
    if not _is_truthy(os.environ.get("AUTO_PUBLISH")):
        _die("Auto publish disabled. Set AUTO_PUBLISH=1 to enable.", code=1)

    fm = _read_frontmatter(draft_path)
    if not _is_truthy(fm.get("auto_publish")):
        _die("Auto publish refused: draft frontmatter missing `auto_publish: true`.", code=1)

    scheduled_at = _parse_iso_utc(fm.get("scheduled_at", ""))
    if scheduled_at is None:
        _die("Auto publish refused: frontmatter missing valid `scheduled_at`.", code=1)

    now = _dt.datetime.now(tz=_dt.timezone.utc)
    if scheduled_at > now:
        _die("Auto publish refused: scheduled_at is in the future.", code=1)

    max_late = int(os.environ.get("MAX_LATE_MINUTES", str(DEFAULT_MAX_LATE_MINUTES)))
    if max_late >= 0 and (now - scheduled_at) > _dt.timedelta(minutes=max_late):
        _die("Auto publish refused: scheduled_at is too old (MAX_LATE_MINUTES).", code=1)

    _require_not_stopped(root)
    _require_rate_limits(root)


def _post_tweet(text: str, token: str) -> dict:
    url = "https://api.x.com/2/tweets"
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if not body:
                return {}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        title, detail = _extract_error_detail(body)
        if e.code == 403 and title == "Unsupported Authentication":
            _die(
                "X API error HTTP 403: Unsupported Authentication. "
                "Use OAuth 2.0 User Context token (not app-only) "
                f"with tweet.write scope. Detail: {detail or body}",
                code=1,
            )
        _die(f"X API error HTTP {e.code}: {title} {detail}".strip() or body, code=1)
    except urllib.error.URLError as e:
        _die(f"X API connection error: {e}", code=1)


def _append_posts_jsonl(root: pathlib.Path, record: dict) -> None:
    posts = root / "workspace" / "state" / "posts.jsonl"
    posts.parent.mkdir(parents=True, exist_ok=True)
    with posts.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", nargs="?", help="Path to a draft .md under workspace/drafts/")
    ap.add_argument(
        "--draft",
        dest="draft_alias",
        help="Optional positional alternative for the draft path.",
    )
    ap.add_argument(
        "--account-dir",
        dest="account_dir",
        help="Optional account root directory (e.g. accounts/agent-x). "
             "If omitted, inferred from draft path.",
    )
    ap.add_argument(
        "--secrets-root",
        dest="secrets_root",
        default=str(DEFAULT_SECRETS_ROOT),
        help="Secrets root directory/file path (default: ~/.secrets/x-agent-manager).",
    )
    ap.add_argument(
        "--secrets-file",
        dest="secrets_file",
        help="Optional explicit secret file path. "
             "Takes precedence over inferred ~/.secrets/x-agent-manager/<account> and fallback file.",
    )
    ap.add_argument(
        "--publish-mode",
        dest="publish_mode",
        default=os.environ.get("PUBLISH_MODE", "human"),
        choices=["human", "auto"],
        help="Publish mode: human (default) requires approval in workspace/human/messages.md; "
             "auto requires AUTO_PUBLISH=1 and draft frontmatter flags.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do all checks and parsing, but do not call the X API.",
    )
    args = ap.parse_args()
    draft_arg = args.draft_alias or args.draft
    if not draft_arg:
        _die("Draft path is required (positional argument or --draft).")

    _require_autonomous()

    draft_path = pathlib.Path(draft_arg).expanduser().resolve()
    account_root = _infer_account_root(draft_path)
    if args.account_dir:
        account_root = pathlib.Path(args.account_dir).expanduser().resolve()
        if not account_root.name:
            _die("--account-dir is invalid")
        if not account_root.is_dir():
            _die(f"--account-dir not found: {account_root}")
        if not (account_root / "workspace").is_dir():
            _die(f"--account-dir missing workspace directory: {account_root}")

    _load_secrets_file(
        account_dir=account_root,
        secrets_file=args.secrets_file,
        secrets_root=pathlib.Path(args.secrets_root).expanduser(),
    )

    drafts_dir = account_root / "workspace" / "drafts"
    if not draft_path.exists():
        _die(f"Draft not found: {draft_path}")
    if not draft_path.is_file():
        _die(f"Draft is not a file: {draft_path}")
    if not draft_path.is_relative_to(drafts_dir):
        _die(f"Draft must be under {drafts_dir}: {draft_path}")

    draft_rel = draft_path.relative_to(account_root).as_posix()
    if args.publish_mode == "human":
        _require_approved(account_root, draft_rel)

    text = _read_draft_body(draft_path)
    text_hash = _text_sha256(text)
    if len(text) > 280:
        print(f"warn: draft text length is {len(text)} (> 280)", file=sys.stderr)

    if args.publish_mode == "auto":
        _require_auto_mode(account_root, draft_path)
        _require_not_duplicate(account_root, draft_rel, text_hash)

    if args.dry_run:
        print(f"dry_run ok: {draft_rel}")
        return 0

    token = _get_access_token()
    resp = _post_tweet(text=text, token=token)

    tweet_id = (
        resp.get("data", {}).get("id")
        if isinstance(resp, dict)
        else None
    )

    record = {
        "published_at": _utc_now_iso(),
        "draft_path": draft_rel,
        "tweet_id": tweet_id,
        "text_sha256": text_hash,
        "text": text,
        "response": resp,
    }
    _append_posts_jsonl(account_root, record)

    print(f"published: tweet_id={tweet_id} draft={draft_rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
