import argparse
import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

from dotenv import load_dotenv
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCHNELL_MODEL = "black-forest-labs/flux-schnell"
KONTEXT_MODEL = "black-forest-labs/flux-kontext-pro"


def build_kontext_prompt(image_prompt: str, scene_number: int) -> str:
    return (
        f"Create a new horizontal 16:9 scene {scene_number:02d} based on the reference image. "
        "Preserve the same hand-drawn editorial stick-figure doodle style, line weight, "
        "warm off-white paper texture, muted teal, dusty-blue, mustard and light-gray palette, "
        "and recurring character identity whenever that character appears. "
        f"Follow this scene direction exactly: {image_prompt} "
        "Show only the people required by the scene. Keep the setting complete but uncluttered, "
        "with important faces and actions above the lower fifth and the lower 18 percent quiet "
        "for English subtitles. Avoid anime, chibi, generic vector clipart, thick smooth outlines, "
        "oversized heads, photorealism, 3D, glossy rendering, gradients, text, letters, logos, "
        "watermarks and subtitles."
    )


def build_model_input(prompt: str, reference_image: Path, seed: int) -> dict[str, object]:
    return {
        "prompt": prompt,
        "input_image": reference_image,
        "aspect_ratio": "16:9",
        "output_format": "png",
        "prompt_upsampling": False,
        "seed": seed,
    }


def normalize_png(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        image = image.convert("RGB")
        image = image.resize((1920, 1080), Image.Resampling.LANCZOS)
        image.save(target, "PNG", optimize=True)


def save_output(output, target: Path) -> None:
    if isinstance(output, list):
        output = output[0]
    temp = target.with_suffix(".tmp")
    if hasattr(output, "read"):
        temp.write_bytes(output.read())
    elif isinstance(output, str) and output.startswith(("http://", "https://")):
        with urlopen(output) as response:  # noqa: S310
            temp.write_bytes(response.read())
    elif isinstance(output, str):
        temp.write_bytes(Path(output).read_bytes())
    else:
        raise TypeError(f"Unsupported output: {type(output)!r}")
    normalize_png(temp, target)
    temp.unlink(missing_ok=True)


def resolve_project(value: str) -> Path:
    project = Path(value)
    if not project.is_absolute():
        project = ROOT / project
    return project.resolve()


def find_prompts(project: Path) -> Path:
    candidates = [
        project / "image_prompts.jsonl",
        *sorted(project.glob("*_image_prompts.jsonl")),
        *sorted(project.glob("*_prompts.jsonl")),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing image prompts JSONL in {project}")


def load_prompts(path: Path) -> list[dict[str, str]]:
    prompts = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                prompts.append(json.loads(line))
    return prompts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate horizontal YouTube scene images.")
    parser.add_argument("--project", default="youtube1", help="Project folder path, absolute or relative to repo root.")
    parser.add_argument("--reference-image", help="Project-relative image used to lock style and recurring characters.")
    parser.add_argument("--regenerate-from", type=int, default=0, help="Overwrite images from this scene number onward.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project = resolve_project(args.project)
    images = project / "images"
    prompts_path = find_prompts(project)

    load_dotenv(ROOT / ".env")
    if not os.environ.get("REPLICATE_API_TOKEN"):
        raise SystemExit("Missing REPLICATE_API_TOKEN in .env or environment.")

    import replicate

    images.mkdir(parents=True, exist_ok=True)
    prompts = load_prompts(prompts_path)
    reference_image = project / args.reference_image if args.reference_image else None
    if reference_image and not reference_image.exists():
        raise FileNotFoundError(f"Missing reference image: {reference_image}")

    for index, item in enumerate(prompts, start=1):
        target = images / f"scene_{index:02}.png"
        should_overwrite = bool(args.regenerate_from and index >= args.regenerate_from)
        if target.exists() and not should_overwrite:
            print(f"skip {target.name}")
            continue
        if reference_image:
            model = KONTEXT_MODEL
            prompt = build_kontext_prompt(item["image_prompt"], index)
            model_input = build_model_input(prompt, reference_image, seed=400 + index)
        else:
            model = SCHNELL_MODEL
            prompt = item["image_prompt"] + ", keep lower caption area clean and uncluttered"
            model_input = {
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "output_format": "png",
                "output_quality": 95,
                "num_outputs": 1,
                "num_inference_steps": 4,
                "go_fast": True,
            }
        print(f"generate {target.name}")
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                output = replicate.run(model, input=model_input)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                wait = 12 * attempt
                print(f"retry {target.name} in {wait}s: {exc}")
                time.sleep(wait)
        else:
            raise RuntimeError(f"Failed to generate {target.name}: {last_error}") from last_error
        save_output(output, target)
        print(f"saved {target}")
        time.sleep(1 if reference_image else 11)


if __name__ == "__main__":
    main()
