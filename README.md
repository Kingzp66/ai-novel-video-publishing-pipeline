# AI Story Video Generator

This project is a reusable Python pipeline for generating a complete story video from one project folder.

You only change the project folder path when starting a new video:

```powershell
python main.py --project "projects/police_file_story"
```

## Folder Structure

Each video project should use this structure:

```text
projects/
  police_file_story/
    script.txt
    subtitle_script.txt
    config.json
    image_prompts.csv
    music/
      background.mp3
    sfx/
      hit.mp3
      buzz.mp3
    reference/
      main_character.png
```

Required files:

- `script.txt`: full narration script.
- `config.json`: project settings.
- `image_prompts.csv`: scene timings, image names, motion, prompts, and optional sound effects.

Optional files:

- `subtitle_script.txt`: subtitle text. If missing, the pipeline uses `script.txt`.
- `music/background.mp3`: background music.
- `sfx/*.mp3`: sound effects listed in `image_prompts.csv`.
- `reference/main_character.png`: reserved extension point for future reference-based image generation.

## config.json

Example:

```json
{
  "project_name": "Police File Story",
  "video_mode": "vertical",
  "resolution": "1080x1920",
  "fps": 30,
  "generate_images": true,
  "generate_voice": true,
  "burn_subtitles": true,
  "use_background_music": true,
  "style_prefix": "cinematic, realistic, dramatic lighting",
  "replicate_model": "owner/model",
  "voice_name": "Rachel",
  "voice_id": "your-elevenlabs-voice-id",
  "output_filename": "final_video.mp4",
  "force_regenerate": false
}
```

Notes:

- `replicate_model` is configurable and not hardcoded.
- ElevenLabs REST calls need a `voice_id`. `voice_name` is kept for readability.
- Set `force_regenerate` to `true` to recreate images even if files already exist.

## image_prompts.csv

Required columns:

```csv
scene_id,start_time,end_time,image_file,motion_type,prompt,sfx
1,0,5,scene_001.png,zoom_in,A detective opens a cold case folder,
2,5,10,scene_002.png,pan_left,A dark hallway with flickering lights,buzz.mp3
```

Supported `motion_type` values:

- `zoom_in`
- `zoom_out`
- `pan_left`
- `pan_right`
- `slow_push`

Images are saved to:

```text
PROJECT_FOLDER/generated_images/
```

If an image already exists, it is skipped unless `force_regenerate` is `true`.

## Environment

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Make sure FFmpeg works:

```powershell
ffmpeg -version
```

Set API keys in `.env` or your system environment:

```text
REPLICATE_API_TOKEN=your_replicate_token
ELEVENLABS_API_KEY=your_elevenlabs_key
ELEVENLABS_VOICE_ID=optional_default_voice_id
```

## Run The Pipeline

From this repository folder:

```powershell
python main.py --project "projects/police_file_story"
```

For another video, only change the folder name:

```powershell
python main.py --project "projects/another_project_name"
```

The program will:

1. Validate the project folder.
2. Create missing output directories.
3. Load `config.json`.
4. Read `image_prompts.csv`.
5. Generate missing images with Replicate.
6. Generate narration with ElevenLabs.
7. Create `subtitles.srt`.
8. Render animated Ken Burns clips.
9. Mix narration, background music, and sound effects.
10. Export the final video.

## Outputs

Generated files are saved inside the project folder:

```text
PROJECT_FOLDER/
  generated_images/
  generated_audio/
    voice.mp3
  generated_subtitles/
    subtitles.srt
  output/
    final_video.mp4
    _clips/
  logs/
    image_generation_log.txt
    voice_generation_log.txt
    video_render_log.txt
```

## Logs

Logs are written to:

```text
PROJECT_FOLDER/logs/
```

Use these files when a generation step fails or when FFmpeg reports an error.

## Auto-Publish Short Videos With Postiz

The repository includes a Postiz-based publishing workflow for finished short videos. It reads video files from `videos/`, reads publishing metadata from `videos/metadata.csv`, and schedules posts through the Postiz Public API.

This workflow uses API keys or Postiz OAuth-managed integrations only. It does not use cookies, browser sessions, or password-based social platform login.

### metadata.csv

Create `videos/metadata.csv` with these columns:

```csv
platform,title,description,hashtags,file_path,scheduled_time
youtube,My YouTube Short,Short description,#ai #story,clip1.mp4,2026-07-08T10:00:00-04:00
tiktok,My TikTok,Short description,#ai #story,clip2.mp4,2026-07-08T11:00:00-04:00
instagram,My Reel,Short description,#ai #story,clip3.mp4,2026-07-08T12:00:00-04:00
facebook,My Facebook Reel,Short description,#ai #story,clip4.mp4,2026-07-08T13:00:00-04:00
```

Supported `platform` values:

