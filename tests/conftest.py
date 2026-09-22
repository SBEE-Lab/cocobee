"""A Slack client stub that replays recorded API responses."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeSlackClient:
    """Returns the queued response per method call and records the call kwargs."""

    def __init__(self, **responses: list[dict[str, Any]]) -> None:
        self._responses = {name: list(pages) for name, pages in responses.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _next(self, method: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, kwargs))
        pages = self._responses[method]
        if not pages:
            raise AssertionError(f"{method} called more times than there are pages")
        return pages.pop(0)

    async def conversations_history(self, **kwargs: Any) -> dict[str, Any]:
        return self._next("conversations_history", kwargs)

    async def files_list(self, **kwargs: Any) -> dict[str, Any]:
        return self._next("files_list", kwargs)


@pytest.fixture
def history_client() -> FakeSlackClient:
    return FakeSlackClient(
        conversations_history=[
            load_fixture("history_page1"),
            load_fixture("history_page2"),
        ]
    )


@pytest.fixture
def files_client() -> FakeSlackClient:
    return FakeSlackClient(files_list=[load_fixture("files_list")])
