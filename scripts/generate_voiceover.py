"""
Generate narration audio from prompts/episode_01.json using ElevenLabs.

The script reads the episode's voiceover text, loads ElevenLabs credentials from
.env, and writes assets/audio/voiceover.mp3.
"""

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EPISODE_PATH = PROJECT_ROOT / "prompts" / "episode_01.json"
AUDIO_PATH = PROJECT_ROOT / "assets" / "audio" / "voiceover.mp3"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def load_voiceover_text(episode_path):
    """Read the narration text from an episode JSON file."""
    with episode_path.open("r", encoding="utf-8") as file:
        episode = json.load(file)

    return episode["voiceover"].strip()


def load_environment():
    """Load .env values when python-dotenv is installed."""
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")


def generate_voiceover_audio(text, api_key, voice_id, output_path):
    """Call ElevenLabs and save the returned MP3 audio."""
    import requests

    response = requests.post(
        ELEVENLABS_URL.format(voice_id=voice_id),
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        params={"output_format": "mp3_44100_128"},
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
        },
        timeout=120,
    )
    response.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)


def main():
    """Generate assets/audio/voiceover.mp3 from the episode voiceover."""
    load_environment()

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("Missing ELEVENLABS_API_KEY. Add it to .env before generating voiceover audio.")
        return 1

    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    if not voice_id:
        print("Missing ELEVENLABS_VOICE_ID. Add it to .env before generating voiceover audio.")
        return 1

    text = load_voiceover_text(EPISODE_PATH)
    generate_voiceover_audio(text, api_key, voice_id, AUDIO_PATH)

    print(f"Created voiceover: {AUDIO_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
