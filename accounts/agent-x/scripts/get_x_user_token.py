#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.error
import urllib.parse
import urllib.request


CLIENT_ID = "OUFFYW9Nb1N1RmpvY1lmb2wxZDc6MTpjaQ"
REDIRECT_URI = "http://127.0.0.1:8787/callback"
SCOPES = "tweet.read tweet.write users.read offline.access"


def build_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")


def build_code_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def build_auth_url(verifier: str, state: str) -> str:
    challenge = build_code_challenge(verifier)
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return "https://x.com/i/oauth2/authorize?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def parse_auth_code(raw: str) -> str:
    raw = raw.strip()
    if "code=" in raw:
        parsed = urllib.parse.urlparse(raw)
        return (urllib.parse.parse_qs(parsed.query).get("code") or [""])[0]
    return raw


def fetch_token(auth_code: str, verifier: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "code": auth_code,
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    ).encode()

    req = urllib.request.Request("https://api.x.com/2/oauth2/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"token 取得失敗: HTTP {e.code}\n{body}")


def save_secret(path: str, token: dict) -> str:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    if not access_token:
        raise SystemExit(f"access_token が見つかりませんでした:\n{json.dumps(token, ensure_ascii=False)}")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'export X_ACCESS_TOKEN="{access_token}"\n')
        if refresh_token:
            f.write(f'export X_REFRESH_TOKEN="{refresh_token}"\n')

    os.chmod(path, 0o600)
    return path


class CallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, expected_state: str, done_state: dict, *args, **kwargs):
        self._expected_state = expected_state
        self._done_state = done_state
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args):  # noqa: A002
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self._send_text(404, "Not found")
            return

        params = urllib.parse.parse_qs(parsed.query)
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


def _start_callback_server(expected_state: str) -> tuple[HTTPServer, threading.Event, dict]:
    done: dict[str, object] = {"event": threading.Event()}

    class Handler(CallbackHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(expected_state, done, *args, **kwargs)

    server = HTTPServer(("127.0.0.1", 8787), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, done["event"], done


def _wait_for_callback(state: str) -> str:
    print("2) ブラウザで許可すると、127.0.0.1:8787 で code を受け取ります。")
    print("   30秒以内に許可しない場合は、URLを手動貼り付けで入力します。")

    try:
        server, done_event, shared = _start_callback_server(state)
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


def main() -> None:
    verifier = build_code_verifier()
    state = secrets.token_urlsafe(16)
    auth_url = build_auth_url(verifier, state)

    print("1) 下記をブラウザで開いて認可してください:")
    print(auth_url)
    print()
    webbrowser.open(auth_url, new=1, autoraise=True)

    auth_code = _wait_for_callback(state)

    token = fetch_token(auth_code, verifier)
    out = save_secret(os.path.expanduser("~/.secrets/x-agent-manager"), token)
    print(f"保存しました: {out}")


if __name__ == "__main__":
    main()
