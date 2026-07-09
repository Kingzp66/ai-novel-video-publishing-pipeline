import argparse
import json
import logging
import mimetypes
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path: str = ".env") -> bool:
        path = Path(dotenv_path)
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return True

from scripts.publish_videos import PublishRow, load_metadata


YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
GRAPH_BASE_URL = "https://graph.facebook.com/v20.0"

logging.getLogger("publish_videos_official").addHandler(logging.NullHandler())


@dataclass(frozen=True)
class WorkflowResult:
    previewed: int = 0
    published: int = 0
    skipped: int = 0
    failed: int = 0


class YouTubeClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        session: Optional[object] = None,
    ):
        require_env_value("YOUTUBE_CLIENT_ID", client_id)
        require_env_value("YOUTUBE_CLIENT_SECRET", client_secret)
        require_env_value("YOUTUBE_REFRESH_TOKEN", refresh_token)
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = session or requests.Session()

    def refresh_access_token(self) -> str:
        response = self.session.post(
            YOUTUBE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def publish(self, row: PublishRow) -> Dict[str, object]:
        access_token = self.refresh_access_token()
        metadata = {
            "snippet": {
                "title": row.title,
                "description": row.content,
                "tags": split_hashtags(row.hashtags),
                "categoryId": os.environ.get("YOUTUBE_CATEGORY_ID", "24"),
            },
            "status": {
                "privacyStatus": os.environ.get("YOUTUBE_PRIVACY_STATUS", "public"),
                "selfDeclaredMadeForKids": False,
            },
        }
        mime_type = guess_mime_type(row.video_path)
        init_response = self.session.post(
            YOUTUBE_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": mime_type,
                "X-Upload-Content-Length": str(row.video_path.stat().st_size),
            },
            data=json.dumps(metadata),
            timeout=30,
        )
        init_response.raise_for_status()
        upload_url = init_response.headers["Location"]

        with row.video_path.open("rb") as file:
            upload_response = self.session.put(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": mime_type},
                data=file,
                timeout=300,
            )
        upload_response.raise_for_status()
        return upload_response.json()


class TikTokClient:
    def __init__(self, access_token: str, post_mode: str = "publish", session: Optional[object] = None):
        require_env_value("TIKTOK_ACCESS_TOKEN", access_token)
        if post_mode not in {"publish", "upload"}:
            raise ValueError("TIKTOK_POST_MODE must be 'publish' or 'upload'.")
        self.access_token = access_token
        self.post_mode = post_mode
        self.session = session or requests.Session()

    def publish(self, row: PublishRow) -> Dict[str, object]:
        file_size = row.video_path.stat().st_size
        payload: Dict[str, object] = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        }
        init_url = TIKTOK_UPLOAD_INIT_URL
        if self.post_mode == "publish":
            init_url = TIKTOK_INIT_URL
            payload["post_info"] = {
                "title": row.content[:2200],
                "privacy_level": os.environ.get("TIKTOK_PRIVACY_LEVEL", "PUBLIC_TO_EVERYONE"),
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            }
        init_response = self.session.post(
            init_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload,
            timeout=30,
        )
        init_response.raise_for_status()
        data = init_response.json()["data"]

        with row.video_path.open("rb") as file:
            upload_response = self.session.put(
                data["upload_url"],
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                },
                data=file,
                timeout=300,
            )
        upload_response.raise_for_status()
        return {"publish_id": data["publish_id"]}


def refresh_tiktok_access_token(
    client_key: str,
    client_secret: str,
    refresh_token: str,
    session: Optional[object] = None,
) -> Dict[str, str]:
    require_env_value("TIKTOK_CLIENT_KEY", client_key)
    require_env_value("TIKTOK_CLIENT_SECRET", client_secret)
    require_env_value("TIKTOK_REFRESH_TOKEN", refresh_token)
    session = session or requests.Session()
    response = session.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