- `youtube` or `youtube shorts`
- `tiktok`
- `instagram` or `instagram reels`
- `facebook` or `facebook reels`

`file_path` can be relative to `videos/` or an absolute path. `scheduled_time` should be ISO format with a timezone offset.

### Environment

Set your Postiz API key in `.env` or your shell:

```text
POSTIZ_API_KEY=your_postiz_api_key
POSTIZ_BASE_URL=https://api.postiz.com/public/v1
```

If you have multiple connected accounts for one platform, set explicit integration IDs:

```text
POSTIZ_YOUTUBE_INTEGRATION_ID=your-youtube-integration-id
POSTIZ_TIKTOK_INTEGRATION_ID=your-tiktok-integration-id
POSTIZ_INSTAGRAM_INTEGRATION_ID=your-instagram-integration-id
POSTIZ_FACEBOOK_INTEGRATION_ID=your-facebook-integration-id
```

If these are not set, the script asks Postiz for connected integrations and uses the single active integration whose identifier matches the platform. Instagram supports both Postiz `instagram` and `instagram-standalone` integrations.

### Preview Before Publishing

Always run a dry-run first:

```powershell
.\.venv-sdxl\Scripts\python.exe scripts\publish_videos.py --dry-run
```

Dry-run validates the CSV and video files, converts scheduled times to UTC, and logs what would be scheduled without uploading or publishing anything.

### Publish

After reviewing the dry-run output:

```powershell
.\.venv-sdxl\Scripts\python.exe scripts\publish_videos.py
```

Optional paths:

```powershell
.\.venv-sdxl\Scripts\python.exe scripts\publish_videos.py `
  --metadata videos\metadata.csv `
  --videos-dir videos `
  --log-file logs\publishing.log
```

Publishing uploads each MP4 to Postiz, creates a scheduled post, and keeps processing later rows if one row fails. Logs are written to `logs/publishing.log`.

## Auto-Publish With Official Platform APIs

If you do not want to use Postiz, use the official API workflow:

```powershell
.\.venv-sdxl\Scripts\python.exe scripts\publish_videos_official.py --dry-run
```

Then publish due rows:

```powershell
.\.venv-sdxl\Scripts\python.exe scripts\publish_videos_official.py
```

By default, rows whose `scheduled_time` is in the future are skipped. To publish every row immediately:

```powershell
.\.venv-sdxl\Scripts\python.exe scripts\publish_videos_official.py --publish-all
```

This uses the same `videos/metadata.csv` format as the Postiz workflow.

### Official API Environment

YouTube Shorts uses the YouTube Data API resumable upload flow:

```text
YOUTUBE_CLIENT_ID=your-google-oauth-client-id
YOUTUBE_CLIENT_SECRET=your-google-oauth-client-secret
YOUTUBE_REFRESH_TOKEN=your-authorized-refresh-token
YOUTUBE_CATEGORY_ID=24
YOUTUBE_PRIVACY_STATUS=public
```

TikTok uses the Content Posting API direct post flow. Your TikTok developer app must be approved for the needed posting scope:

```text
TIKTOK_ACCESS_TOKEN=your-user-access-token
TIKTOK_PRIVACY_LEVEL=PUBLIC_TO_EVERYONE
```

Instagram Reels and Facebook Reels use Meta Graph API:

```text
META_ACCESS_TOKEN=your-meta-access-token
INSTAGRAM_USER_ID=your-instagram-business-or-creator-user-id
FACEBOOK_PAGE_ID=your-facebook-page-id
FACEBOOK_PAGE_ACCESS_TOKEN=your-facebook-page-access-token
PUBLIC_VIDEO_BASE_URL=https://your-public-cdn.example.com/videos
```

Meta publishing APIs generally need a public HTTPS `video_url` that Meta can fetch. The script maps each local `file_path` to:

```text
PUBLIC_VIDEO_BASE_URL/file_name.mp4
```

For example, `file_path` of `clip1.mp4` with `PUBLIC_VIDEO_BASE_URL=https://cdn.example.com/videos` becomes:

```text
https://cdn.example.com/videos/clip1.mp4
```

The official API workflow still avoids cookies, browser sessions, and password-based login. It requires OAuth/API tokens that you obtain through each platform developer setup.

If your website is hosted on Vercel, you can upload Instagram source videos to Vercel Blob before publishing. Create a Blob store in the Vercel project and add these environment variables:

```text
PUBLIC_VIDEO_UPLOAD_PROVIDER=vercel_blob_cli
PUBLIC_VIDEO_UPLOAD_PREFIX=videos
BLOB_READ_WRITE_TOKEN=your-vercel-blob-read-write-token
VERCEL_CLI_COMMAND=vercel
```

With this mode, Instagram publishing uploads the local video first and uses the public Blob URL returned by Vercel. Vercel documents Blob as file storage for images, videos, and other large files, and the CLI supports `vercel blob put` with a read-write token.
