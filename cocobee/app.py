"""Pipeline entry point.

cocoindex update cocobee/app.py        # one-shot catch-up
cocoindex update -L cocobee/app.py     # live: re-scan every poll interval
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import cocoindex as coco
from anthropic import AsyncAnthropic
from cocoindex.connectors import lancedb
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.resources.rate_limit import RateLimiter
from slack_sdk.web.async_client import AsyncWebClient

from cocobee import config
from cocobee.context import DISTILLER, EMBEDDER, LANCE_DB, SLACK, SLACK_LIMIT
from cocobee.distill import Distiller
from cocobee.files import process_file
from cocobee.models import SlackChunk
from cocobee.source import SlackChannelFiles, SlackChannelThreads
from cocobee.threads import process_thread

_settings = config.Settings.from_env()


@coco.lifespan
async def coco_lifespan(builder: coco.EnvironmentBuilder) -> AsyncIterator[None]:
    config.VAR_DIR.mkdir(parents=True, exist_ok=True)
    builder.settings.db_path = config.DB_PATH
    builder.provide(SLACK, AsyncWebClient(token=config.bot_token()))
    builder.provide(
        DISTILLER,
        Distiller(
            AsyncAnthropic(
                api_key=config.anthropic_api_key(),
                default_headers=config.anthropic_headers(),
            ),
            config.DISTILL_MODEL,
        ),
    )
    builder.provide(SLACK_LIMIT, RateLimiter(config.SLACK_REQUESTS_PER_SECOND))
    builder.provide(EMBEDDER, SentenceTransformerEmbedder(_settings.embed_model))
    builder.provide(LANCE_DB, await lancedb.connect_async(str(config.LANCEDB_URI)))
    yield


@coco.fn
async def app_main(settings: config.Settings) -> None:
    table = await lancedb.mount_table_target(
        LANCE_DB,
        config.TABLE_NAME,
        await lancedb.TableSchema.from_class(SlackChunk, primary_key=["id"]),
    )
    table.declare_vector_index(column="embedding")

    client = coco.use_context(SLACK)
    limiter = coco.use_context(SLACK_LIMIT)
    for channel in settings.channel_ids:
        threads = SlackChannelThreads(
            client,
            limiter,
            channel,
            lookback=settings.lookback,
            poll_interval=settings.poll_interval,
        )
        files = SlackChannelFiles(
            client,
            limiter,
            channel,
            lookback=settings.lookback,
            poll_interval=settings.poll_interval,
        )
        # The channel is part of the subpath so each channel keeps its own
        # component subtree — and its own rows — across runs.
        await coco.mount_each(
            coco.ComponentSubpath("threads", channel), process_thread, threads, table
        )
        await coco.mount_each(
            coco.ComponentSubpath("files", channel),
            process_file,
            files,
            table,
            settings.max_file_bytes,
        )


app = coco.App(coco.AppConfig(name="SlackIndex"), app_main, settings=_settings)
