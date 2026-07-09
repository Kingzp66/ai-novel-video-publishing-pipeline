import argparse
import csv
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

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


REQUIRED_COLUMNS = {"platform", "title", "description", "hashtags", "file_path", "scheduled_time"}
FORBIDDEN_COLUMNS = {"password", "cookie", "cookies", "session", "sessionid"}
PLATFORM_ALIASES = {
    "youtube": "youtube",
    "youtube shorts": "youtube",
    "shorts": "youtube",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "instagram reels": "instagram",
    "reels": "instagram",
    "facebook": "facebook",
    "facebook reels": "facebook",
}
PLATFORM_IDENTIFIERS = {
    "youtube": {"youtube"},
    "tiktok": {"tiktok"},
    "instagram": {"instagram", "instagram-standalone"},
    "facebook": {"facebook"},
}
PROVIDER_SETTINGS = {
    "youtube": {
        "__type": "youtube",
        "type": "public",
        "selfDeclaredMadeForKids": "no",
        "thumbnail": None,
        "tags": [],
    },
    "tiktok": {
        "__type": "tiktok",
        "title": "",
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "duet": False,
        "stitch": False,
        "comment": True,
        "autoAddMusic": "no",
        "brand_content_toggle": False,
        "brand_organic_toggle": False,
        "video_made_with_ai": False,
        "content_posting_method": "DIRECT_POST",
    },
    "instagram": {
        "__type": "instagram",
        "post_type": "post",
        "is_trial_reel": False,
        "collaborators": [],
    },
    "facebook": {
        "__type": "facebook",
    },
}

logging.getLogger("publish_videos").addHandler(logging.NullHandler())


@dataclass(frozen=True)
class PublishRow:
    platform: str
    title: str
    description: str
    hashtags: str
    video_path: Path
    scheduled_time: str

    @property
    def content(self) -> str:
        parts = [self.description.strip(), self.hashtags.strip()]
        return "\n\n".join(part for part in parts if part)


@dataclass(frozen=True)
class WorkflowResult:
    previewed: int = 0
    published: int = 0
    failed: int = 0


class PostizClient:
    def __init__(self, api_key: str, base_url: str = "https://api.postiz.com/public/v1"):
        if not api_key:
            raise ValueError("Missing POSTIZ_API_KEY.")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": api_key})

    def list_integrations(self) -> List[Dict[str, object]]:
        response = self.session.get(f"{self.base_url}/integrations", timeout=30)
        response.raise_for_status()
        return response.json()

    def upload_file(self, video_path: Path) -> Dict[str, str]:
        with video_path.open("rb") as file:
            response = self.session.post(
                f"{self.base_url}/upload",
                files={"file": (video_path.name, file, "video/mp4")},
                timeout=120,
            )
        response.raise_for_status()
        data = response.json()
        return {"id": data["id"], "path": data["path"]}

    def create_post(self, payload: Dict[str, object]) -> Dict[str, object]:
        response = self.session.post(f"{self.base_url}/posts", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def schedule_video(self, row: PublishRow, integration: Dict[str, str]) -> Dict[str, object]:
        media = self.upload_file(row.video_path)
        return self.create_post(
            build_post_payload(
                row,
                integration_id=integration["id"],
                media=media,
                provider_type=integration.get("identifier"),
            )
        )


def normalize_platform(value: str) -> str:
    platform = PLATFORM_ALIASES.get(value.strip().lower())
    if not platform:
        allowed = ", ".join(sorted({"youtube", "tiktok", "instagram", "facebook"}))
        raise ValueError(f"Unsupported platform '{value}'. Allowed platforms: {allowed}.")
    return platform


def load_metadata(metadata_path: Path, videos_dir: Path) -> List[PublishRow]:
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.csv not found: {metadata_path}")

    with metadata_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        forbidden = columns & FORBIDDEN_COLUMNS
        if forbidden:
            raise ValueError(f"Forbidden credential columns are not allowed: {', '.join(sorted(forbidden))}")
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"metadata.csv is missing required columns: {', '.join(sorted(missing))}")

        rows = []
        for index, raw in enumerate(reader, start=2):
            platform = normalize_platform(raw["platform"])
            video_path = resolve_video_path(raw["file_path"], videos_dir)
            if not video_path.exists():
                raise FileNotFoundError(f"Row {index} video file not found: {video_path}")
            rows.append(
                PublishRow(
                    platform=platform,
                    title=raw["title"].strip(),
                    description=raw["description"].strip(),
                    hashtags=raw["hashtags"].strip(),
                    video_path=video_path,
                    scheduled_time=to_utc_iso(raw["scheduled_time"].strip()),
                )
            )
    return rows


