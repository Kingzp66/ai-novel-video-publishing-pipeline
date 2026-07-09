import argparse
import json
import os
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Optional

import requests


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


class OAuthResult:
    code: Optional[str] = None
    error: Optional[str] = None


def load_client_config(client_secret_path: Path) -> Dict[str, str]:
    data = json.loads(client_secret_path.read_text(encoding="utf-8"))
    config = data.get("installed") or data.get("web")
    if not config:
        raise ValueError("Client secret JSON must contain an 'installed' or 'web' section.")
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("Client secret JSON is missing client_id or client_secret.")
    return {"client_id": client_id, "client_secret": client_secret}


def request_authorization_code(client_id: str, no_browser: bool = False) -> str:
    result = OAuthResult()
    state = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result.error = "OAuth state mismatch."
            elif "error" in query:
                result.error = query["error"][0]
            else:
                result.code = query.get("code", [None])[0]

            message = b"YouTube authorization received. You can close this browser tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("localhost", 0), Handler)
    redirect_uri = f"http://localhost:{server.server_port}/"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    authorization_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("Open this URL to authorize YouTube API access:")
    print(authorization_url)
    if not no_browser:
        webbrowser.open(authorization_url)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=300)
    server.server_close()

    if result.error:
        raise RuntimeError(f"Authorization failed: {result.error}")
    if not result.code:
        raise TimeoutError("Timed out waiting for Google OAuth callback.")
    return result.code


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Dict[str, str]:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "refresh_token" not in data:
        raise RuntimeError("Google did not return a refresh token. Revoke the app grant and run again with prompt=consent.")
    return data


def write_env_values(env_path: Path, values: Dict[str, str]) -> None:
    existing = {}
    lines = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key = line.split("=", 1)[0]
                existing[key] = True
                if key in values:
                    lines.append(f"{key}={values[key]}")
                else:
                    lines.append(line)
            else:
                lines.append(line)

    for key, value in values.items():
        if key not in existing:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize YouTube Data API upload access and save refresh token to .env.")
    parser.add_argument("--client-secret", required=True, type=Path)
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout-seconds", default=900, type=int)
    args = parser.parse_args()

    config = load_client_config(args.client_secret)
    server = HTTPServer(("localhost", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://localhost:{server.server_port}/"
    server.server_close()

    result = OAuthResult()
    state = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result.error = "OAuth state mismatch."
            elif "error" in query:
                result.error = query["error"][0]
            else:
                result.code = query.get("code", [None])[0]

            message = b"YouTube authorization received. You can close this browser tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

        def log_message(self, format, *args):
            return

    auth_server = HTTPServer(("localhost", int(urllib.parse.urlparse(redirect_uri).port)), Handler)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    authorization_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("Open this URL to authorize YouTube API access:")
    print(authorization_url)
    if not args.no_browser:
        webbrowser.open(authorization_url)

    thread = threading.Thread(target=auth_server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=args.timeout_seconds)
    auth_server.server_close()
    if result.error:
        raise RuntimeError(f"Authorization failed: {result.error}")
    if not result.code:
        raise TimeoutError("Timed out waiting for Google OAuth callback.")

    tokens = exchange_code_for_tokens(config["client_id"], config["client_secret"], result.code, redirect_uri)
    write_env_values(
        args.env_file,
        {
            "YOUTUBE_CLIENT_ID": config["client_id"],
            "YOUTUBE_CLIENT_SECRET": config["client_secret"],
            "YOUTUBE_REFRESH_TOKEN": tokens["refresh_token"],
        },
    )
    print(f"Saved YouTube OAuth values to {args.env_file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
