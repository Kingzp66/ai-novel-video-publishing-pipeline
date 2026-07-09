import argparse
import csv
import gc
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "sdxl-base-1.0"
NEGATIVE_PROMPT = (
    "text, letters, captions, logo, watermark, photorealistic, 3d, anime, chibi, "
    "thick vector lines, duplicate people, deformed, blurry, low quality"
)


def scene_filename(number: int) -> str:
    return f"scene_{number:02d}.png"


def build_prompt(image_prompt: str) -> str:
    scene = image_prompt.split("Scene:", 1)[-1].strip()
    return (
        "hand-drawn editorial stick-figure doodle, thin imperfect black ink, round white faces, "
        "dot eyes, flat muted teal blue mustard gray, warm paper background, detailed clean setting, "
        f"16:9 educational story scene: {scene}"
    )


def resolve_project(value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def find_prompts(project: Path) -> Path:
    candidates = [
        project / "scenes.csv",
        *sorted(project.glob("*_prompts.csv")),
        *sorted(project.glob("*.csv")),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing prompts CSV in {project}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate YouTube scene images with local SDXL.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    import torch
    from diffusers import StableDiffusionXLImg2ImgPipeline
    from PIL import Image

    args = parse_args()
    project = resolve_project(args.project)
    reference = project / args.reference
    images = project / "images"
    images.mkdir(parents=True, exist_ok=True)

    with find_prompts(project).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    end = min(args.end or len(rows), len(rows))

    gc.collect()
    torch.cuda.empty_cache()
    pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
        MODEL,
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.enable_sequential_cpu_offload()
    pipe.enable_attention_slicing("max")
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()

    init_image = Image.open(reference).convert("RGB").resize((768, 432), Image.Resampling.LANCZOS)
    for number in range(args.start, end + 1):
        target = images / scene_filename(number)
        if target.exists() and not args.overwrite:
            print(f"skip {target.name}", flush=True)
            continue

        started = time.time()
        result = pipe(
            prompt=build_prompt(rows[number - 1]["image_prompt"]),
            negative_prompt=NEGATIVE_PROMPT,
            image=init_image,
            strength=0.68,
            guidance_scale=7.0,
            num_inference_steps=30,
            generator=torch.Generator("cpu").manual_seed(5600 + number),
            width=768,
            height=432,
        ).images[0]
        result.resize((1920, 1080), Image.Resampling.LANCZOS).save(target, "PNG", optimize=True)
        print(f"saved {target.name} in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
