from pathlib import Path
from typing import Any
from urllib.request import urlopen

from utils import PipelineError, append_log, env_value, resolve_image_path, retry


def build_image_prompt(config: dict[str, Any], scene: dict[str, Any]) -> str:
    style_prefix = str(config.get("style_prefix", "")).strip()
    prompt = scene["prompt"].strip()
    return f"{style_prefix}, {prompt}" if style_prefix else prompt


def normalize_replicate_output(output: Any) -> Any:
    if isinstance(output, list) and output:
        return output[0]
    return output


def save_replicate_output(output: Any, destination: Path) -> None:
    output = normalize_replicate_output(output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(output, bytes):
        destination.write_bytes(output)
        return

    if hasattr(output, "read"):
        destination.write_bytes(output.read())
        return

    if isinstance(output, str):
        if output.startswith(("http://", "https://")):
            with urlopen(output) as response:  # noqa: S310 - expected user/API URL
                destination.write_bytes(response.read())
            return
        source = Path(output)
        if source.is_file():
            destination.write_bytes(source.read_bytes())
            return

    raise PipelineError("Replicate returned an unsupported image output format.")


def run_replicate_model(model: str, prompt: str, project: Path) -> Any:
    token = env_value("REPLICATE_API_TOKEN")
    if not token:
        raise PipelineError("Missing REPLICATE_API_TOKEN. Add it to .env or your environment.")
    if not model:
        raise PipelineError("Missing replicate_model in config.json.")

    try:
        import replicate
    except ImportError as exc:
        raise PipelineError("Missing Python package: replicate. Run pip install -r requirements.txt.") from exc

    reference_path = project / "reference" / "main_character.png"
    model_input: dict[str, Any] = {"prompt": prompt}
    if reference_path.is_file():
        # Extension point: add image-to-image/reference parameters here for models that support them.
        model_input["reference_image_path"] = str(reference_path)
    return replicate.run(model, input=model_input)


def generate_missing_images(project: Path, config: dict[str, Any], scenes: list[dict[str, Any]]) -> list[Path]:
    generated_paths: list[Path] = []
    if not config.get("generate_images", True):
        append_log(project, "image_generation_log.txt", "Image generation disabled by config.")
        return generated_paths

    for scene in scenes:
        image_path = resolve_image_path(project, scene["image_file"])
        force = bool(config.get("force_regenerate", False))
        if image_path.exists() and not force:
            append_log(project, "image_generation_log.txt", f"SKIP scene {scene['scene_id']}: {image_path}")
            continue

        prompt = build_image_prompt(config, scene)

        def operation() -> Any:
            return run_replicate_model(str(config.get("replicate_model", "")), prompt, project)

        try:
            output = retry(
                operation,
                int(config.get("image_retries", 3)),
                float(config.get("retry_delay_seconds", 2)),
                f"Image generation for scene {scene['scene_id']}",
            )
            save_replicate_output(output, image_path)
            generated_paths.append(image_path)
            append_log(project, "image_generation_log.txt", f"OK scene {scene['scene_id']}: {image_path}")
        except Exception as exc:  # noqa: BLE001 - logged and re-raised with scene context
            append_log(project, "image_generation_log.txt", f"FAIL scene {scene['scene_id']}: {exc}")
            raise

    return generated_paths