def resolve_video_path(file_path: str, videos_dir: Path) -> Path:
    path = Path(file_path.strip())
    if not path.is_absolute():
        path = videos_dir / path
    return path.resolve()


def to_utc_iso(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid scheduled_time '{value}'. Use ISO format, for example 2026-07-08T10:00:00-04:00.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_post_payload(
    row: PublishRow,
    integration_id: str,
    media: Dict[str, str],
    provider_type: Optional[str] = None,
) -> Dict[str, object]:
    settings = dict(PROVIDER_SETTINGS[row.platform])
    if provider_type:
        settings["__type"] = provider_type
    if row.platform == "youtube":
        settings["title"] = row.title
        settings["tags"] = split_hashtags(row.hashtags)
    if row.platform == "tiktok":
        settings["title"] = row.title

    return {
        "type": "schedule",
        "date": row.scheduled_time,
        "shortLink": False,
        "tags": [],
        "posts": [
            {
                "integration": {"id": integration_id},
                "value": [{"content": row.content, "image": [media]}],
                "settings": settings,
            }
        ],
    }


def split_hashtags(hashtags: str) -> List[str]:
    return [tag.lstrip("#") for tag in hashtags.replace(",", " ").split() if tag.strip()]


def resolve_integration(platform: str, integrations: Iterable[Dict[str, object]]) -> Dict[str, str]:
    env_name = f"POSTIZ_{platform.upper()}_INTEGRATION_ID"
    explicit_id = os.environ.get(env_name)
    if explicit_id:
        return {"id": explicit_id, "identifier": platform}

    allowed_identifiers = PLATFORM_IDENTIFIERS[platform]
    matches = [
        {"id": str(integration["id"]), "identifier": str(integration.get("identifier", platform)).lower()}
        for integration in integrations
        if str(integration.get("identifier", "")).lower() in allowed_identifiers and not integration.get("disabled")
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No active Postiz integration found for platform '{platform}'. Set {env_name}.")
    raise ValueError(f"Multiple Postiz integrations found for platform '{platform}'. Set {env_name}.")


def resolve_integration_id(platform: str, integrations: Iterable[Dict[str, object]]) -> str:
    return resolve_integration(platform, integrations)["id"]


def run_workflow(
    metadata_path: Path,
    videos_dir: Path,
    dry_run: bool,
    client: Optional[object] = None,
    logger: Optional[logging.Logger] = None,
) -> WorkflowResult:
    logger = logger or logging.getLogger("publish_videos")
    rows = load_metadata(metadata_path, videos_dir)

    if dry_run:
        for row in rows:
            logger.info(
                "DRY RUN platform=%s title=%s file=%s scheduled=%s",
                row.platform,
                row.title,
                row.video_path,
                row.scheduled_time,
            )
        return WorkflowResult(previewed=len(rows))

    if client is None:
        client = PostizClient(
            api_key=os.environ.get("POSTIZ_API_KEY", ""),
            base_url=os.environ.get("POSTIZ_BASE_URL", "https://api.postiz.com/public/v1"),
        )

    integrations = client.list_integrations()
    published = 0
    failed = 0
    for row in rows:
        try:
            integration = resolve_integration(row.platform, integrations)
            response = client.schedule_video(row, integration)
            published += 1
            logger.info("Scheduled %s '%s' with Postiz response: %s", row.platform, row.title, response)
        except Exception as exc:
            failed += 1
            logger.error("Failed to schedule %s '%s': %s", row.platform, row.title, exc)
    return WorkflowResult(published=published, failed=failed)


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("publish_videos")
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
    parser = argparse.ArgumentParser(description="Schedule short videos through Postiz.")
    parser.add_argument("--metadata", default="videos/metadata.csv", type=Path)
    parser.add_argument("--videos-dir", default="videos", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-file", default="logs/publishing.log", type=Path)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    logger = setup_logging(args.log_file)
    try:
        result = run_workflow(args.metadata, args.videos_dir, args.dry_run, logger=logger)
    except Exception as exc:
        logger.error("Publishing workflow failed: %s", exc)
        return 1

    print(json.dumps(result.__dict__, indent=2))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
