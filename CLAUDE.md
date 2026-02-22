# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Dropbox MCP Server — connects Claude Desktop, Cursor, and other AI tools to Dropbox for file management, search, and content operations. Single-file Python server using FastMCP.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Then fill in credentials

# Run (stdio mode — Claude Desktop/Cursor)
python server.py

# Run (SSE mode — remote deployment)
TRANSPORT=sse python server.py   # Starts on 0.0.0.0:8080

# OAuth2 setup (interactive — opens browser)
python auth_helper.py
```

No test suite. No build step. No linting configured.

# Docker
docker build --target production -t dropbox-mcp .   # Build production image
docker build --target development -t dropbox-mcp:dev .  # Build dev image
```

Multi-stage Dockerfile (Python 3.11-slim): builder → development → production. Uses `/opt/venv` virtual environment pattern for non-root user compatibility. Production stage copies only `server.py`. Exposes port 8080, runs in SSE mode by default. Also available via top-level `docker-compose.yml` as `dropbox-mcp` service (host port 8081).

## Architecture

Single module: **`server.py`** (~575 lines) contains everything — FastMCP server, all 11 tools, Dropbox client lifecycle, and helpers.

**Auth flow:** `app_lifespan()` async context manager initializes the `dropbox.Dropbox` client. Prefers OAuth2 refresh token (`DROPBOX_REFRESH_TOKEN` + `APP_KEY` + `APP_SECRET`), falls back to short-lived `DROPBOX_ACCESS_TOKEN`. Client is verified on startup via `users_get_current_account()` and shared via `AppContext` dataclass through `ctx.request_context.lifespan_context.dbx`.

**`auth_helper.py`** — Interactive OAuth2 flow using `DropboxOAuth2FlowNoRedirect` to obtain a refresh token. Outputs credentials for `.env`.

## MCP Tools (11)

| Tool | Description |
|------|-------------|
| `list_files` | Browse directory (supports recursive, pagination up to 2000) |
| `read_file` | Read text files (10MB max, binary files return metadata only) |
| `search_files` | Search by name/content with extension filtering (max 100 results) |
| `write_file` | Create/overwrite files (`overwrite` flag required for existing files) |
| `create_folder` | Create folder with auto-created parents |
| `move_file` | Move or rename files/folders |
| `copy_file` | Copy files/folders |
| `delete_file` | Delete to trash (**requires `confirm=True`**, recoverable 30 days) |
| `get_file_info` | Detailed metadata (size, hash, media info) |
| `get_shared_link` | Get existing or create new public shared link |
| `get_account_info` | Account name, email, storage usage |

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DROPBOX_APP_KEY` | Yes* | Dropbox app key |
| `DROPBOX_APP_SECRET` | Yes* | Dropbox app secret |
| `DROPBOX_REFRESH_TOKEN` | Yes* | OAuth2 refresh token (long-lived) |
| `DROPBOX_ACCESS_TOKEN` | Alt | Short-lived token (4hr, for quick testing) |
| `TRANSPORT` | No | `stdio` (default) or `sse` |
| `HOST` | No | SSE bind address (default `0.0.0.0`) |
| `PORT` | No | SSE port (default `8080`) |

*Either refresh token + key + secret, OR access token required.

## Dependencies

`mcp[cli]>=1.2.0`, `dropbox>=12.0.0`, `python-dotenv>=1.0.0`. Python 3 required.

## Key Implementation Details

- Text file detection: `TEXT_EXTENSIONS` set (~40 extensions) plus MIME type fallback
- All tool responses return JSON strings via `json.dumps()`
- `delete_file` is the only destructive tool — requires `confirm=True` safety parameter
- Dropbox paths: `""` or `"/"` both map to root; paths auto-prefixed with `/` if missing
