import argparse
import gc
import json
import time
from pathlib import Path


ROOT = Path(r"D:\ai-novel-video-generator\youtube short1 bass")
MODEL = Path(r"D:\ai-novel-video-generator\models\sdxl-base-1.0")
NEGATIVE = (
    "text, letters, captions, subtitles, logo, watermark, readable signs, black card, title card, "
    "extra fingers, deformed hands, distorted face, duplicate person, cropped face, blurry, low quality, "
    "cartoon, anime, abstract, surreal, overexposed, underexposed"
)


def build_prompt(raw: str) -> str:
    return (
        "Vertical 9:16 cinematic fishing documentary still, realistic polished editorial image, "
        "natural lake environment, dramatic but believable lighting, detailed water and fishing gear, "
        "same focused male angler character, mid-30s, light skin, short dark hair, trimmed beard, "
        "unbranded olive waterproof jacket, dark unbranded baseball cap, tan fishing vest, black waders, "
        "graphite spinning rod, centered subject, open lower safe area for subtitles, no text. "
        + raw
    )[:3900]


def iter_missing(short_id: str | None):
    root = ROOT / "output" / "shorts"
    for manifest_path in sorted(root.glob("short_*/short_*_manifest.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if short_id and data["short_id"] != short_id:
            continue
        folder = manifest_path.parent / "images"
        folder.mkdir(parents=True, exist_ok=True)
        for scene in data["scenes"]:
            out = folder / scene["image"]
            if out.exists() and out.stat().st_size > 0:
                continue
            yield data["short_id"], scene, out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--short-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--first-missing-per-short", action="store_true")
    args = parser.parse_args()

    import torch
    from diffusers import StableDiffusionXLPipeline
    from PIL import Image

    jobs = list(iter_missing(args.short_id))
    if args.first_missing_per_short:
        first_jobs = []
        seen = set()
        for job in jobs:
            if job[0] in seen:
                continue
            seen.add(job[0])
            first_jobs.append(job)
        jobs = first_jobs
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"missing jobs: {len(jobs)}", flush=True)
    if not jobs:
        return

    gc.collect()
    torch.cuda.empty_cache()
    pipe = StableDiffusionXLPipeline.from_pretrained(
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

    for global_index, (short_id, scene, out) in enumerate(jobs, start=1):
        started = time.time()
        scene_index = int(scene["index"])
        seed = 812000 + int(short_id.split("_")[1]) * 100 + scene_index
        generator = torch.Generator("cpu").manual_seed(seed)
        image = pipe(
            prompt=build_prompt(scene["visual_prompt"]),
            negative_prompt=NEGATIVE,
            width=768,
            height=1344,
            num_inference_steps=24,
            guidance_scale=6.2,
            generator=generator,
        ).images[0]
        image = image.resize((1080, 1920), Image.Resampling.LANCZOS)
        image.save(out, "PNG", optimize=True)
        print(f"{global_index}/{len(jobs)} saved {out} in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
