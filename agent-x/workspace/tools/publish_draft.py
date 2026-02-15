#!/usr/bin/env python3
"""Publish an approved draft to X via API v2.

Guardrails:
- Refuses to run unless hostname == 'autonomous' (configurable via EXPECTED_HOSTNAME env).
- Refuses to publish unless the draft path is explicitly present in workspace/human/messages.md.
- Never prints or writes secrets. Reads token from env vars only.

Usage:
  python3 workspace/tools/publish_draft.py workspace/drafts/20260215_084451_guardrails_stop_mechanism.md

Env:
  X_ACCESS_TOKEN or X_USER_ACCESS_TOKEN (OAuth2 user access token with tweet.write)
  X_BEARER_TOKEN, TWITTER_ACCESS_TOKEN, or BEARER_TOKEN (legacy fallbacks)
  EXPECTED_HOSTNAME (default: autonomous)
  You can also set variables in ~/.secrets/agent-x (exported shell syntax).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import socket
import sys
import shlex
import urllib.error
import urllib.request


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _utc_now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_secrets_file() -> None:
    candidate = pathlib.Path.home() / ".secrets" / "agent-x"
    if not candidate.exists():
        return

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


def _repo_root() -> pathlib.Path:
    # .../workspace/tools/publish_draft.py -> repo root is two levels up.
    return pathlib.Path(__file__).resolve().parents[2]


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
        " Tokens can be loaded from ~/.secrets/agent-x if present."
    )


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
    ap.add_argument("draft", help="Path to a draft .md under workspace/drafts/")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do all checks and parsing, but do not call the X API.",
    )
    args = ap.parse_args()

    _require_autonomous()
    _load_secrets_file()

    root = _repo_root()
    drafts_dir = root / "workspace" / "drafts"

    draft_path = pathlib.Path(args.draft).expanduser().resolve()
    if not draft_path.exists():
        _die(f"Draft not found: {draft_path}")
    if not draft_path.is_file():
        _die(f"Draft is not a file: {draft_path}")
    if not draft_path.is_relative_to(drafts_dir):
        _die(f"Draft must be under {drafts_dir}: {draft_path}")

    draft_rel = draft_path.relative_to(root).as_posix()
    _require_approved(root, draft_rel)

    text = _read_draft_body(draft_path)
    if len(text) > 280:
        print(f"warn: draft text length is {len(text)} (> 280)", file=sys.stderr)

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
        "text": text,
        "response": resp,
    }
    _append_posts_jsonl(root, record)

    print(f"published: tweet_id={tweet_id} draft={draft_rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
