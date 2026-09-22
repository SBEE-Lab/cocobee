"""A reply-less message must not cost a Slack call."""

from __future__ import annotations

import asyncio

from slack_index.models import ThreadRef
from slack_index.threads import needs_replies, thread_messages, thread_permalink


def _ref(reply_count: int) -> ThreadRef:
    return ThreadRef(
        channel="C0TEST",
        thread_ts="1758470400.000100",
        revision="1758470400.000100",
        reply_count=reply_count,
        user="U0LEAD",
        text="staging is green",
    )


def test_lone_message_is_rendered_from_the_scan() -> None:
    ref = _ref(0)
    assert not needs_replies(ref)
    # No Slack client in context: reaching the API here would raise.
    assert asyncio.run(thread_messages(ref)) == [
        {"user": "U0LEAD", "text": "staging is green", "ts": ref.thread_ts}
    ]


def test_thread_with_replies_still_needs_fetching() -> None:
    assert needs_replies(_ref(3))


def test_permalink_points_at_the_thread() -> None:
    assert (
        thread_permalink("C0TEST", "1758470400.000100")
        == "https://slack.com/archives/C0TEST/p1758470400000100"
    )
