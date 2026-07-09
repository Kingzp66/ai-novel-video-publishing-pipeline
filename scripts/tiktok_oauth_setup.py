import argparse
import hashlib
import os
import secrets
import string
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path: str = ".env") -> bool:
        path = Path(dotenv_path)
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return True


AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
DEFAULT_SCOPES = ["user.info.basic", "video.upload"]


class OAuthResult:
    code: Optional[str] = None
    error: Optional[str] = None


def generate_code_verifier(length: int = 64) -> str:
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def code_challenge_from_verifier(code_verifier: str) -> str:
    return hashlib.sha256(code_verifier.encode("utf-8")).hexdigest()


def build_authorization_url(
    client_key: str,
    redirect_uri: str,
    scopes: List[str],
    state: Optional[str] = None,
    code_verifier: Optional[str] = None,
) -> Tuple[str, str, str]:
    state = state or secrets.token_urlsafe(24)
    code_verifier = code_verifier or generate_code_verifier()
    params = {
        "client_key": client_key,
        "scope": ",".join(scopes),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge_from_verifier(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", state, code_verifier


def exchange_code_for_tokens(
    client_key: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    session: Optional[object] = None,
) -> Dict[str, str]:
    session = session or requests.Session()
    response = session.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token response did not include access_token: {data}")
    return data


def write_env_values(env_path: Path, values: Dict[str, str]) -> None:
    existing = {}
    lines = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key = line.split("=", 1)[0]
                existing[key] = True
                lines.append(f"{key}={values[key]}" if key in values else line)
            else:
                lines.append(line)

    for key, value in values.items():
        if key not in existing:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def request_authorization_code(client_key: str, scopes: List[str], no_browser: bool, timeout_seconds: int) -> Tuple[str, str]:
    result = OAuthResult()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result.error = "OAuth state mismatch."
            elif "error" in query:
                result.error = query["error"][0]
            else:
                result.code = query.get("code", [None])[0]

            message = b"TikTok authorization received. You can close this browser tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback/"
    auth_url, state, code_verifier = build_authorization_url(client_key, redirect_uri, scopes)
    print("Open this URL to authorize TikTok API access:")
    print(auth_url)
    if not no_browser:
        webbrowser.open(auth_url)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    server.server_close()
    if result.error:
        raise RuntimeError(f"Authorization failed: {result.error}")
    if not result.code:
        raise TimeoutError("Timed out waiting for TikTok OAuth callback.")
    return result.code, redirect_uri, code_verifier


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize TikTok Content Posting API access and save tokens to .env.")
    parser.add_argument("--client-key")
    parser.add_argument("--client-secret")
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--scope", default=",".join(DEFAULT_SCOPES), help="Comma-separated TikTok scopes.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout-seconds", default=900, type=int)
    args = parser.parse_args()
    load_dotenv(str(args.env_file))
    client_key = args.client_key or os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = args.client_secret or os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not client_key:
        raise ValueError("Missing TikTok client key. Pass --client-key or set TIKTOK_CLIENT_KEY in .env.")
    if not client_secret:
        raise ValueError("Missing TikTok client secret. Pass --client-secret or set TIKTOK_CLIENT_SECRET in .env.")

    scopes = [scope.strip() for scope in args.scope.split(",") if scope.strip()]
    code, redirect_uri, code_verifier = request_authorization_code(
        client_key=client_key,
        scopes=scopes,
        no_browser=args.no_browser,
        timeout_seconds=args.timeout_seconds,
    )
    tokens = exchange_code_for_tokens(
        client_key=client_key,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    values = {
        "TIKTOK_CLIENT_KEY": client_key,
        "TIKTOK_CLIENT_SECRET": client_secret,
        "TIKTOK_ACCESS_TOKEN": tokens["access_token"],
    }
    if tokens.get("refresh_token"):
        values["TIKTOK_REFRESH_TOKEN"] = tokens["refresh_token"]
    write_env_values(args.env_file, values)
    print(f"Saved TikTok OAuth values to {args.env_file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
