"""
Dropbox MCP Server - Production Ready
Connects Claude/Cursor to your Dropbox for file management, search, and content operations.
Supports both stdio (local) and SSE (remote) transports.
"""

from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from dotenv import load_dotenv
import dropbox
from dropbox.files import WriteMode, SearchOptions, SearchOrderBy
from dropbox.sharing import RequestedVisibility, SharedLinkSettings
import asyncio
import json
import os
import mimetypes
from pathlib import PurePosixPath
from datetime import datetime

load_dotenv()

MAX_TEXT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".text", ".csv", ".tsv",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".rb", ".sh", ".bash", ".zsh", ".fish",
    ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".sql", ".r", ".m", ".mm",
    ".log", ".env", ".gitignore", ".dockerfile",
    ".rst", ".tex", ".bib", ".org", ".adoc",
}


def _is_text_file(path: str) -> bool:
    ext = PurePosixPath(path).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(path)
    return mime is not None and mime.startswith("text/")


def _format_entry(entry) -> dict:
    """Format a Dropbox file/folder entry into a clean dict."""
    info = {
        "name": entry.name,
        "path": entry.path_display,
        "type": "folder" if isinstance(entry, dropbox.files.FolderMetadata) else "file",
    }
    if isinstance(entry, dropbox.files.FileMetadata):
        info["size_bytes"] = entry.size
        info["modified"] = entry.server_modified.isoformat()
        info["content_hash"] = entry.content_hash
    return info


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# Lifespan: initialise and clean up the Dropbox client
# ---------------------------------------------------------------------------
@dataclass
class AppContext:
    dbx: dropbox.Dropbox


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN")

    if refresh_token and app_key and app_secret:
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )
    elif access_token:
        dbx = dropbox.Dropbox(access_token)
    else:
        raise RuntimeError(
            "Dropbox credentials missing. "
            "Set DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET, "
            "or DROPBOX_ACCESS_TOKEN in your .env file."
        )

    try:
        dbx.users_get_current_account()
    except dropbox.exceptions.AuthError as e:
        raise RuntimeError(f"Dropbox authentication failed: {e}")

    try:
        yield AppContext(dbx=dbx)
    finally:
        dbx.close()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "dropbox-mcp-server",
    instructions="Dropbox integration for file management, search, and content operations",
    lifespan=app_lifespan,
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8080")),
)


# ---------------------------------------------------------------------------
# Tool: list_files
# ---------------------------------------------------------------------------
@mcp.tool()
async def list_files(ctx: Context, path: str = "", recursive: bool = False, limit: int = 100) -> str:
    """List files and folders in a Dropbox directory.

    Use this to browse and explore the Dropbox folder structure.
    Returns name, path, type, size, and modification date for each entry.

    Args:
        ctx: Server context (automatic)
        path: Dropbox path to list. Use "" or "/" for root. Example: "/Documents/Projects"
        recursive: If true, list all files in subfolders too
        limit: Maximum number of entries to return (default 100, max 2000)
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx
        if path in ("", "/"):
            path = ""
        limit = min(max(1, limit), 2000)

        result = dbx.files_list_folder(path, recursive=recursive, limit=min(limit, 2000))
        entries = [_format_entry(e) for e in result.entries]

        while result.has_more and len(entries) < limit:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(_format_entry(e) for e in result.entries)

        entries = entries[:limit]

        folders = [e for e in entries if e["type"] == "folder"]
        files = [e for e in entries if e["type"] == "file"]
        total_size = sum(e.get("size_bytes", 0) for e in files)

        return json.dumps({
            "path": path or "/",
            "total_entries": len(entries),
            "folders": len(folders),
            "files": len(files),
            "total_size": _format_size(total_size),
            "entries": entries,
            "has_more": result.has_more,
        }, indent=2, default=str)

    except dropbox.exceptions.ApiError as e:
        return f"Error listing files: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: read_file
# ---------------------------------------------------------------------------
@mcp.tool()
async def read_file(ctx: Context, path: str) -> str:
    """Read the contents of a text file from Dropbox.

    Supports markdown, text, code, JSON, YAML, CSV, and other text-based files.
    Binary files (images, PDFs, etc.) will return metadata only.

    Args:
        ctx: Server context (automatic)
        path: Full Dropbox path to the file. Example: "/Documents/notes.md"
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx

        metadata = dbx.files_get_metadata(path)
        if isinstance(metadata, dropbox.files.FolderMetadata):
            return f"Error: '{path}' is a folder, not a file. Use list_files instead."

        file_info = _format_entry(metadata)

        if not _is_text_file(path):
            file_info["note"] = "Binary file — content not shown. Use get_download_link to access it."
            return json.dumps(file_info, indent=2, default=str)

        if metadata.size > MAX_TEXT_FILE_SIZE:
            file_info["note"] = f"File too large ({_format_size(metadata.size)}). Max is {_format_size(MAX_TEXT_FILE_SIZE)}."
            return json.dumps(file_info, indent=2, default=str)

        _, response = dbx.files_download(path)
        content = response.content.decode("utf-8", errors="replace")

        return json.dumps({
            **file_info,
            "content": content,
        }, indent=2, default=str)

    except dropbox.exceptions.ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            return f"Error: File not found at '{path}'"
        return f"Error reading file: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: search_files
