# Social Auto Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that reads short-video publishing rows from `videos/metadata.csv`, previews them in dry-run mode, and schedules them through Postiz using API/OAuth-based publishing.

**Architecture:** Add one focused script under `scripts/` with CSV parsing, validation, Postiz upload/post creation, logging, and CLI entrypoint. Tests will mock network calls through an injected client so behavior is covered without real publishing.

**Tech Stack:** Python standard library, `requests`, `python-dotenv`, `unittest`.

---

### Task 1: CSV Parsing and Dry Run

**Files:**
- Create: `scripts/publish_videos.py`
- Modify: `tests/test_project.py`

- [x] Write failing tests for CSV parsing and dry-run behavior.
- [x] Run targeted tests to verify they fail because the module does not exist.
- [x] Implement CSV parsing, platform validation, file validation, caption building, and dry-run result reporting.
- [x] Run targeted tests to verify they pass.

### Task 2: Postiz API Publishing

**Files:**
- Modify: `scripts/publish_videos.py`
- Modify: `tests/test_project.py`

- [x] Write failing tests for upload/post payloads and per-row error isolation.
- [x] Run targeted tests to verify expected failures.
- [x] Implement `PostizClient`, integration resolution, media upload, create-post payloads, and error handling.
- [x] Run targeted tests to verify they pass.

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`

- [x] Document `metadata.csv`, environment variables, dry-run, and publishing command.
- [x] Run full test suite.
- [x] Review requirements against implementation.
