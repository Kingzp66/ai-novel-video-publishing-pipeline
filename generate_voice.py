from pathlib import Path
from typing import Any
import asyncio

import requests

from utils import PipelineError, append_log, env_value, read_text_file, retry


DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"


def voice_output_path(project: Path) -> Path:
    return project / "generated_audio" / "voice.mp3"


def use_edge_tts(config: dict[str, Any]) -> bool:
    return str(config.get("voice_provider", "")).strip().lower().replace("-", "_") == "edge_tts"


def resolve_voice_id(config: dict[str, Any]) -> str:
    voice_id = str(config.get("voice_id", "")).strip() or env_value("ELEVENLABS_VOICE_ID")
    if voice_id:
        return voice_id

    voice_name = str(config.get("voice_name", "")).strip()
    if voice_name:
        # ElevenLabs needs an ID for the REST call. Keeping this explicit avoids guessing wrong voices.
        raise PipelineError(
            "config.json has voice_name but no voice_id. Add voice_id, or set ELEVENLABS_VOICE_ID."
        )
    raise PipelineError("Missing ElevenLabs voice_id. Add voice_id to config.json or ELEVENLABS_VOICE_ID.")


def request_elevenlabs_audio(text: str, config: dict[str, Any]) -> bytes:
    api_key = env_value("ELEVENLABS_API_KEY")
    if not api_key:
        raise PipelineError("Missing ELEVENLABS_API_KEY. Add it to .env or your environment.")

    voice_id = resolve_voice_id(config)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": str(config.get("elevenlabs_model", DEFAULT_ELEVENLABS_MODEL)),
        "voice_settings": {
            "stability": float(config.get("voice_stability", 0.45)),
            "similarity_boost": float(config.get("voice_similarity_boost", 0.75)),
        },
    }
    response = requests.post(
        url,
        json=payload,
        headers={
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    if response.status_code >= 400:
        raise PipelineError(f"ElevenLabs error {response.status_code}: {response.text[:300]}")
    return response.content


async def generate_edge_tts_audio_async(text: str, output_path: Path, config: dict[str, Any]) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise PipelineError("Missing Python package: edge-tts. Run pip install edge-tts.") from exc

    voice = str(config.get("edge_tts_voice", "en-US-GuyNeural"))
    rate = str(config.get("edge_tts_rate", "+0%"))
    volume = str(config.get("edge_tts_volume", "+0%"))
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume)
    await communicate.save(str(output_path))


def generate_edge_tts_audio(text: str, output_path: Path, config: dict[str, Any]) -> None:
    asyncio.run(generate_edge_tts_audio_async(text, output_path, config))


def generate_voiceover(project: Path, config: dict[str, Any]) -> Path | None:
    if not config.get("generate_voice", True):
        append_log(project, "voice_generation_log.txt", "Voice generation disabled by config.")
        return None

    script_text = read_text_file(project / "script.txt")
    output_path = voice_output_path(project)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if use_edge_tts(config):
        try:
            retry(
                lambda: generate_edge_tts_audio(script_text, output_path, config),
                int(config.get("voice_retries", 3)),
                float(config.get("retry_delay_seconds", 2)),
                "Edge TTS voice generation",
            )
            append_log(project, "voice_generation_log.txt", f"OK edge-tts voice saved: {output_path}")
            return output_path
        except Exception as exc:  # noqa: BLE001 - logged and re-raised for main summary
            append_log(project, "voice_generation_log.txt", f"FAIL edge-tts voice generation: {exc}")
            raise

    def operation() -> bytes:
        return request_elevenlabs_audio(script_text, config)

    try:
        audio = retry(
            operation,
            int(config.get("voice_retries", 3)),
            float(config.get("retry_delay_seconds", 2)),
            "Voice generation",
        )
        output_path.write_bytes(audio)
        append_log(project, "voice_generation_log.txt", f"OK voice saved: {output_path}")
        return output_path
    except Exception as exc:  # noqa: BLE001 - logged and re-raised for main summary
        append_log(project, "voice_generation_log.txt", f"FAIL voice generation: {exc}")
        raise