class InstagramClient:
    def __init__(
        self,
        access_token: str,
        ig_user_id: str,
        public_base_url: str,
        session: Optional[object] = None,
        video_host: Optional[object] = None,
        container_poll_interval: float = 5.0,
        container_poll_timeout: float = 300.0,
    ):
        require_env_value("META_ACCESS_TOKEN", access_token)
        require_env_value("INSTAGRAM_USER_ID", ig_user_id)
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self.public_base_url = public_base_url.rstrip("/")
        self.session = session or requests.Session()
        self.video_host = video_host or StaticPublicVideoHost(self.public_base_url)
        self.container_poll_interval = container_poll_interval
        self.container_poll_timeout = container_poll_timeout

    def publish(self, row: PublishRow) -> Dict[str, object]:
        video_url = self.video_host.video_url(row.video_path)
        container_response = self.session.post(
            f"{GRAPH_BASE_URL}/{self.ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": row.content,
                "access_token": self.access_token,
            },
            timeout=30,
        )
        container_response.raise_for_status()
        creation_id = container_response.json()["id"]
        self._wait_for_container(creation_id)

        publish_response = self.session.post(
            f"{GRAPH_BASE_URL}/{self.ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": self.access_token},
            timeout=30,
        )
        publish_response.raise_for_status()
        return publish_response.json()

    def _wait_for_container(self, creation_id: str) -> None:
        deadline = time.monotonic() + self.container_poll_timeout
        last_status = "UNKNOWN"

        while time.monotonic() < deadline:
            status_response = self.session.get(
                f"{GRAPH_BASE_URL}/{creation_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            status_response.raise_for_status()
            status_payload = status_response.json()
            last_status = status_payload.get("status_code", "UNKNOWN")
            status_message = status_payload.get("status", "")

            if last_status == "FINISHED":
                return
            if last_status == "ERROR":
                raise RuntimeError(
                    f"Instagram media container failed: {creation_id} {status_message}".strip()
                )

            time.sleep(self.container_poll_interval)

        raise TimeoutError(
            f"Instagram media container was not ready after "
            f"{self.container_poll_timeout:.0f}s: {creation_id} ({last_status})"
        )


class FacebookClient:
    def __init__(
        self,
        page_id: str,
        page_access_token: str,
        public_base_url: str = "",
        session: Optional[object] = None,
    ):
        require_env_value("FACEBOOK_PAGE_ID", page_id)
        require_env_value("FACEBOOK_PAGE_ACCESS_TOKEN", page_access_token)
        self.page_id = page_id
        self.page_access_token = page_access_token
        self.public_base_url = public_base_url.rstrip("/")
        self.session = session or requests.Session()

    def publish(self, row: PublishRow) -> Dict[str, object]:
        start_response = self.session.post(
            f"{GRAPH_BASE_URL}/{self.page_id}/video_reels",
            data={
                "upload_phase": "start",
                "access_token": self.page_access_token,
            },
            timeout=30,
        )
        start_response.raise_for_status()
        upload_session = start_response.json()
        video_id = upload_session["video_id"]
        upload_url = upload_session["upload_url"]

        file_size = row.video_path.stat().st_size
        with row.video_path.open("rb") as file:
            upload_response = self.session.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {self.page_access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                },
                data=file,
                timeout=300,
            )
        upload_response.raise_for_status()

        finish_response = self.session.post(
            f"{GRAPH_BASE_URL}/{self.page_id}/video_reels",
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": row.content,
                "access_token": self.page_access_token,
            },
            timeout=30,
        )
        finish_response.raise_for_status()
        return finish_response.json()


def require_env_value(name: str, value: str) -> None:
    if not value:
        raise ValueError(f"Missing {name}.")


def split_hashtags(hashtags: str) -> List[str]:
    return [tag.lstrip("#") for tag in hashtags.replace(",", " ").split() if tag.strip()]


def guess_mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "video/mp4"


def parse_iso_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def public_video_url(public_base_url: str, video_path: Path) -> str:
    require_env_value("PUBLIC_VIDEO_BASE_URL", public_base_url)
    return f"{public_base_url.rstrip('/')}/{quote(video_path.name)}"


class StaticPublicVideoHost:
    def __init__(self, public_base_url: str):
        self.public_base_url = public_base_url

    def video_url(self, video_path: Path) -> str:
        return public_video_url(self.public_base_url, video_path)


class VercelBlobCliVideoHost:
    def __init__(
        self,
        rw_token: str,
        upload_prefix: str = "videos",
        cli_command: str = "vercel",
        runner: object = subprocess.run,
    ):
        require_env_value("BLOB_READ_WRITE_TOKEN", rw_token)
        self.rw_token = rw_token
        self.upload_prefix = upload_prefix.strip("/").replace("\\", "/")
        self.cli_command = cli_command
        self.runner = runner

    def video_url(self, video_path: Path) -> str:
        pathname = f"{self.upload_prefix}/{video_path.name}" if self.upload_prefix else video_path.name
        command = [
            *shlex.split(self.cli_command),
            "blob",
            "put",
            str(video_path),
            "--access",
            "public",
            "--pathname",
            pathname,
            "--content-type",
            guess_mime_type(video_path),
            "--allow-overwrite",
            "--rw-token",
            self.rw_token,
            "--no-color",
            "--non-interactive",
        ]
        result = self.runner(command, capture_output=True, text=True, check=True)
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        match = re.search(r"https://\S+", output)
        if not match:
            raise RuntimeError(f"Vercel Blob upload did not return a public URL: {output.strip()}")
        return match.group(0).rstrip(".,)")


