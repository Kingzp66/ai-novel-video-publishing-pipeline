import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils import PipelineError, append_log, resolve_image_path


@dataclass
class PlannedScene:
    scene_id: str
    image_path: Path
    duration: float
    motion_type: str
    sfx: str


@dataclass
class VideoPlan:
    project: Path
    output_path: Path
    temp_dir: Path
    width: int
    height: int
    fps: int
    burn_subtitles: bool
    scenes: list[PlannedScene]


def parse_resolution(value: str) -> tuple[int, int]:
    cleaned = str(value).lower().replace(" ", "")
    if "x" not in cleaned:
        raise PipelineError("resolution must look like 1080x1920 or 1920x1080.")
    width_text, height_text = cleaned.split("x", 1)
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise PipelineError("resolution width and height must be numbers.") from exc
    if width <= 0 or height <= 0:
        raise PipelineError("resolution width and height must be positive.")
    return width, height


def build_video_plan(project: Path, config: dict[str, Any], scenes: list[dict[str, Any]]) -> VideoPlan:
    width, height = parse_resolution(str(config.get("resolution", "1080x1920")))
    output_name = str(config.get("output_filename", "final_video.mp4")).strip() or "final_video.mp4"
    planned_scenes = [
        PlannedScene(
            scene_id=str(scene["scene_id"]),
            image_path=resolve_image_path(project, scene["image_file"]),
            duration=float(scene["end_time"]) - float(scene["start_time"]),
            motion_type=str(scene["motion_type"]),
            sfx=str(scene.get("sfx", "")),
        )
        for scene in scenes
    ]
    return VideoPlan(
        project=project,
        output_path=project / "output" / output_name,
        temp_dir=project / "output" / "_clips",
        width=width,
        height=height,
        fps=int(config.get("fps", 30)),
        burn_subtitles=bool(config.get("burn_subtitles", True)),
        scenes=planned_scenes,
    )


def run_command(command: list[str], label: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PipelineError(f"{label} failed:\n{detail}")


def zoompan_expression(motion_type: str, width: int, height: int, frames: int) -> str:
    base_scale = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase"
    crop = f"crop={width}:{height}"
    if motion_type == "zoom_out":
        zoom = "z='if(eq(on,1),1.18,max(1.0,zoom-0.0015))'"
        x = "x='iw/2-(iw/zoom/2)'"
        y = "y='ih/2-(ih/zoom/2)'"
    elif motion_type == "pan_left":
        zoom = "z='1.12'"
        x = f"x='(iw-iw/zoom)*(1-on/{frames})'"
        y = "y='ih/2-(ih/zoom/2)'"
    elif motion_type == "pan_right":
        zoom = "z='1.12'"
        x = f"x='(iw-iw/zoom)*on/{frames}'"
        y = "y='ih/2-(ih/zoom/2)'"
    else:
        zoom = "z='min(1.18,1+on*0.0015)'"
        x = "x='iw/2-(iw/zoom/2)'"
        y = "y='ih/2-(ih/zoom/2)'"
    zoompan = f"zoompan={zoom}:d={frames}:s={width}x{height}:fps=30:{x}:{y}"
    return f"{base_scale},{crop},{zoompan},format=yuv420p"


def render_scene_clip(ffmpeg: str, plan: VideoPlan, scene: PlannedScene, index: int) -> Path:
    if not scene.image_path.is_file():
        raise PipelineError(f"Missing image for scene {scene.scene_id}: {scene.image_path}")

    frames = max(1, int(round(scene.duration * plan.fps)))
    output_path = plan.temp_dir / f"scene_{index:03}.mp4"
    command = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(scene.image_path),
        "-frames:v",
        str(frames),
        "-vf",
        zoompan_expression(scene.motion_type, plan.width, plan.height, frames).replace(":fps=30", f":fps={plan.fps}"),
        "-an",
        "-r",
        str(plan.fps),
        str(output_path),
    ]
    run_command(command, f"Render scene {scene.scene_id}")
    return output_path


def write_concat_file(clips: list[Path], concat_path: Path) -> None:
    lines = []
    for clip in clips:
        safe_path = clip.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_clips(ffmpeg: str, clips: list[Path], output_path: Path) -> None:
    concat_path = output_path.with_suffix(".txt")
    write_concat_file(clips, concat_path)
    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(output_path),
    ]
    run_command(command, "Concat scene clips")


def subtitle_filter_path(path: Path) -> str:
    text = path.resolve().as_posix()
    return text.replace(":", "\\:")


