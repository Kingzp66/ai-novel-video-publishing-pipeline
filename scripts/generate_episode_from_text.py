"""
Create prompts/episode_01.json from one story prompt.

This first version uses a local template instead of calling a large language
model API. The generated JSON keeps the same shape expected by the video,
subtitle, voiceover, and assembly scripts.
"""

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EPISODE_PATH = PROJECT_ROOT / "prompts" / "episode_01.json"

CHARACTER_PROMPT = (
    "Maya Lin, a realistic young Asian woman, 19 years old, messy black hair "
    "in a loose ponytail, oversized gray hoodie, black shorts, barefoot, tired "
    "but determined eyes, ordinary student look, no makeup."
)

STYLE_PROMPT = (
    "cinematic realistic, apocalyptic survival, dramatic lighting, high detail, "
    "vertical 9:16."
)

NEGATIVE_PROMPT = (
    "no fantasy armor, no perfect makeup, no glamorous model look, no anime style, "
    "no extra fingers, no distorted hands, no duplicate character, no different "
    "outfit, no futuristic weapon."
)


SCENE_BEATS = [
    (
        "A global survival game notification flashes across every screen.",
        "A dark world map covered in emergency alerts, phones and billboards glowing with a survival game announcement",
    ),
    (
        "Maya Lin is selected while sitting alone in her ordinary dorm room.",
        "Maya Lin startled in a messy student dorm room as a red selection light appears around her",
    ),
    (
        "In a blink, she wakes on the shore of a hostile deserted island.",
        "Maya Lin lying on wet sand beside black rocks and broken waves under a stormy sky",
    ),
    (
        "Millions of viewers laugh at her bare feet and oversized hoodie.",
        "Floating livestream comments mocking Maya Lin as she stands barefoot on the island shore",
    ),
    (
        "The system labels her the weakest lord candidate on the island.",
        "A cold game interface ranking Maya Lin at the bottom while jungle shadows rise behind her",
    ),
    (
        "Maya studies the forest instead of answering the crowd.",
        "Close-up of Maya Lin's tired but determined eyes looking toward a dense apocalyptic forest",
    ),
    (
        "A distant roar rolls out from behind the trees.",
        "The forest entrance shaking with unseen danger, birds scattering, Maya Lin standing small in the foreground",
    ),
    (
        "She finds a sharp shell and wraps it in torn cloth.",
        "Maya Lin crouching by the shore, making a simple survival tool from a shell and torn gray hoodie cloth",
    ),
    (
        "The comments turn crueler as she steps away from the safe beach.",
        "Maya Lin walking away from the beach while translucent audience comments swarm around her",
    ),
    (
        "At the forest edge, she hears something whisper her name.",
        "Maya Lin at the dark jungle threshold, leaves moving as if whispering her name",
    ),
    (
        "She takes one breath and chooses the forest.",
        "Maya Lin stepping barefoot into the shadowed forest, dramatic light behind her, survival resolve",
    ),
    (
        "Behind her, the first island trial begins to awaken.",
        "The beach and forest glowing with hidden game symbols as the first survival trial activates",
    ),
]


def clean_prompt_pack_text(text):
    """Clean common mojibake characters from exported prompt pack files."""
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "鈥?": "-",
        "鈥檚": "'s",
        "鈥檛": "n't",
        "鈥檝": "'v",
        "鈥淣": '"N',
        "鈥淔": '"F',
        "鈥淪": '"S',
        "鈥淗": '"H',
        "鈥淲": '"W',
        "鈥淢": '"M',
        "鈥淚": '"I',
    }

    for bad_text, good_text in replacements.items():
        text = text.replace(bad_text, good_text)

    return text


def extract_field(text, label, default=""):
    """Extract the first non-empty line after a label such as Project:."""
    match = re.search(rf"{re.escape(label)}\s*\n?([^\n]+)", text)
    if not match:
        return default

    return match.group(1).strip().strip(":")


def extract_block(text, start_label, end_label, default=""):
    """Extract a block of text between two labels."""
    pattern = rf"{re.escape(start_label)}\s*(.*?)(?={re.escape(end_label)})"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return default

    return "\n".join(line.strip() for line in match.group(1).strip().splitlines() if line.strip())


def extract_short_voiceover(text):
    """Extract the 60-second voiceover section from a prompt pack."""
    pattern = (
        r"5\.\s*SHORTER 60-SECOND VOICEOVER VERSION\s*=+\s*"
        r"(.*?)"
        r"\s*=+\s*6\.\s*SCENE-BY-SCENE VIDEO PROMPTS"
    )
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return ""

    return "\n".join(line.strip() for line in match.group(1).strip().splitlines() if line.strip())


