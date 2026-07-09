from pathlib import Path
import argparse

import youtube12_pipeline as pipeline


ROOT = Path(r"D:\ai-novel-video-generator\youtube14 JIG")
SCENE_SENTENCE_RANGES = [
    (0, 2), (2, 4), (4, 7),
    (7, 9), (9, 10), (10, 12), (12, 13),
    (13, 14), (14, 16), (16, 17), (17, 18),
    (18, 19), (19, 21), (21, 24), (24, 25),
    (25, 29), (29, 30), (30, 31),
    (31, 33), (33, 36), (36, 37),
    (37, 39), (39, 40), (40, 42),
    (42, 44), (44, 45), (45, 46),
    (46, 48), (48, 49), (49, 51),
    (51, 54), (54, 55), (55, 57), (57, 58),
]


def build_video_no_subtitles() -> None:
    output = ROOT / "output"
    clips = pipeline.build_clips()
    concat_list = output / "clips.txt"
    concat_list.write_text(
        "\n".join(f"file '{clip.as_posix()}'" for clip in clips) + "\n",
        encoding="utf-8",
    )
    video_only = output / "video_only.mp4"
    voice = ROOT / "audio" / "voiceover_brian.mp3"
    music = output / "ambient_music.mp3"
    no_sub = output / "final_youtube_video_no_subtitles.mp4"
    voice_duration = pipeline.probe_duration(voice)

    pipeline.run([
        str(pipeline.FFMPEG), "-y", "-loglevel", "error", "-f", "concat",
        "-safe", "0", "-i", str(concat_list), "-c", "copy", str(video_only),
    ])
    pipeline.run([
        str(pipeline.FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        f"anoisesrc=color=brown:amplitude=0.055:duration={voice_duration + 2}",
        "-f", "lavfi", "-i",
        f"sine=frequency=73:sample_rate=48000:duration={voice_duration + 2}",
        "-filter_complex",
        "[0:a]lowpass=f=950,volume=0.16[a0];[1:a]volume=0.018[a1];"
        "[a0][a1]amix=inputs=2:duration=longest,afade=t=in:st=0:d=3,"
        f"afade=t=out:st={max(0, voice_duration - 5):.3f}:d=5",
        "-c:a", "libmp3lame", "-b:a", "128k", str(music),
    ])
    pipeline.run([
        str(pipeline.FFMPEG), "-y", "-loglevel", "error", "-i", str(video_only),
        "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex",
        "[1:a]volume=1.0[a1];[2:a]volume=0.18[a2];"
        "[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-shortest", str(no_sub),
    ])
    print(no_sub)


if __name__ == "__main__":
    pipeline.ROOT = ROOT
    pipeline.PKG = ROOT
    pipeline.SCENE_SENTENCE_RANGES = SCENE_SENTENCE_RANGES
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "audio", "video", "video-no-sub", "audit-images"])
    args = parser.parse_args()
    if args.step == "video-no-sub":
        build_video_no_subtitles()
    else:
        import sys
        sys.argv = [sys.argv[0], args.step]
        pipeline.main()
