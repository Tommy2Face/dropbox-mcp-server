# Dropbox MCP Server

MCP server that connects Claude Desktop, Cursor, and other AI tools to your Dropbox account. Browse, read, search, create, move, and share files — all through natural language.

## Tools

| Tool | Description |
|------|-------------|
| `list_files` | Browse files and folders in any Dropbox directory |
| `read_file` | Read the contents of markdown, text, code, and other text files |
| `search_files` | Search for files by name or content, with extension filtering |
| `write_file` | Create new files or update existing ones |
| `create_folder` | Create folders (with auto-creation of parent folders) |
| `move_file` | Move or rename files and folders |
| `copy_file` | Copy files or folders to a new location |
| `delete_file` | Delete files/folders (moves to Dropbox trash, recoverable 30 days) |
| `get_file_info` | Get detailed metadata (size, dates, content hash) |
| `get_shared_link` | Get or create a shareable public link |
| `get_account_info` | Check which Dropbox account is connected and storage usage |

## Quick Start

### 1. Create a Dropbox App

1. Go to [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. Click **Create app**
3. Choose **Scoped access**
4. Choose **Full Dropbox** access (or App folder if you want restricted access)
5. Name it something like `mcp-server`
6. Under **Permissions**, enable:
   - `files.metadata.read`
   - `files.metadata.write`
   - `files.content.read`
   - `files.content.write`
   - `sharing.read`
   - `sharing.write`
7. Click **Submit** to save permissions

### 2. Get Your Credentials

**Option A — OAuth2 Refresh Token (recommended):**

1. Note your **App key** and **App secret** from the app settings page
2. Get a refresh token by running the included auth helper:

```bash
cd /Users/Beheerder/Code-projects/dropbox-mcp-server
python auth_helper.py
```

3. Follow the prompts — it will open your browser, you authorize, and it gives you a refresh token.

**Option B — Access Token (quick test):**

1. On the app settings page, click **Generate** under "Generated access token"
2. Note: this token expires after 4 hours

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Install Dependencies

```bash
cd /Users/Beheerder/Code-projects/dropbox-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Connect to Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dropbox": {
      "command": "/Users/Beheerder/Code-projects/dropbox-mcp-server/.venv/bin/python",
      "args": ["/Users/Beheerder/Code-projects/dropbox-mcp-server/server.py"],
      "env": {
        "DROPBOX_APP_KEY": "your-app-key",
        "DROPBOX_APP_SECRET": "your-app-secret",
        "DROPBOX_REFRESH_TOKEN": "your-refresh-token"
      }
    }
  }
}
```

### 6. Connect to Cursor

Add to your project's `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "dropbox": {
      "command": "/Users/Beheerder/Code-projects/dropbox-mcp-server/.venv/bin/python",
      "args": ["/Users/Beheerder/Code-projects/dropbox-mcp-server/server.py"],
      "env": {
        "DROPBOX_APP_KEY": "your-app-key",
        "DROPBOX_APP_SECRET": "your-app-secret",
        "DROPBOX_REFRESH_TOKEN": "your-refresh-token"
      }
    }
  }
}
```

### 7. SSE Mode (Remote Deployment)

Set `TRANSPORT=sse` in `.env`, then:

```bash
python server.py
# Server starts on http://0.0.0.0:8080
```

Connect with:

```json
{
  "mcpServers": {
    "dropbox": {
      "transport": "sse",
      "url": "http://localhost:8080/sse"
    }
  }
}
```

## Usage Examples

Once connected, you can ask Claude things like:

- "List all files in my Documents folder"
- "Search for markdown files about project proposals"
- "Read the contents of /Projects/README.md"
- "Create a new file at /Notes/meeting-2026-02-21.md with these notes: ..."
- "Move /Drafts/report.md to /Final/report-v2.md"
- "Get a shareable link for /Presentations/deck.pdf"
- "How much storage am I using?"

## Project Structure

```
dropbox-mcp-server/
├── server.py           # Main MCP server with all tools
├── auth_helper.py      # OAuth2 helper to get refresh token
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .env                # Your actual credentials (git-ignored)
└── README.md           # This file
```
