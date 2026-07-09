import csv
import json
import re
from pathlib import Path


ROOT = Path(r"D:\ai-novel-video-generator\youtube6")


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def main() -> None:
    with (ROOT / "poppi_soda_scenes.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    narration = [
        {
            "scene_id": row["scene_id"],
            "scene_title": row["scene_title"],
            "sentences": split_sentences(row["narration"]),
        }
        for row in rows
    ]

    for folder in ("images", "audio", "subtitles", "output"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)

    (ROOT / "narration_en.json").write_text(
        json.dumps(narration, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Prepared {len(narration)} scenes and {sum(len(x['sentences']) for x in narration)} sentences")


if __name__ == "__main__":
    main()
