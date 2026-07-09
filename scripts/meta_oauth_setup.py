import argparse
import os
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


GRAPH_VERSION = "v20.0"
AUTH_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts"]


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


class OAuthResult:
    code: Optional[str] = None
    error: Optional[str] = None


def build_authorization_url(
    app_id: str,
    redirect_uri: str,
    scopes: List[str],
    state: Optional[str] = None,
) -> Tuple[str, str]:
    state = state or secrets.token_urlsafe(24)
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": ",".join(scopes),
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", state


def exchange_code_for_short_lived_token(
    app_id: str,
    app_secret: str,
    code: str,
    redirect_uri: str,
    session: Optional[object] = None,
) -> Dict[str, object]:
    session = session or requests.Session()
    response = session.get(
        f"{GRAPH_URL}/oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def exchange_for_long_lived_token(
    app_id: str,
    app_secret: str,
    short_lived_token: str,
    session: Optional[object] = None,
) -> Dict[str, object]:
    session = session or requests.Session()
    response = session.get(
        f"{GRAPH_URL}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_lived_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_page_access_token(
    user_access_token: str,
    page_id: str = "",
    page_name: str = "",
    session: Optional[object] = None,
) -> Dict[str, str]:
    session = session or requests.Session()
    response = session.get(
        f"{GRAPH_URL}/me/accounts",
        params={"access_token": user_access_token, "fields": "id,name,access_token,tasks"},
        timeout=30,
    )
    response.raise_for_status()
    pages = response.json().get("data", [])
    for page in pages:
        if page_id and str(page.get("id")) == page_id:
            return page
        if page_name and str(page.get("name", "")).lower() == page_name.lower():
            return page
    names = ", ".join(f"{page.get('name')} ({page.get('id')})" for page in pages)
    raise ValueError(f"Could not find requested Facebook Page. Available Pages: {names}")


def request_authorization_code(app_id: str, scopes: List[str], no_browser: bool, timeout_seconds: int) -> Tuple[str, str]:
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

            message = b"Meta authorization received. You can close this browser tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback/"
    authorization_url, state = build_authorization_url(app_id, redirect_uri, scopes)
    print("Open this URL to authorize Facebook Page API access:")
    print(authorization_url)
    if not no_browser:
        webbrowser.open(authorization_url)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    server.server_close()
    if result.error:
        raise RuntimeError(f"Authorization failed: {result.error}")
    if not result.code:
        raise TimeoutError("Timed out waiting for Meta OAuth callback.")
    return result.code, redirect_uri


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize Meta Pages API access and save Page token to .env.")
    parser.add_argument("--app-id")
    parser.add_argument("--app-secret")
    parser.add_argument("--page-id", default="")
    parser.add_argument("--page-name", default="")
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--scope", default=",".join(DEFAULT_SCOPES))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout-seconds", default=900, type=int)
    args = parser.parse_args()

    load_dotenv(str(args.env_file))
    app_id = args.app_id or os.environ.get("META_APP_ID", "")
    app_secret = args.app_secret or os.environ.get("META_APP_SECRET", "")
    page_id = args.page_id or os.environ.get("FACEBOOK_PAGE_ID", "")
    page_name = args.page_name or os.environ.get("FACEBOOK_PAGE_NAME", "")
    if not app_id:
        raise ValueError("Missing Meta app id. Pass --app-id or set META_APP_ID in .env.")
    if not app_secret:
        raise ValueError("Missing Meta app secret. Pass --app-secret or set META_APP_SECRET in .env.")
    if not page_id and not page_name:
        raise ValueError("Missing Facebook Page. Pass --page-id/--page-name or set FACEBOOK_PAGE_ID/FACEBOOK_PAGE_NAME in .env.")

    scopes = [scope.strip() for scope in args.scope.split(",") if scope.strip()]
    code, redirect_uri = request_authorization_code(app_id, scopes, args.no_browser, args.timeout_seconds)
    short_token = exchange_code_for_short_lived_token(app_id, app_secret, code, redirect_uri)
    long_token = exchange_for_long_lived_token(app_id, app_secret, short_token["access_token"])
    page = get_page_access_token(
        user_access_token=long_token["access_token"],
        page_id=page_id,
        page_name=page_name,
    )
    write_env_values(
        args.env_file,
        {
            "META_APP_ID": app_id,
            "META_APP_SECRET": app_secret,
            "META_ACCESS_TOKEN": long_token["access_token"],
            "FACEBOOK_PAGE_ID": str(page["id"]),
            "FACEBOOK_PAGE_NAME": str(page.get("name", "")),
            "FACEBOOK_PAGE_ACCESS_TOKEN": str(page["access_token"]),
        },
    )
    print(f"Saved Meta OAuth and Facebook Page values to {args.env_file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
