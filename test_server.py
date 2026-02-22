#!/usr/bin/env python3
"""Tests for dropbox-mcp-server/server.py — Dropbox MCP Server."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import PurePosixPath
from datetime import datetime

# Import helpers and constants (not the tools themselves, which need a running server)
from server import (
    _is_text_file,
    _format_entry,
    _format_size,
    TEXT_EXTENSIONS,
    MAX_TEXT_FILE_SIZE,
)


# ─── _is_text_file ──────────────────────────────────────────────────────────


class TestIsTextFile:
    def test_markdown_is_text(self):
        assert _is_text_file("report.md") is True

    def test_python_is_text(self):
        assert _is_text_file("script.py") is True

    def test_json_is_text(self):
        assert _is_text_file("config.json") is True

    def test_yaml_is_text(self):
        assert _is_text_file("settings.yaml") is True
        assert _is_text_file("settings.yml") is True

    def test_csv_is_text(self):
        assert _is_text_file("data.csv") is True

    def test_html_is_text(self):
        assert _is_text_file("page.html") is True
        assert _is_text_file("page.htm") is True

    def test_javascript_is_text(self):
        assert _is_text_file("app.js") is True
        assert _is_text_file("app.ts") is True
        assert _is_text_file("component.jsx") is True
        assert _is_text_file("component.tsx") is True

    def test_shell_scripts_are_text(self):
        assert _is_text_file("setup.sh") is True
        assert _is_text_file("init.bash") is True
        assert _is_text_file("config.zsh") is True

    def test_log_is_text(self):
        assert _is_text_file("app.log") is True

    def test_env_is_text(self):
        # ".env" as a dotfile has no suffix (PurePosixPath(".env").suffix == "")
        # Files like "config.env" DO match the .env extension
        assert _is_text_file("config.env") is True
        assert _is_text_file(".env") is False  # Dotfile, no suffix detected

    def test_gitignore_is_text(self):
        # ".gitignore" is a dotfile with no suffix — not matched by TEXT_EXTENSIONS
        assert _is_text_file(".gitignore") is False

    def test_pdf_is_not_text(self):
        assert _is_text_file("report.pdf") is False

    def test_image_is_not_text(self):
        assert _is_text_file("photo.jpg") is False
        assert _is_text_file("icon.png") is False
        assert _is_text_file("image.gif") is False

    def test_binary_is_not_text(self):
        assert _is_text_file("archive.zip") is False
        assert _is_text_file("program.exe") is False

    def test_case_insensitive_extension(self):
        assert _is_text_file("README.MD") is True
        assert _is_text_file("CONFIG.JSON") is True

    def test_path_with_directories(self):
        assert _is_text_file("/some/path/to/file.py") is True
        assert _is_text_file("/some/path/to/file.pdf") is False

    def test_all_text_extensions_recognized(self):
        for ext in TEXT_EXTENSIONS:
            assert _is_text_file(f"test{ext}") is True, f"Extension {ext} should be text"

    def test_no_extension(self):
        # No extension, no mime type — should return False
        assert _is_text_file("Dockerfile") is False  # Unless mimetypes guesses it


# ─── _format_entry ───────────────────────────────────────────────────────────


class TestFormatEntry:
    def test_folder_entry(self):
        import dropbox.files
        entry = MagicMock(spec=dropbox.files.FolderMetadata)
        entry.name = "Documents"
        entry.path_display = "/Documents"

        result = _format_entry(entry)
        assert result["name"] == "Documents"
        assert result["path"] == "/Documents"
        assert result["type"] == "folder"
        assert "size_bytes" not in result

    def test_file_entry(self):
        import dropbox.files
        entry = MagicMock(spec=dropbox.files.FileMetadata)
        entry.name = "report.pdf"
        entry.path_display = "/Documents/report.pdf"
        entry.size = 1024
        entry.server_modified = datetime(2025, 1, 15, 10, 30, 0)
        entry.content_hash = "abc123"

        result = _format_entry(entry)
        assert result["name"] == "report.pdf"
        assert result["path"] == "/Documents/report.pdf"
        assert result["type"] == "file"
        assert result["size_bytes"] == 1024
        assert result["modified"] == "2025-01-15T10:30:00"
        assert result["content_hash"] == "abc123"


# ─── _format_size ────────────────────────────────────────────────────────────


class TestFormatSize:
    def test_bytes(self):
        assert _format_size(500) == "500.0 B"

    def test_kilobytes(self):
        result = _format_size(1536)
        assert "KB" in result

    def test_megabytes(self):
        result = _format_size(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        result = _format_size(2 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_terabytes(self):
        result = _format_size(3 * 1024 * 1024 * 1024 * 1024)
        assert "TB" in result

    def test_zero(self):
        assert _format_size(0) == "0.0 B"

    def test_exact_kb(self):
        result = _format_size(1024)
        assert "1.0 KB" == result


# ─── Constants ───────────────────────────────────────────────────────────────


class TestConstants:
    def test_max_text_file_size(self):
        assert MAX_TEXT_FILE_SIZE == 10 * 1024 * 1024

    def test_text_extensions_comprehensive(self):
        # Should include common text extensions
        assert ".md" in TEXT_EXTENSIONS
        assert ".py" in TEXT_EXTENSIONS
        assert ".json" in TEXT_EXTENSIONS
        assert ".txt" in TEXT_EXTENSIONS
        assert ".csv" in TEXT_EXTENSIONS
        assert ".xml" in TEXT_EXTENSIONS
        assert ".sql" in TEXT_EXTENSIONS

    def test_text_extensions_all_lowercase(self):
        for ext in TEXT_EXTENSIONS:
            assert ext == ext.lower(), f"Extension should be lowercase: {ext}"
            assert ext.startswith("."), f"Extension should start with dot: {ext}"


# ─── Tool function behavior (mocked Dropbox SDK) ────────────────────────────


class MockContext:
    """Mock MCP Context for tool tests."""
    def __init__(self, dbx_mock):
        self.request_context = MagicMock()
        self.request_context.lifespan_context.dbx = dbx_mock


class TestDeleteFileSafetyCheck:
    @pytest.mark.asyncio
    async def test_confirm_false_returns_safety_message(self):
        from server import delete_file
        dbx = MagicMock()
        ctx = MockContext(dbx)
        result = await delete_file(ctx, "/path/file.txt", confirm=False)
        assert "Safety check" in result
        assert "confirm=true" in result.lower()
        dbx.files_delete_v2.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_true_deletes(self):
        import dropbox.files
        from server import delete_file
        dbx = MagicMock()
        metadata = MagicMock(spec=dropbox.files.FileMetadata)
        metadata.path_display = "/path/file.txt"
        metadata.name = "file.txt"
        dbx.files_delete_v2.return_value.metadata = metadata
        ctx = MockContext(dbx)

        result = await delete_file(ctx, "/path/file.txt", confirm=True)
        dbx.files_delete_v2.assert_called_once_with("/path/file.txt")
        parsed = json.loads(result)
        assert "deleted" in parsed["status"]


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_auto_prefix_slash(self):
        import dropbox.files
        from server import write_file
        dbx = MagicMock()
        metadata = MagicMock(spec=dropbox.files.FileMetadata)
        metadata.name = "test.txt"
        metadata.path_display = "/test.txt"
        metadata.size = 100
        metadata.server_modified = datetime.now()
        metadata.content_hash = "hash"
        dbx.files_upload.return_value = metadata
        ctx = MockContext(dbx)

        await write_file(ctx, "test.txt", "content", overwrite=False)
        # Should have been called with /test.txt (auto-prefixed)
        call_args = dbx.files_upload.call_args
        assert call_args[0][1] == "/test.txt"

    @pytest.mark.asyncio
    async def test_overwrite_mode(self):
        import dropbox.files
        from dropbox.files import WriteMode
        from server import write_file
        dbx = MagicMock()
        metadata = MagicMock(spec=dropbox.files.FileMetadata)
        metadata.name = "test.txt"
        metadata.path_display = "/test.txt"
        metadata.size = 100
        metadata.server_modified = datetime.now()
        metadata.content_hash = "hash"
        dbx.files_upload.return_value = metadata
        ctx = MockContext(dbx)

        await write_file(ctx, "/test.txt", "content", overwrite=True)
        call_args = dbx.files_upload.call_args
        assert call_args[1]["mode"] == WriteMode.overwrite


class TestCreateFolder:
    @pytest.mark.asyncio
    async def test_auto_prefix_slash(self):
        from server import create_folder
        dbx = MagicMock()
        result_mock = MagicMock()
        result_mock.metadata.path_display = "/Projects"
        result_mock.metadata.name = "Projects"
        dbx.files_create_folder_v2.return_value = result_mock
        ctx = MockContext(dbx)

        await create_folder(ctx, "Projects")
        call_args = dbx.files_create_folder_v2.call_args
        assert call_args[0][0] == "/Projects"


class TestListFiles:
    @pytest.mark.asyncio
    async def test_root_path_normalization(self):
        import dropbox.files
        from server import list_files
        dbx = MagicMock()
        result_mock = MagicMock()
        result_mock.entries = []
        result_mock.has_more = False
        dbx.files_list_folder.return_value = result_mock
        ctx = MockContext(dbx)

        await list_files(ctx, path="/", recursive=False, limit=100)
        # "/" should be normalized to "" for Dropbox API
        dbx.files_list_folder.assert_called_once_with("", recursive=False, limit=100)

    @pytest.mark.asyncio
    async def test_limit_capped_at_2000(self):
        import dropbox.files
        from server import list_files
        dbx = MagicMock()
        result_mock = MagicMock()
        result_mock.entries = []
        result_mock.has_more = False
        dbx.files_list_folder.return_value = result_mock
        ctx = MockContext(dbx)

        await list_files(ctx, path="", recursive=False, limit=5000)
        call_args = dbx.files_list_folder.call_args
        assert call_args[1]["limit"] <= 2000

    @pytest.mark.asyncio
    async def test_returns_json_with_stats(self):
        import dropbox.files
        from server import list_files
        dbx = MagicMock()

        folder_entry = MagicMock(spec=dropbox.files.FolderMetadata)
        folder_entry.name = "docs"
        folder_entry.path_display = "/docs"

        file_entry = MagicMock(spec=dropbox.files.FileMetadata)
        file_entry.name = "readme.md"
        file_entry.path_display = "/readme.md"
        file_entry.size = 256
        file_entry.server_modified = datetime.now()
        file_entry.content_hash = "xyz"

        result_mock = MagicMock()
        result_mock.entries = [folder_entry, file_entry]
        result_mock.has_more = False
        dbx.files_list_folder.return_value = result_mock
        ctx = MockContext(dbx)

        result = await list_files(ctx, path="", recursive=False, limit=100)
        parsed = json.loads(result)
        assert parsed["total_entries"] == 2
        assert parsed["folders"] == 1
        assert parsed["files"] == 1


class TestReadFile:
    @pytest.mark.asyncio
    async def test_folder_returns_error(self):
        import dropbox.files
        from server import read_file
        dbx = MagicMock()
        dbx.files_get_metadata.return_value = MagicMock(spec=dropbox.files.FolderMetadata)
        ctx = MockContext(dbx)

        result = await read_file(ctx, "/some/folder")
        assert "folder" in result.lower()
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_binary_file_returns_metadata_only(self):
        import dropbox.files
        from server import read_file
        dbx = MagicMock()
        metadata = MagicMock(spec=dropbox.files.FileMetadata)
        metadata.name = "image.png"
        metadata.path_display = "/image.png"
        metadata.size = 5000
        metadata.server_modified = datetime.now()
        metadata.content_hash = "hash"
        dbx.files_get_metadata.return_value = metadata
        ctx = MockContext(dbx)

        result = await read_file(ctx, "/image.png")
        parsed = json.loads(result)
        assert "note" in parsed
        assert "Binary" in parsed["note"]

    @pytest.mark.asyncio
    async def test_too_large_file_returns_error(self):
        import dropbox.files
        from server import read_file
        dbx = MagicMock()
        metadata = MagicMock(spec=dropbox.files.FileMetadata)
        metadata.name = "huge.md"
        metadata.path_display = "/huge.md"
        metadata.size = MAX_TEXT_FILE_SIZE + 1
        metadata.server_modified = datetime.now()
        metadata.content_hash = "hash"
        dbx.files_get_metadata.return_value = metadata
        ctx = MockContext(dbx)

        result = await read_file(ctx, "/huge.md")
        parsed = json.loads(result)
        assert "too large" in parsed["note"].lower()

    @pytest.mark.asyncio
    async def test_text_file_returns_content(self):
        import dropbox.files
        from server import read_file
        dbx = MagicMock()
        metadata = MagicMock(spec=dropbox.files.FileMetadata)
        metadata.name = "notes.md"
        metadata.path_display = "/notes.md"
        metadata.size = 100
        metadata.server_modified = datetime.now()
        metadata.content_hash = "hash"
        dbx.files_get_metadata.return_value = metadata

        response_mock = MagicMock()
        response_mock.content = b"# Hello World"
        dbx.files_download.return_value = (None, response_mock)

        ctx = MockContext(dbx)
        result = await read_file(ctx, "/notes.md")
        parsed = json.loads(result)
        assert parsed["content"] == "# Hello World"


class TestSearchFiles:
    @pytest.mark.asyncio
    async def test_search_returns_matches(self):
        import dropbox.files
        from server import search_files
        dbx = MagicMock()

        file_meta = MagicMock(spec=dropbox.files.FileMetadata)
        file_meta.name = "report.pdf"
        file_meta.path_display = "/report.pdf"
        file_meta.size = 1000
        file_meta.server_modified = datetime.now()
        file_meta.content_hash = "abc"

        match = MagicMock()
        match.metadata.get_metadata.return_value = file_meta

        result_mock = MagicMock()
        result_mock.matches = [match]
        result_mock.has_more = False
        dbx.files_search_v2.return_value = result_mock

        ctx = MockContext(dbx)
        result = await search_files(ctx, "report")
        parsed = json.loads(result)
        assert parsed["total_matches"] == 1
        assert parsed["matches"][0]["name"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_max_results_capped(self):
        from server import search_files
        dbx = MagicMock()
        result_mock = MagicMock()
        result_mock.matches = []
        result_mock.has_more = False
        dbx.files_search_v2.return_value = result_mock
        ctx = MockContext(dbx)

        await search_files(ctx, "test", max_results=500)
        # The internal max_results should be capped at 100
        call_args = dbx.files_search_v2.call_args
        options = call_args[1]["options"]
        assert options.max_results <= 100