def build_video_host_from_env() -> object:
    provider = os.environ.get("PUBLIC_VIDEO_UPLOAD_PROVIDER", "").strip().lower()
    if provider in {"", "static"}:
        return StaticPublicVideoHost(os.environ.get("PUBLIC_VIDEO_BASE_URL", ""))
    if provider == "vercel_blob_cli":
        return VercelBlobCliVideoHost(
            rw_token=os.environ.get("BLOB_READ_WRITE_TOKEN", ""),
            upload_prefix=os.environ.get("PUBLIC_VIDEO_UPLOAD_PREFIX", "videos"),
            cli_command=os.environ.get("VERCEL_CLI_COMMAND", "vercel"),
        )
    raise ValueError(f"Unsupported PUBLIC_VIDEO_UPLOAD_PROVIDER: {provider}")


def build_clients_from_env(platforms: Optional[List[str]] = None) -> Dict[str, object]:
    public_base_url = os.environ.get("PUBLIC_VIDEO_BASE_URL", "")
    requested = set(platforms or ["youtube", "tiktok", "instagram", "facebook"])
    clients: Dict[str, object] = {}
    if "youtube" in requested:
        clients["youtube"] = YouTubeClient(
            client_id=os.environ.get("YOUTUBE_CLIENT_ID", ""),
            client_secret=os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
            refresh_token=os.environ.get("YOUTUBE_REFRESH_TOKEN", ""),
        )
    if "tiktok" in requested:
        access_token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
        if os.environ.get("TIKTOK_REFRESH_TOKEN"):
            tokens = refresh_tiktok_access_token(
                client_key=os.environ.get("TIKTOK_CLIENT_KEY", ""),
                client_secret=os.environ.get("TIKTOK_CLIENT_SECRET", ""),
                refresh_token=os.environ.get("TIKTOK_REFRESH_TOKEN", ""),
            )
            access_token = tokens.get("access_token", access_token)
        clients["tiktok"] = TikTokClient(
            access_token=access_token,
            post_mode=os.environ.get("TIKTOK_POST_MODE", "publish"),
        )
    if "instagram" in requested:
        clients["instagram"] = InstagramClient(
            access_token=os.environ.get("META_ACCESS_TOKEN", ""),
            ig_user_id=os.environ.get("INSTAGRAM_USER_ID", ""),
            public_base_url=public_base_url,
            video_host=build_video_host_from_env(),
        )
    if "facebook" in requested:
        clients["facebook"] = FacebookClient(
            page_id=os.environ.get("FACEBOOK_PAGE_ID", ""),
            page_access_token=os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", ""),
            public_base_url=public_base_url,
        )
    return clients


def run_workflow(
    metadata_path: Path,
    videos_dir: Path,
    dry_run: bool,
    clients: Optional[Dict[str, object]] = None,
    now: Optional[datetime] = None,
    publish_due_only: bool = True,
    logger: Optional[logging.Logger] = None,
) -> WorkflowResult:
    logger = logger or logging.getLogger("publish_videos_official")
    rows = load_metadata(metadata_path, videos_dir)
    now = now or datetime.now(timezone.utc)

    if dry_run:
        for row in rows:
            due = parse_iso_time(row.scheduled_time) <= now
            logger.info(
                "DRY RUN platform=%s title=%s file=%s scheduled=%s due=%s",
                row.platform,
                row.title,
                row.video_path,
                row.scheduled_time,
                due,
            )
        return WorkflowResult(previewed=len(rows))

    clients = clients or build_clients_from_env(sorted({row.platform for row in rows}))
    published = 0
    skipped = 0
    failed = 0
    for row in rows:
        if publish_due_only and parse_iso_time(row.scheduled_time) > now:
            skipped += 1
            logger.info("Skipped future row platform=%s title=%s scheduled=%s", row.platform, row.title, row.scheduled_time)
            continue
        try:
            client = clients[row.platform]
            response = client.publish(row)
            published += 1
            logger.info("Published %s '%s': %s", row.platform, row.title, response)
        except Exception as exc:
            failed += 1
            logger.error("Failed to publish %s '%s': %s", row.platform, row.title, exc)
    return WorkflowResult(published=published, skipped=skipped, failed=failed)


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("publish_videos_official")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish short videos through official platform APIs.")
    parser.add_argument("--metadata", default="videos/metadata.csv", type=Path)
    parser.add_argument("--videos-dir", default="videos", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish-all", action="store_true", help="Publish rows even when scheduled_time is in the future.")
    parser.add_argument("--log-file", default="logs/official_publishing.log", type=Path)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    logger = setup_logging(args.log_file)
    try:
        result = run_workflow(
            args.metadata,
            args.videos_dir,
            dry_run=args.dry_run,
            publish_due_only=not args.publish_all,
            logger=logger,
        )
    except Exception as exc:
        logger.error("Official publishing workflow failed: %s", exc)
        return 1

    print(json.dumps(result.__dict__, indent=2))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
