"""Rewrite pyrogram.get_chat_history"""

import asyncio
from datetime import datetime
from typing import AsyncGenerator, Optional, Union

import pyrogram
from loguru import logger

# pylint: disable = W0611
from pyrogram import raw, types, utils

DEFAULT_HISTORY_FETCH_TIMEOUT = 60
DEFAULT_HISTORY_FETCH_RETRIES = 3
DEFAULT_HISTORY_FETCH_RETRY_DELAY = 3


async def get_chunk_v2(
    *,
    client: pyrogram.Client,
    chat_id: Union[int, str],
    limit: int = 0,
    offset: int = 0,
    max_id: int = 0,
    from_message_id: int = 0,
    from_date: datetime = utils.zero_datetime(),
    reverse: bool = False,
    request_timeout: int = DEFAULT_HISTORY_FETCH_TIMEOUT,
    retry_count: int = DEFAULT_HISTORY_FETCH_RETRIES,
):
    """get chunk"""
    from_message_id = from_message_id or (1 if reverse else 0)

    last_error = None
    for attempt in range(1, max(retry_count, 1) + 1):
        try:
            raw_messages = await asyncio.wait_for(
                client.invoke(
                    raw.functions.messages.GetHistory(
                        peer=await client.resolve_peer(chat_id),
                        offset_id=from_message_id,
                        offset_date=utils.datetime_to_timestamp(from_date),
                        add_offset=offset * (-1 if reverse else 1)
                        - (limit if reverse else 0),
                        limit=limit,
                        max_id=max_id,
                        min_id=0,
                        hash=0,
                    ),
                    sleep_threshold=60,
                ),
                timeout=request_timeout,
            )
            break
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning(
                "GetHistory timeout: chat_id={}, offset_id={}, attempt={}/{}, "
                "timeout={}s",
                chat_id,
                from_message_id,
                attempt,
                retry_count,
                request_timeout,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "GetHistory failed: chat_id={}, offset_id={}, attempt={}/{}: {}",
                chat_id,
                from_message_id,
                attempt,
                retry_count,
                exc,
            )

        if attempt < retry_count:
            await asyncio.sleep(DEFAULT_HISTORY_FETCH_RETRY_DELAY * attempt)
    else:
        if last_error:
            raise last_error
        raise TimeoutError("GetHistory did not return any result")

    messages = await utils.parse_messages(
        client,
        raw_messages,
        replies=0,
    )

    if reverse:
        messages.reverse()

    return messages


# pylint: disable = C0301
async def get_chat_history_v2(
    self: pyrogram.Client,
    chat_id: Union[int, str],
    limit: int = 0,
    max_id: int = 0,
    offset: int = 0,
    offset_id: int = 0,
    offset_date: datetime = utils.zero_datetime(),
    reverse: bool = False,
    request_timeout: int = DEFAULT_HISTORY_FETCH_TIMEOUT,
    retry_count: int = DEFAULT_HISTORY_FETCH_RETRIES,
) -> Optional[AsyncGenerator["types.Message", None]]:
    """Get messages from a chat history."""
    current = 0
    total = limit or (1 << 31) - 1
    limit = min(100, total)

    while True:
        messages = await get_chunk_v2(
            client=self,
            chat_id=chat_id,
            limit=limit,
            offset=offset,
            max_id=max_id + 1 if max_id else 0,
            from_message_id=offset_id,
            from_date=offset_date,
            reverse=reverse,
            request_timeout=request_timeout,
            retry_count=retry_count,
        )

        if not messages:
            break_count = offset_id - 1
            history_iter = self.get_chat_history(chat_id).__aiter__()
            while True:
                try:
                    message = await asyncio.wait_for(
                        history_iter.__anext__(), timeout=request_timeout
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.warning(
                        "Fallback get_chat_history timeout: chat_id={}, "
                        "offset_id={}, timeout={}s",
                        chat_id,
                        offset_id,
                        request_timeout,
                    )
                    return

                if break_count:
                    break_count -= 1
                    continue
                if len(messages) >= limit + 1:
                    break
                messages.append(message)
            if not messages:
                return

        offset_id = messages[-1].id + (1 if reverse else 0)

        for message in messages:
            yield message

            current += 1

            if current >= total:
                return
