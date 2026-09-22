"""What gets read, and what gets skipped before any download happens."""

from __future__ import annotations

import asyncio

from slack_index.files import extract_text, is_text
from slack_index.models import FileRef

MAX_BYTES = 1024


def _ref(mimetype: str, size: int) -> FileRef:
    return FileRef(
        channel="C0TEST",
        file_id="F0TEST",
        name="sample",
        mimetype=mimetype,
        size=size,
        created=1758470500,
        url="https://files.slack.com/files-pri/T0-F0TEST/download/sample",
        permalink="https://example.slack.com/files/U0LEAD/F0TEST/sample",
        user="U0LEAD",
    )


def test_is_text_covers_text_and_structured_formats() -> None:
    assert is_text("text/markdown")
    assert is_text("application/json")
    assert not is_text("application/pdf")
    assert not is_text("image/png")


def test_binary_file_is_skipped_without_downloading() -> None:
    assert asyncio.run(extract_text(_ref("application/pdf", 10), MAX_BYTES)) is None


def test_oversized_file_is_skipped_without_downloading() -> None:
    assert (
        asyncio.run(extract_text(_ref("text/plain", MAX_BYTES + 1), MAX_BYTES)) is None
    )