def build_audio_inputs(project: Path, config: dict[str, Any], scenes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    inputs: list[str] = []
    filters: list[str] = []
    audio_labels: list[str] = []

    def add_audio(path: Path, filter_chain: str) -> None:
        if not path.is_file():
            return
        input_index = 1 + len(inputs) // 2
        inputs.extend(["-i", str(path)])
        label = f"a{len(audio_labels)}"
        filters.append(f"[{input_index}:a]{filter_chain}[{label}]")
        audio_labels.append(f"[{label}]")

    voice_path = project / "generated_audio" / "voice.mp3"
    add_audio(voice_path, f"volume={float(config.get('voice_volume', 1.0))}")

    music_path = project / "music" / "background.mp3"
    if config.get("use_background_music", True):
        add_audio(music_path, f"volume={float(config.get('background_music_volume', 0.18))}")

    for scene in scenes:
        sfx_name = str(scene.get("sfx", "")).strip()
        if not sfx_name:
            continue
        sfx_path = project / "sfx" / sfx_name
        delay_ms = int(float(scene["start_time"]) * 1000)
        add_audio(sfx_path, f"adelay={delay_ms}|{delay_ms},volume={float(config.get('sfx_volume', 0.8))}")

    if audio_labels:
        filters.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0[mixed]")
    return inputs, filters


def mux_audio_and_subtitles(
    ffmpeg: str,
    project: Path,
    config: dict[str, Any],
    scenes: list[dict[str, Any]],
    video_path: Path,
    output_path: Path,
) -> None:
    command = [ffmpeg, "-y", "-i", str(video_path)]
    audio_inputs, audio_filters = build_audio_inputs(project, config, scenes)
    command.extend(audio_inputs)

    subtitle_path = project / "generated_subtitles" / "subtitles.srt"
    video_filters = []
    if config.get("burn_subtitles", True) and subtitle_path.is_file():
        font_size = float(config.get("subtitle_font_size", 9))
        margin_v = int(config.get("subtitle_margin_v", 95))
        outline = float(config.get("subtitle_outline", 1.4))
        style = (
            "FontName=Arial,"
            f"FontSize={font_size},"
            "PrimaryColour=&HFFFFFF,"
            "OutlineColour=&H000000,"
            f"Outline={outline},"
            "Alignment=2,"
            f"MarginV={margin_v}"
        )
        video_filters.append(f"subtitles='{subtitle_filter_path(subtitle_path)}':force_style='{style}'")

    filter_complex_parts = audio_filters[:]
    if video_filters:
        filter_complex_parts.append(f"[0:v]{','.join(video_filters)}[vout]")

    if filter_complex_parts:
        command.extend(["-filter_complex", ";".join(filter_complex_parts)])
        command.extend(["-map", "[vout]" if video_filters else "0:v"])
        if audio_filters:
            command.extend(["-map", "[mixed]"])
    else:
        command.extend(["-map", "0:v"])

    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if audio_filters:
        command.extend(["-c:a", "aac"])
    else:
        command.append("-an")
    command.append(str(output_path))
    run_command(command, "Final mux")


def warn_if_voice_duration_differs(project: Path, ffprobe: str, scenes: list[dict[str, Any]]) -> None:
    voice_path = project / "generated_audio" / "voice.mp3"
    if not voice_path.is_file():
        return
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(voice_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return
    try:
        voice_duration = float(result.stdout.strip())
    except ValueError:
        return
    scene_duration = max(float(scene["end_time"]) for scene in scenes)
    if abs(voice_duration - scene_duration) > 5:
        append_log(
            project,
            "video_render_log.txt",
            f"WARNING voice length ({voice_duration:.1f}s) differs from scene timeline ({scene_duration:.1f}s).",
        )


def render_video(project: Path, config: dict[str, Any], scenes: list[dict[str, Any]]) -> Path:
    ffmpeg = str(config.get("ffmpeg_path", "ffmpeg"))
    ffprobe = str(config.get("ffprobe_path", "ffprobe"))
    plan = build_video_plan(project, config, scenes)
    plan.temp_dir.mkdir(parents=True, exist_ok=True)
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)

    clips = [render_scene_clip(ffmpeg, plan, scene, index) for index, scene in enumerate(plan.scenes, start=1)]
    silent_video = plan.temp_dir / "silent_video.mp4"
    concat_clips(ffmpeg, clips, silent_video)
    warn_if_voice_duration_differs(project, ffprobe, scenes)
    mux_audio_and_subtitles(ffmpeg, project, config, scenes, silent_video, plan.output_path)
    append_log(project, "video_render_log.txt", f"OK final video saved: {plan.output_path}")
    return plan.output_path