# ---------------------------------------------------------------------------
@mcp.tool()
async def search_files(ctx: Context, query: str, path: str = "", file_extensions: str = "", max_results: int = 20) -> str:
    """Search for files in Dropbox by name or content.

    Use this to find files when you don't know the exact path.
    Searches file names and, where possible, file contents.

    Args:
        ctx: Server context (automatic)
        query: Search terms. Example: "project proposal" or "meeting notes 2026"
        path: Restrict search to this folder and subfolders. Use "" for everywhere.
        file_extensions: Comma-separated list of extensions to filter. Example: "md,txt,pdf"
        max_results: Maximum results to return (default 20, max 100)
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx
        max_results = min(max(1, max_results), 100)

        options = SearchOptions(
            path=path if path else None,
            max_results=max_results,
            file_extensions=[ext.strip().lstrip(".") for ext in file_extensions.split(",") if ext.strip()] or None,
            order_by=SearchOrderBy.relevance,
        )

        result = dbx.files_search_v2(query, options=options)

        matches = []
        for match in result.matches:
            metadata = match.metadata.get_metadata()
            entry = _format_entry(metadata)
            matches.append(entry)

        return json.dumps({
            "query": query,
            "total_matches": len(matches),
            "has_more": result.has_more,
            "matches": matches,
        }, indent=2, default=str)

    except dropbox.exceptions.ApiError as e:
        return f"Error searching: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: write_file
# ---------------------------------------------------------------------------
@mcp.tool()
async def write_file(ctx: Context, path: str, content: str, overwrite: bool = False) -> str:
    """Create or update a text file in Dropbox.

    Writes UTF-8 text content to the specified path.
    Parent folders are created automatically.

    Args:
        ctx: Server context (automatic)
        path: Full Dropbox path for the file. Example: "/Documents/new-note.md"
        content: The text content to write
        overwrite: If true, overwrite existing file. If false (default), fail if file exists.
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx

        if not path.startswith("/"):
            path = "/" + path

        mode = WriteMode.overwrite if overwrite else WriteMode.add
        data = content.encode("utf-8")

        metadata = dbx.files_upload(data, path, mode=mode, mute=True)

        return json.dumps({
            "status": "success",
            "action": "overwritten" if overwrite else "created",
            **_format_entry(metadata),
        }, indent=2, default=str)

    except dropbox.exceptions.ApiError as e:
        if hasattr(e.error, "is_path") and e.error.is_path():
            conflict = e.error.get_path()
            if hasattr(conflict, "is_conflict") and conflict.is_conflict():
                return "Error: File already exists. Set overwrite=true to replace it."
        return f"Error writing file: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: create_folder
# ---------------------------------------------------------------------------
@mcp.tool()
async def create_folder(ctx: Context, path: str) -> str:
    """Create a new folder in Dropbox.

    Creates the folder and any missing parent folders automatically.

    Args:
        ctx: Server context (automatic)
        path: Full Dropbox path for the folder. Example: "/Projects/2026/Q1"
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx

        if not path.startswith("/"):
            path = "/" + path

        result = dbx.files_create_folder_v2(path, autorename=False)

        return json.dumps({
            "status": "success",
            "path": result.metadata.path_display,
            "name": result.metadata.name,
        }, indent=2)

    except dropbox.exceptions.ApiError as e:
        if hasattr(e.error, "is_path") and e.error.get_path().is_conflict():
            return f"Folder already exists at '{path}'"
        return f"Error creating folder: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: move_file
# ---------------------------------------------------------------------------
@mcp.tool()
async def move_file(ctx: Context, from_path: str, to_path: str) -> str:
    """Move or rename a file or folder in Dropbox.

    Works for both moving to a different folder and renaming in the same folder.

    Args:
        ctx: Server context (automatic)
        from_path: Current path. Example: "/Documents/old-name.md"
        to_path: New path. Example: "/Archive/renamed.md"
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx
        result = dbx.files_move_v2(from_path, to_path)
        metadata = result.metadata

        return json.dumps({
            "status": "success",
            "from": from_path,
            "to": metadata.path_display,
            "type": "folder" if isinstance(metadata, dropbox.files.FolderMetadata) else "file",
        }, indent=2)

    except dropbox.exceptions.ApiError as e:
        return f"Error moving: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: copy_file
