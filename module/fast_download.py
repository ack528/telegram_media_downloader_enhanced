"""Parallel media download.

Pyrogram downloads a file one 1 MB part at a time and multiplexes every
concurrent download over a single connection per data center, so throughput
is bounded by round-trip latency and by whatever a single (proxied) TCP
connection can carry.  Official clients and fast tools (Telegram Desktop,
tdl, FastTelethon) instead keep several part requests in flight over several
connections.  This module does the same:

* ``MediaSessionPool`` opens extra MTProto sessions to a media DC.  They reuse
  the auth key of Pyrogram's own (already authorized) media session, so no
  additional authorization is exported.
* ``iter_file_parallel`` keeps up to ``threads`` part requests in flight,
  spread round-robin over the pool, and yields parts strictly in order so the
  caller can keep appending to a resumable ``.temp`` file.
* All downloads from one DC share a cap on requests in flight.  Measured on a
  proxied Premium account, the server stopped answering once roughly 16-20
  parts were outstanding at once, however they were spread over connections,
  while 4-10 already saturated the link.
"""

import asyncio
import functools
import inspect
from collections import deque
from typing import AsyncGenerator, Callable, Deque, Dict, List, Optional, Tuple

from loguru import logger
from pyrogram import raw, utils
from pyrogram.errors import InternalServerError, ServiceUnavailable
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.methods.messages.inline_session import get_session
from pyrogram.session import Session

PART_SIZE = 1024 * 1024
MAX_IN_FLIGHT = 8
# Per attempt.  A part waits behind the other parts in flight on a slow link,
# so this is generous; a stuck connection is abandoned after PART_ATTEMPTS
# tries instead of Pyrogram's ten.
PART_REQUEST_TIMEOUT = 30
PART_ATTEMPTS = 3
# FLOOD_PREMIUM_WAIT / FLOOD_WAIT shorter than this are slept through.
PART_SLEEP_THRESHOLD = 60


class CdnRedirect(Exception):
    """The file is served from a CDN DC; use Pyrogram's own downloader."""


def file_location(file_id: FileId):
    """Input location for ``upload.GetFile`` (mirrors ``Client.get_file``)."""
    file_type = file_id.file_type
    if file_type == FileType.CHAT_PHOTO:
        if file_id.chat_id > 0:
            peer = raw.types.InputPeerUser(
                user_id=file_id.chat_id, access_hash=file_id.chat_access_hash
            )
        elif file_id.chat_access_hash == 0:
            peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
        else:
            peer = raw.types.InputPeerChannel(
                channel_id=utils.get_channel_id(file_id.chat_id),
                access_hash=file_id.chat_access_hash,
            )
        return raw.types.InputPeerPhotoFileLocation(
            peer=peer,
            photo_id=file_id.media_id,
            big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
        )
    if file_type == FileType.PHOTO:
        return raw.types.InputPhotoFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size=file_id.thumbnail_size,
        )
    return raw.types.InputDocumentFileLocation(
        id=file_id.media_id,
        access_hash=file_id.access_hash,
        file_reference=file_id.file_reference,
        thumb_size=file_id.thumbnail_size,
    )


class MediaSessionPool:
    """Extra connections per media DC, shared by all downloads of a client."""

    def __init__(self, client):
        self.client = client
        self._extra: Dict[int, List[Session]] = {}
        self._epoch: Dict[int, int] = {}
        self._limiters: Dict[int, Tuple[int, asyncio.Semaphore]] = {}
        self._lock = asyncio.Lock()

    def limiter(self, dc_id: int, limit: int) -> asyncio.Semaphore:
        """Semaphore capping the part requests in flight to ``dc_id``."""
        limit = max(limit, 1)
        current = self._limiters.get(dc_id)
        if current is None or current[0] != limit:
            # Requests holding the old semaphore finish against it.
            current = self._limiters[dc_id] = (limit, asyncio.Semaphore(limit))
        return current[1]

    async def sessions(self, dc_id: int, count: int, epoch: int = 0) -> List[Session]:
        """Pyrogram's media session for ``dc_id`` plus up to ``count - 1`` extra."""
        base = await get_session(self.client, dc_id)
        if count <= 1:
            return [base]
        async with self._lock:
            extra = self._extra.setdefault(dc_id, [])
            if self._epoch.get(dc_id, epoch) != epoch:
                # The network route changed (e.g. a Clash node switch): drop
                # connections pinned to the old route.
                await self._stop(extra)
                extra.clear()
            self._epoch[dc_id] = epoch
            test_mode = await self.client.storage.test_mode()
            while len(extra) < count - 1:
                session = Session(
                    self.client, dc_id, base.auth_key, test_mode, is_media=True
                )
                await session.start()
                extra.append(session)
                logger.debug(
                    "Opened extra media connection {} to DC{}", len(extra) + 1, dc_id
                )
            return [base] + extra[: count - 1]

    @staticmethod
    async def _stop(sessions: List[Session]):
        for session in sessions:
            try:
                await session.stop()
            except Exception:  # pylint: disable = W0718
                pass

    async def close(self):
        """Stop all extra connections (Pyrogram stops its own on client.stop)."""
        async with self._lock:
            for sessions in self._extra.values():
                await self._stop(sessions)
            self._extra.clear()


