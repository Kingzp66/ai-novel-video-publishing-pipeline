import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Callable


class PipelineError(Exception):
    """Raised when the project cannot be processed safely."""


DEFAULT_CONFIG = {
    "project_name": "",
    "video_mode": "vertical",
    "resolution": "1080x1920",
    "fps": 30,
    "generate_images": True,
    "generate_voice": True,
    "burn_subtitles": True,
    "use_background_music": True,
    "style_prefix": "",
    "replicate_model": "",
    "voice_name": "",
    "voice_id": "",
    "voice_provider": "elevenlabs",
    "edge_tts_voice": "en-US-GuyNeural",
    "edge_tts_rate": "+0%",
    "edge_tts_volume": "+0%",
    "output_filename": "final_video.mp4",
    "force_regenerate": False,
    "image_retries": 3,
    "voice_retries": 3,
    "retry_delay_seconds": 2,
    "background_music_volume": 0.18,
    "voice_volume": 1.0,
    "sfx_volume": 0.8,
    "subtitle_font_size": 9,
    "subtitle_margin_v": 95,
    "subtitle_outline": 1.4,
}

REQUIRED_SCENE_COLUMNS = {
    "scene_id",
    "start_time",
    "end_time",
    "image_file",
    "motion_type",
    "prompt",
    "sfx",
}

SUPPORTED_MOTIONS = {"zoom_in", "zoom_out", "pan_left", "pan_right", "slow_push"}


def project_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def validate_project_folder(project: Path) -> None:
    if not project.exists():
        raise PipelineError(f"Project folder does not exist: {project}")
    if not project.is_dir():
        raise PipelineError(f"Project path is not a folder: {project}")

    required_files = ["script.txt", "config.json", "image_prompts.csv"]
    missing = [name for name in required_files if not (project / name).is_file()]
    if missing:
        raise PipelineError(f"Missing required project file(s): {', '.join(missing)}")


def ensure_project_directories(project: Path) -> None:
    for name in ["generated_images", "generated_audio", "generated_subtitles", "logs", "output"]:
        (project / name).mkdir(parents=True, exist_ok=True)


def load_config(project: Path) -> dict[str, Any]:
    config_path = project / "config.json"
    try:
        with config_path.open("r", encoding="utf-8") as file:
            user_config = json.load(file)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Invalid JSON in {config_path}: {exc}") from exc

    if not isinstance(user_config, dict):
        raise PipelineError("config.json must contain a JSON object.")

    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    if not config["project_name"]:
        config["project_name"] = project.name
    return config


def parse_seconds(value: str, field_name: str, row_number: int) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"Row {row_number}: {field_name} must be a number.") from exc
    if seconds < 0:
        raise PipelineError(f"Row {row_number}: {field_name} cannot be negative.")
    return seconds


def load_scenes(project: Path) -> list[dict[str, Any]]:
    csv_path = project / "image_prompts.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_SCENE_COLUMNS - columns)
        if missing:
            raise PipelineError(f"image_prompts.csv is missing column(s): {', '.join(missing)}")

        scenes: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):
            start_time = parse_seconds(row.get("start_time", ""), "start_time", row_number)
            end_time = parse_seconds(row.get("end_time", ""), "end_time", row_number)
            if end_time <= start_time:
                raise PipelineError(f"Row {row_number}: end_time must be greater than start_time.")

            motion_type = (row.get("motion_type") or "slow_push").strip()
            if motion_type not in SUPPORTED_MOTIONS:
                raise PipelineError(
                    f"Row {row_number}: unsupported motion_type '{motion_type}'. "
                    f"Use one of: {', '.join(sorted(SUPPORTED_MOTIONS))}."
                )

            image_file = (row.get("image_file") or "").strip()
            prompt = (row.get("prompt") or "").strip()
            if not image_file:
                raise PipelineError(f"Row {row_number}: image_file is required.")
            if not prompt:
                raise PipelineError(f"Row {row_number}: prompt is required.")

            scenes.append(
                {
                    "scene_id": (row.get("scene_id") or str(len(scenes) + 1)).strip(),
                    "start_time": start_time,
                    "end_time": end_time,
                    "image_file": image_file,
                    "motion_type": motion_type,
                    "prompt": prompt,
                    "sfx": (row.get("sfx") or "").strip(),
                }
            )

    if not scenes:
        raise PipelineError("image_prompts.csv must contain at least one scene row.")
    return scenes


def resolve_image_path(project: Path, image_file: str) -> Path:
    path = Path(image_file)
    if path.is_absolute():
        return path
    existing_project_path = project / path
    if existing_project_path.exists():
        return existing_project_path
    return project / "generated_images" / path.name


def read_text_file(path: Path) -> str:
    if not path.is_file():
        raise PipelineError(f"Missing text file: {path}")
    return path.read_text(encoding="utf-8").strip()


def append_log(project: Path, log_name: str, message: str) -> None:
    ensure_project_directories(project)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_path = project / "logs" / log_name
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def retry(operation: Callable[[], Any], retries: int, delay_seconds: float, label: str) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - surfaced with friendly context
            last_error = exc
            if attempt < retries:
                time.sleep(delay_seconds)
    raise PipelineError(f"{label} failed after {retries} attempt(s): {last_error}") from last_error


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()