def extract_prompt_pack_scenes(text):
    """Extract scene captions and visual prompts from a prompt pack."""
    scene_pattern = (
        r"Scene\s+(\d+):\s*(.*?)\n"
        r"-+\s*"
        r"Visual Prompt:\s*(.*?)\s*"
        r"Text on Screen:\s*(.*?)\s*"
        r"Sound:"
    )
    matches = re.findall(scene_pattern, text, flags=re.DOTALL | re.IGNORECASE)
    scenes = []

    for scene_id_text, scene_title, visual_prompt, caption in matches:
        scene_id = int(scene_id_text)
        clean_visual_prompt = " ".join(visual_prompt.strip().split())
        clean_caption = " ".join(caption.strip().split())
        if not clean_caption:
            clean_caption = scene_title.strip()

        scenes.append(
            {
                "id": scene_id,
                "duration": 5,
                "caption": clean_caption,
                "prompt": clean_visual_prompt,
            }
        )

    return scenes


def combine_scene_prompt(scene_visual):
    """Merge story, character, style, and negative guidance for one video model prompt."""
    return (
        f"{scene_visual}. {CHARACTER_PROMPT} {STYLE_PROMPT} "
        f"Avoid: {NEGATIVE_PROMPT}"
    )


def build_episode_from_prompt(story_prompt):
    """Build a complete episode dictionary from a user's story prompt."""
    scenes = []
    for scene_id, (caption, scene_visual) in enumerate(SCENE_BEATS, start=1):
        scenes.append(
            {
                "id": scene_id,
                "duration": 5,
                "caption": caption,
                "prompt": combine_scene_prompt(scene_visual),
            }
        )

    voiceover = (
        "Maya Lin was supposed to be ordinary. But when the Apocalypse Lord Game "
        "selected her for Island One, the whole world watched and laughed. She had "
        "no armor, no weapon, and no allies. Only a gray hoodie, bare feet, and one "
        "choice: stay on the beach and be hunted, or walk into the forest first."
    )

    return {
        "title": "Apocalypse Lord Game",
        "episode_title": "Episode 01",
        "aspect_ratio": "9:16",
        "source_prompt": story_prompt,
        "voiceover": voiceover,
        "character_prompt": CHARACTER_PROMPT,
        "style_prompt": STYLE_PROMPT,
        "negative_prompt": NEGATIVE_PROMPT,
        "scenes": scenes,
    }


def build_episode_from_prompt_pack(prompt_pack_text):
    """Build an episode dictionary from a structured prompt pack text file."""
    text = clean_prompt_pack_text(prompt_pack_text)
    title = extract_field(text, "Project:", default="Untitled AI Video")
    episode_title = extract_field(text, "Episode 1:", default="Episode 01")
    character_prompt = extract_block(
        text,
        "AI Image/Video Character Prompt:",
        "Negative Prompt:",
        default=CHARACTER_PROMPT,
    )
    negative_prompt = extract_block(
        text,
        "Negative Prompt:",
        "============================================================",
        default=NEGATIVE_PROMPT,
    )
    voiceover = extract_short_voiceover(text) or build_episode_from_prompt(text)["voiceover"]
    scenes = extract_prompt_pack_scenes(text)
    if not scenes:
        scenes = build_episode_from_prompt(text)["scenes"]

    return {
        "title": title,
        "episode_title": episode_title,
        "aspect_ratio": "9:16",
        "source_prompt": title,
        "voiceover": voiceover,
        "character_prompt": character_prompt,
        "style_prompt": STYLE_PROMPT,
        "negative_prompt": negative_prompt,
        "scenes": scenes,
    }


def write_episode_json(episode, output_path):
    """Write a formatted episode JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(episode, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv=None):
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Generate episode_01.json from a story prompt.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--prompt", help="Story prompt for the episode.")
    source_group.add_argument("--prompt-pack", help="Path to a structured prompt pack text file.")
    return parser.parse_args(argv)


def main(argv=None):
    """Create prompts/episode_01.json from --prompt."""
    args = parse_args(argv)
    if args.prompt_pack:
        prompt_pack_path = Path(args.prompt_pack)
        prompt_pack_text = prompt_pack_path.read_text(encoding="utf-8")
        episode = build_episode_from_prompt_pack(prompt_pack_text)
    else:
        episode = build_episode_from_prompt(args.prompt)

    write_episode_json(episode, EPISODE_PATH)
    print(f"Created episode JSON: {EPISODE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
