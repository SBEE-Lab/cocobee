"""Slack user id -> display name, resolved once per user."""

from __future__ import annotations

import cocoindex as coco
from slack_sdk.errors import SlackApiError

from slack_index.context import SLACK, SLACK_LIMIT

UNKNOWN_AUTHOR = "unknown"


@coco.fn(memo=True)
async def display_name(user_id: str | None) -> str:
    """Memoized so a channel full of the same handful of people costs a few calls.

    Bot and app ids are not users, so Slack rejects them — their raw id is the
    best label available.
    """
    if not user_id:
        return UNKNOWN_AUTHOR
    await coco.use_context(SLACK_LIMIT).acquire()
    try:
        response = await coco.use_context(SLACK).users_info(user=user_id)
    except SlackApiError:
        return user_id
    user = response["user"]
    profile = user.get("profile", {})
    return profile.get("display_name") or user.get("real_name") or user_id
