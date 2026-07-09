# README_Codex.md

This package contains the metadata needed to test automatic publishing for one short video: `short_01`.

## Files Codex should read

Codex should read these files:

- `metadata/metadata.csv`
- `metadata/publishing_plan.json`
- `metadata/platform_checklist.md`
- `metadata/codex_prompt.txt`

A duplicate copy of `metadata.csv` and `publishing_plan.json` is also included in the project root for convenience.

## Where to put the video file

Place the final rendered vertical video here:

```text
videos/short_01.mp4
```

Place the thumbnail or cover image here:

```text
thumbnails/short_01.jpg
```

If the thumbnail is not ready, the script should still support upload using the video frame selected by the target platform when possible.

## metadata.csv column guide

- `video_id`: Unique ID for this video.
- `video_file`: Relative path to the video file.
- `thumbnail_file`: Relative path to the thumbnail or cover file.
- `platforms`: Semicolon-separated target platforms.
- `youtube_title`: YouTube Shorts title.
- `youtube_description`: YouTube description.
- `youtube_tags`: Comma-separated YouTube tags.
- `youtube_hashtags`: Hashtags for YouTube description/title usage.
- `youtube_category`: Suggested YouTube category.
- `youtube_made_for_kids`: Boolean-like value, usually `false` for general fishing content.
- `tiktok_caption`: TikTok caption.
- `tiktok_hashtags`: TikTok hashtags.
- `instagram_caption`: Instagram Reels caption.
- `instagram_hashtags`: Instagram hashtags.
- `instagram_cover_text`: Suggested cover text for editing or thumbnail design.
- `facebook_caption`: Facebook Reels caption.
- `facebook_hashtags`: Facebook hashtags.
- `privacy_status`: Suggested privacy status. For testing, use `private` where supported.
- `schedule_time`: Optional scheduled posting time. Empty means no schedule time was provided.
- `timezone`: Timezone for scheduling.
- `allow_comments`: Whether comments should be allowed when the platform supports it.
- `status`: Internal workflow status.

## Pre-publish checks

Before publishing, validate:

1. The video file exists at `videos/short_01.mp4`.
2. The video is vertical 9:16.
3. The video length is under 3 minutes.
4. Metadata fields are present and not accidentally duplicated.
5. Captions and hashtags are platform-appropriate.
6. Schedule time is either empty or valid ISO 8601 / platform-supported format.
7. API credentials are available from `.env`.
8. Dry-run mode is enabled for the first test.

## Authentication rules

Do not use account passwords, cookies, browser-login scraping, or manual session tokens.

Use only one of the following:

- Official platform APIs
- Postiz API
- Upload-Post API
- n8n workflow with OAuth credentials
- Make workflow with OAuth credentials
- Other OAuth-based publishing tools

Store API keys and OAuth tokens in `.env`, not inside CSV or JSON files.

Example `.env` variable names:

```text
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_ACCESS_TOKEN=
META_APP_ID=
META_APP_SECRET=
META_ACCESS_TOKEN=
POSTIZ_API_KEY=
UPLOAD_POST_API_KEY=
```

## Dry-run mode

The publishing script must support dry-run mode.

In dry-run mode, Codex should:

- Read all files.
- Validate all metadata.
- Validate video file path and basic format.
- Print or save the planned platform posts.
- Generate `logs/dry_run_report.json`.
- Not publish anything.

## Error handling

If one platform fails:

- Record the platform, error message, and timestamp in `logs/errors.log`.
- Continue to the next platform if safe.
- Do not retry endlessly.
- Use a maximum of 2 retries per platform.
- Generate a final report after the run.
