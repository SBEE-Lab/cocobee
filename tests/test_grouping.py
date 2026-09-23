"""A message that only makes sense next to its neighbour must be indexed with it."""

from __future__ import annotations

from cocobee.config import WINDOW_MAX_CHARS, WINDOW_MAX_MESSAGES
from cocobee.models import Message
from cocobee.source import group_messages

CHANNEL = "C0TEST"
BASE = 1758470000.0


def _run(*specs: tuple[float, str, int]) -> list:
    """Each spec is (seconds after BASE, text, reply_count)."""
    messages = []
    meta = {}
    for offset, text, replies in specs:
        ts = f"{BASE + offset:.6f}"
        messages.append(Message(ts=ts, user="U0", text=text))
        meta[ts] = (ts, replies)
    return group_messages(CHANNEL, messages, meta)


def test_question_and_its_answer_land_in_one_conversation() -> None:
    conversations = _run((0, "when was the meeting?", 0), (20, "the 27th", 0))

    assert len(conversations) == 1
    assert [m.text for m in conversations[0].messages] == [
        "when was the meeting?",
        "the 27th",
    ]
    # The answer's own ts stays findable even though the key is the first message.
    assert conversations[0].start_ts == f"{BASE:.6f}"
    assert f"{BASE + 20:.6f}" in conversations[0].covered_ts


def test_a_long_silence_starts_a_new_conversation() -> None:
    conversations = _run((0, "first", 0), (3600, "much later", 0))

    assert [c.start_ts for c in conversations] == [f"{BASE:.6f}", f"{BASE + 3600:.6f}"]


def test_a_thread_stays_on_its_own_and_breaks_the_run() -> None:
    conversations = _run((0, "before", 0), (10, "thread parent", 2), (20, "after", 0))

    assert [(c.start_ts, c.is_thread, len(c.messages)) for c in conversations] == [
        (f"{BASE:.6f}", False, 1),
        (f"{BASE + 10:.6f}", True, 1),
        (f"{BASE + 20:.6f}", False, 1),
    ]


def test_a_busy_stretch_is_capped() -> None:
    conversations = _run(*[(i, "short", 0) for i in range(WINDOW_MAX_MESSAGES + 5)])

    assert len(conversations) == 2
    assert len(conversations[0].messages) == WINDOW_MAX_MESSAGES


def test_a_long_message_does_not_swallow_the_next_one() -> None:
    conversations = _run((0, "x" * WINDOW_MAX_CHARS, 0), (10, "next", 0))

    assert [len(c.messages) for c in conversations] == [1, 1]


def test_revision_is_the_latest_within_the_conversation() -> None:
    conversations = _run((0, "first", 0), (30, "later", 0))

    assert conversations[0].revision == f"{BASE + 30:.6f}"