# ---------------------------------------------------------------------------
@mcp.tool()
async def copy_file(ctx: Context, from_path: str, to_path: str) -> str:
    """Copy a file or folder in Dropbox.

    Args:
        ctx: Server context (automatic)
        from_path: Source path. Example: "/Templates/template.md"
        to_path: Destination path. Example: "/Projects/new-project/README.md"
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx
        result = dbx.files_copy_v2(from_path, to_path)
        metadata = result.metadata

        return json.dumps({
            "status": "success",
            "from": from_path,
            "to": metadata.path_display,
            "type": "folder" if isinstance(metadata, dropbox.files.FolderMetadata) else "file",
        }, indent=2)

    except dropbox.exceptions.ApiError as e:
        return f"Error copying: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: delete_file
# ---------------------------------------------------------------------------
@mcp.tool()
async def delete_file(ctx: Context, path: str, confirm: bool = False) -> str:
    """Delete a file or folder from Dropbox (moves to trash).

    Deleted items can be restored from the Dropbox trash for 30 days.

    Args:
        ctx: Server context (automatic)
        path: Path to delete. Example: "/Documents/old-file.md"
        confirm: Must be set to true to actually delete. Safety measure.
    """
    try:
        if not confirm:
            return "Safety check: set confirm=true to delete. This moves the item to Dropbox trash (recoverable for 30 days)."

        dbx = ctx.request_context.lifespan_context.dbx
        result = dbx.files_delete_v2(path)
        metadata = result.metadata

        return json.dumps({
            "status": "deleted (moved to trash)",
            "path": metadata.path_display,
            "name": metadata.name,
            "recoverable": "Yes, from Dropbox trash for 30 days",
        }, indent=2)

    except dropbox.exceptions.ApiError as e:
        if hasattr(e.error, "is_path_lookup") and e.error.get_path_lookup().is_not_found():
            return f"Error: Nothing found at '{path}'"
        return f"Error deleting: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: get_file_info
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_file_info(ctx: Context, path: str) -> str:
    """Get detailed metadata about a file or folder in Dropbox.

    Returns size, modification date, content hash, sharing status, etc.

    Args:
        ctx: Server context (automatic)
        path: Dropbox path. Example: "/Documents/report.pdf"
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx
        metadata = dbx.files_get_metadata(path, include_media_info=True, include_has_explicit_shared_members=True)

        info = _format_entry(metadata)

        if isinstance(metadata, dropbox.files.FileMetadata):
            info["size_human"] = _format_size(metadata.size)
            info["is_downloadable"] = metadata.is_downloadable
            if metadata.media_info:
                info["media_info"] = str(metadata.media_info)

        return json.dumps(info, indent=2, default=str)

    except dropbox.exceptions.ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            return f"Error: Nothing found at '{path}'"
        return f"Error: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: get_shared_link
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_shared_link(ctx: Context, path: str) -> str:
    """Get or create a shareable link for a Dropbox file or folder.

    If a shared link already exists, returns the existing one.
    Otherwise creates a new public link.

    Args:
        ctx: Server context (automatic)
        path: Dropbox path. Example: "/Documents/shared-report.pdf"
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx

        existing = dbx.sharing_list_shared_links(path=path, direct_only=True)
        if existing.links:
            link = existing.links[0]
            return json.dumps({
                "status": "existing link",
                "url": link.url,
                "path": link.path_lower,
                "expires": str(link.expires) if link.expires else "never",
            }, indent=2)

        settings = SharedLinkSettings(
            requested_visibility=RequestedVisibility.public,
        )
        link = dbx.sharing_create_shared_link_with_settings(path, settings=settings)

        return json.dumps({
            "status": "new link created",
            "url": link.url,
            "path": link.path_lower,
            "expires": str(link.expires) if link.expires else "never",
        }, indent=2)

    except dropbox.exceptions.ApiError as e:
        return f"Error creating shared link: {e.error}"
    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: get_account_info
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_account_info(ctx: Context) -> str:
    """Get information about the connected Dropbox account.

    Returns account name, email, storage usage, and plan details.
    Useful to verify which Dropbox account is connected.
    """
    try:
        dbx = ctx.request_context.lifespan_context.dbx
        account = dbx.users_get_current_account()
        space = dbx.users_get_space_usage()

        used = space.used
        if space.allocation.is_individual():
            allocated = space.allocation.get_individual().allocated
        elif space.allocation.is_team():
            allocated = space.allocation.get_team().allocated
        else:
            allocated = 0

        return json.dumps({
            "name": account.name.display_name,
            "email": account.email,
            "account_type": str(account.account_type),
            "team": account.team.name if account.team else None,
            "storage_used": _format_size(used),
            "storage_allocated": _format_size(allocated) if allocated else "unknown",
            "storage_percent": f"{(used / allocated * 100):.1f}%" if allocated else "unknown",
        }, indent=2)

    except Exception as e:
        return f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    transport = os.getenv("TRANSPORT", "stdio")

    if transport == "sse":
        await mcp.run_sse_async()
    else:
        await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