_pools: Dict[int, MediaSessionPool] = {}


def get_pool(client) -> MediaSessionPool:
    """The session pool attached to ``client``."""
    pool = _pools.get(id(client))
    if pool is None or pool.client is not client:
        pool = _pools[id(client)] = MediaSessionPool(client)
    return pool


async def close_pool(client):
    """Close the extra connections of ``client``."""
    pool = _pools.pop(id(client), None)
    if pool:
        await pool.close()


# pylint: disable = R0913, R0914
async def iter_file_parallel(
    client,
    file_id: FileId,
    file_size: int,
    offset_parts: int = 0,
    *,
    connections: int = 2,
    threads: int = 4,
    max_in_flight: int = MAX_IN_FLIGHT,
    progress: Optional[Callable] = None,
    progress_args: Tuple = (),
    epoch: int = 0,
    sessions: Optional[List[Session]] = None,
    limiter: Optional[asyncio.Semaphore] = None,
) -> AsyncGenerator[bytes, None]:
    """Yield the parts of a file in order, fetching ``threads`` parts at once.

    ``offset_parts`` counts 1 MB parts, as in ``Client.get_file``.  Raises
    ``CdnRedirect`` when the file must be fetched through a CDN.  ``sessions``
    and ``limiter`` default to the client's shared pool.
    """
    location = file_location(file_id)
    if sessions is None:
        pool = get_pool(client)
        sessions = await pool.sessions(file_id.dc_id, max(connections, 1), epoch)
        if limiter is None:
            limiter = pool.limiter(file_id.dc_id, max_in_flight)
    if limiter is None:
        limiter = asyncio.Semaphore(max(max_in_flight, 1))
    threads = max(threads, 1)
    total_parts = -(-file_size // PART_SIZE) if file_size else None

    pending: Deque[Tuple[int, asyncio.Task]] = deque()
    next_part = offset_parts

    async def fetch(index: int):
        query = raw.functions.upload.GetFile(
            location=location, offset=index * PART_SIZE, limit=PART_SIZE
        )
        attempt = 0
        while True:
            # A retry moves to the next connection in case this one is stuck.
            session = sessions[(index + attempt) % len(sessions)]
            async with limiter:
                try:
                    return await session.invoke(
                        query,
                        retries=0,
                        timeout=PART_REQUEST_TIMEOUT,
                        sleep_threshold=PART_SLEEP_THRESHOLD,
                    )
                except (OSError, InternalServerError, ServiceUnavailable) as error:
                    attempt += 1
                    if attempt >= PART_ATTEMPTS:
                        raise
                    logger.debug(
                        "Part {} of DC{} failed ({}), retrying",
                        index,
                        file_id.dc_id,
                        error or type(error).__name__,
                    )
            await asyncio.sleep(0.5 * attempt)

    def schedule():
        nonlocal next_part
        while len(pending) < threads and (
            total_parts is None or next_part < total_parts
        ):
            task = asyncio.ensure_future(fetch(next_part))
            pending.append((next_part, task))
            next_part += 1
            # Without a known size, probe one part at a time until EOF.
            if total_parts is None:
                break

    try:
        schedule()
        while pending:
            index, task = pending.popleft()
            result = await task
            if isinstance(result, raw.types.upload.FileCdnRedirect):
                raise CdnRedirect()
            chunk = result.bytes
            if chunk:
                yield chunk
            done = min((index + 1) * PART_SIZE, file_size) if file_size else (
                index * PART_SIZE + len(chunk)
            )
            if progress:
                call = functools.partial(progress, done, file_size, *progress_args)
                if inspect.iscoroutinefunction(progress):
                    await call()
                else:
                    call()
            if len(chunk) < PART_SIZE:
                break
            schedule()
    finally:
        for _, task in pending:
            task.cancel()
        for _, task in pending:
            try:
                await task
            except BaseException:  # pylint: disable = W0718
                pass
