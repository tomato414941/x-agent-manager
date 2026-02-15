#!/usr/bin/env python3
"""Run OAuth PKCE flow and save X API user tokens."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import secrets
import shlex
import threading
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8787/callback"
DEFAULT_SCOPES = "tweet.read tweet.write users.read offline.access"
DEFAULT_SECRETS_ROOT = pathlib.Path.home() / ".secrets" / "x-agent-manager"


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _load_env_file(path: pathlib.Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
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
        account_path = secrets_root / account_dir.name
        _append(account_path)

    if secrets_root.is_file():
        _append(secrets_root)
    else:
        _append(secrets_root / "config")

    return candidates


def _load_secrets_file(account_dir: pathlib.Path | None, secrets_file: str | None, secrets_root: pathlib.Path) -> None:
    candidates = _normalize_secret_candidates(account_dir, secrets_file, secrets_root)

    for candidate in candidates:
        _load_env_file(candidate)


def _resolve_account_dir(account_dir: str | None) -> pathlib.Path | None:
    if account_dir:
        return pathlib.Path(account_dir).expanduser()

    env_account_dir = os.environ.get("X_ACCOUNT_DIR")
    if env_account_dir:
        return pathlib.Path(env_account_dir).expanduser()

    return None


def _build_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")


def _build_code_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def _build_auth_url(verifier: str, state: str, client_id: str, redirect_uri: str, scopes: str) -> str:
    challenge = _build_code_challenge(verifier)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return "https://x.com/i/oauth2/authorize?" + urlencode(params)


def parse_auth_code(raw: str) -> str:
    raw = raw.strip()
    if "code=" in raw:
        parsed = urlparse(raw)
        return (parse_qs(parsed.query).get("code") or [""])[0]
    return raw


def fetch_token(auth_code: str, verifier: str, client_id: str, redirect_uri: str) -> dict:
    data = urlencode(
        {
            "code": auth_code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()

    req = Request("https://api.x.com/2/oauth2/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"token 取得失敗: HTTP {e.code}\n{body}")
    except URLError as e:
        raise SystemExit(f"token 取得失敗: 接続エラー {e}")


def save_secret(path: str, token: dict) -> str:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    if not access_token:
        raise SystemExit(f"access_token が見つかりませんでした:\n{json.dumps(token, ensure_ascii=False)}")

    out = pathlib.Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(f'export X_ACCESS_TOKEN="{access_token}"\n')
        if refresh_token:
            f.write(f'export X_REFRESH_TOKEN="{refresh_token}"\n')
    out.chmod(0o600)
    return str(out)


class CallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, expected_state: str, expected_path: str, done_state: dict, *args, **kwargs):
        self._expected_state = expected_state
        self._expected_path = expected_path
        self._done_state = done_state
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args):  # noqa: A002
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != self._expected_path:
            self._send_text(404, "Not found")
            return

        params = parse_qs(parsed.query)
        if params.get("error"):
            error = params.get("error", [""])[0]
            self._send_text(400, f"OAuth error: {error}")
            self._done_state["error"] = error
            self._done_state["event"].set()
            return

        state = (params.get("state") or [""])[0]
        if state != self._expected_state:
            self._send_text(400, "Invalid state parameter")
            self._done_state["error"] = "invalid_state"
            self._done_state["event"].set()
            return

        code = (params.get("code") or [""])[0]
        if not code:
            self._send_text(400, "Missing code")
            self._done_state["error"] = "missing_code"
            self._done_state["event"].set()
            return

        self._done_state["code"] = code
        self._send_text(200, "Authorization successful. You can close this tab.")
        self._done_state["event"].set()

    def _send_text(self, status: int, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def _start_callback_server(expected_state: str, bind_host: str, bind_port: int, callback_path: str) -> tuple[HTTPServer, threading.Event, dict]:
    done: dict[str, object] = {"event": threading.Event()}

    class Handler(CallbackHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(expected_state, callback_path, done, *args, **kwargs)

    server = HTTPServer((bind_host, bind_port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, done["event"], done


def _resolve_callback_parts(redirect_uri: str) -> tuple[str, int, str]:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8787
    path = parsed.path or "/callback"
    if not path.startswith("/"):
        path = "/" + path
    return host, port, path


def _wait_for_callback(state: str, redirect_uri: str) -> str:
    host, port, path = _resolve_callback_parts(redirect_uri)
    print(f"2) ブラウザで許可すると、{host}:{port}{path} で code を受け取ります。")
    print("   30秒以内に許可しない場合は、URLを手動貼り付けで入力します。")

    try:
        server, done_event, shared = _start_callback_server(state, host, port, path)
    except OSError as exc:
        print(f"callback server start failed: {exc}")
        return _read_code_from_stdin()

    try:
        if done_event.wait(timeout=300):
            if shared.get("error"):
                raise SystemExit(f"OAuth error: {shared['error']}")
            code = shared.get("code")
            if code:
                return str(code)
            raise SystemExit("callback arrived without code")
        print("時間切れです。callback URL（または code）を貼り付けてください。")
        return _read_code_from_stdin()
    finally:
        server.shutdown()
        server.server_close()


def _read_code_from_stdin() -> str:
    raw = input("2) callback URL（または code）を貼り付けて Enter: ").strip()
    auth_code = parse_auth_code(raw)
    if not auth_code:
        raise SystemExit("code を取得できませんでした")
    return auth_code


def _resolve_output_path(
    account_dir: pathlib.Path | None,
    explicit: str | None,
    secrets_root: pathlib.Path,
) -> str:
    if explicit:
        return os.path.expanduser(explicit)
    if account_dir is not None:
        if secrets_root.is_file():
            print(
                f"warning: '{secrets_root}' is a file. "
                "Saving token to shared secret file for compatibility.",
                file=sys.stderr,
            )
            return str(secrets_root)
        return str(secrets_root / account_dir.name)
    if secrets_root.is_file():
        return str(secrets_root)
    return str(secrets_root / "config")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secrets-root", default=str(DEFAULT_SECRETS_ROOT), help="Root secrets location")
    ap.add_argument("--client-id", default=os.environ.get("X_CLIENT_ID", ""), help="OAuth client id (or X_CLIENT_ID env)")
    ap.add_argument(
        "--redirect-uri",
        default=os.environ.get("X_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        help="OAuth callback URI (default: http://127.0.0.1:8787/callback)",
    )
    ap.add_argument(
        "--scopes",
        default=os.environ.get("X_SCOPES", DEFAULT_SCOPES),
        help="space-separated OAuth scopes",
    )
    ap.add_argument(
        "--account-dir",
        dest="account_dir",
        help="Optional account directory name (defaults to X_ACCOUNT_DIR).",
    )
    ap.add_argument("--secrets-file", dest="secrets_file", help="Explicit secret output file path")
    args = ap.parse_args()

    account_dir = _resolve_account_dir(args.account_dir)
    secrets_root = pathlib.Path(args.secrets_root).expanduser()
    _load_secrets_file(account_dir, args.secrets_file, secrets_root)

    client_id = args.client_id or os.environ.get("X_CLIENT_ID")
    if not client_id:
        _die("Missing X_CLIENT_ID. set env or pass --client-id.")

    redirect_uri = os.environ.get("X_REDIRECT_URI", args.redirect_uri)
    scopes = os.environ.get("X_SCOPES", args.scopes)

    verifier = _build_code_verifier()
    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(verifier, state, client_id, redirect_uri, scopes)

    print("1) 下記をブラウザで開いて認可してください:")
    print(auth_url)
    print()
    webbrowser.open(auth_url, new=1, autoraise=True)

    auth_code = _wait_for_callback(state, redirect_uri)

    token = fetch_token(auth_code, verifier, client_id, redirect_uri)
    out = save_secret(_resolve_output_path(account_dir, args.secrets_file, secrets_root), token)
    print(f"保存しました: {out}")


if __name__ == "__main__":
    main()
