"""TikTok-only desktop sidecar. Never imports or calls the market engine."""
import asyncio
import contextlib
import json
import re
import sys
import threading
import time
from typing import Literal

from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.routes.fetch_room_id_api import FetchRoomIdAPIRoute
from TikTokLive.events import (CommentEvent, ConnectEvent, FollowEvent, GiftEvent, JoinEvent,
                               LiveEndEvent, RoomUserSeqEvent, ShareEvent)
from pydantic import BaseModel, ConfigDict


class TikTokStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: Literal['LIVE', 'OFFLINE', 'CONNECTING', 'UNKNOWN', 'NOT_CONFIGURED']
    username: str | None
    viewers: int | None = None
    live_since_ms: int | None = None
    last_checked_ms: int
    error: str | None = None


class TikTokWatcher(threading.Thread):
    """Own thread and asyncio loop; configuration never waits on network I/O."""
    def __init__(self):
        super().__init__(daemon=True, name='TikTokStatus')
        self.ready = threading.Event()
        self.status = TikTokStatus(state='NOT_CONFIGURED', username=None, last_checked_ms=int(time.time()*1000))

    def configure(self, config):
        self.ready.wait(5)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, config)

    def publish(self, state, event=None, **changes):
        self.status = TikTokStatus.model_validate(self.status.model_dump() | {
            'state': state, 'last_checked_ms': int(time.time()*1000), **changes})
        print(json.dumps({'event': event or 'status', 'status': self.status.model_dump()}), flush=True)

    def comment(self, event):
        """A live comment, for the LetsTalk speaker to answer by name.

        Mirrors welcome() exactly: one JSON line on stdout, which Electron appends to
        runtime/desktop/tiktok-events.jsonl. The text and the handle are passed through UNTOUCHED - the speaker
        sanitises names at its own Event boundary, and cleaning them here would hide what TikTok actually sent.
        This sidecar still never imports or calls the market engine.
        """
        user = getattr(event, 'user', None)
        name = (
            getattr(user, 'nickname', None)
            or getattr(user, 'display_id', None)
            or getattr(user, 'unique_id', None)
            or getattr(user, 'username', None)
        )
        text = getattr(event, 'comment', None) or getattr(event, 'text', None)
        if not name or not text:
            return
        print(json.dumps({
            'event': 'TikTokComment',
            'comment': {
                'name': str(name)[:40],
                'user_id': str(getattr(user, 'unique_id', '') or getattr(user, 'display_id', '') or name)[:64],
                'text': str(text)[:500],
                'at_ms': int(time.time()*1000),
            }
        }, ensure_ascii=False), flush=True)

    def appreciation(self, kind, event):
        """A gift, follow or share, for the speaker to thank them for.

        Same shape and same discipline as comment()/welcome(): one JSON line, handles passed through untouched,
        and the sidecar still never imports or calls the market engine. Gifts carry their name and coin value so
        he can say what someone actually sent.
        """
        user = getattr(event, 'user', None)
        name = (
            getattr(user, 'nickname', None)
            or getattr(user, 'display_id', None)
            or getattr(user, 'unique_id', None)
            or getattr(user, 'username', None)
        )
        if not name:
            return
        body = {
            'kind': kind,
            'name': str(name)[:40],
            'user_id': str(getattr(user, 'unique_id', '') or getattr(user, 'display_id', '') or name)[:64],
            'at_ms': int(time.time()*1000),
        }
        if kind == 'gift':
            gift = getattr(event, 'gift', None)
            body['gift'] = str(getattr(gift, 'name', None) or 'something')[:40]
            body['coins'] = int(getattr(gift, 'diamond_count', 0) or 0)
            # A streak gift repeats until it ends; only the final one is the real total.
            if getattr(event, 'streaking', False):
                return
        print(json.dumps({'event': 'TikTokAppreciation', 'appreciation': body}, ensure_ascii=False), flush=True)

    def welcome(self, event):
        user = getattr(event, 'user', None)
        name = (
            getattr(user, 'nickname', None)
            or getattr(user, 'display_id', None)
            or getattr(user, 'unique_id', None)
            or getattr(user, 'username', None)
        )
        if not name:
            return
        print(json.dumps({
            'event': 'TikTokViewerJoined',
            'welcome': {'name': str(name)[:40], 'at_ms': int(time.time()*1000)}
        }), flush=True)

    async def monitor(self, config):
        username = config.get('username', '').strip().lstrip('@')
        if not username:
            self.publish('NOT_CONFIGURED', username=None, error=None)
            await asyncio.Future()
        self.publish('CONNECTING', username=username, error=None)
        client = TikTokLiveClient(unique_id=username)
        sessionid = (config.get('sessionid') or '').strip()
        tt_target_idc = (config.get('tt_target_idc') or '').strip() or None
        if sessionid:
            client.web.set_session(sessionid, tt_target_idc)
        session_live = False
        connection_task = None

        @client.on(ConnectEvent)
        async def connected(_event):
            nonlocal session_live
            session_live = True
            viewers = (client.room_info or {}).get('user_count')
            self.publish('LIVE', event='TikTokLiveStarted', viewers=int(viewers) if viewers is not None else None,
                         live_since_ms=int(time.time()*1000), error=None)

        @client.on(RoomUserSeqEvent)
        async def viewers_changed(event):
            if session_live:
                self.publish('LIVE', viewers=int(event.total), error=None)

        @client.on(JoinEvent)
        async def viewer_joined(event):
            self.welcome(event)

        @client.on(CommentEvent)
        async def viewer_commented(event):
            self.comment(event)

        @client.on(GiftEvent)
        async def viewer_gifted(event):
            self.appreciation('gift', event)

        @client.on(FollowEvent)
        async def viewer_followed(event):
            self.appreciation('follow', event)

        @client.on(ShareEvent)
        async def viewer_shared(event):
            self.appreciation('share', event)

        @client.on(LiveEndEvent)
        async def ended(_event):
            nonlocal session_live
            session_live = False
            self.publish('OFFLINE', event='TikTokLiveEnded', error=None)

        try:
            while True:
                started = time.monotonic()
                if connection_task is not None and connection_task.done():
                    connection_task = None
                try:
                    live = await asyncio.wait_for(client.is_live(), 4)
                    if live:
                        if not session_live:
                            session_live = True
                            self.publish('LIVE', event='TikTokLiveStarted', live_since_ms=int(time.time()*1000), error=None)
                        if config.get('auto_connect_comments', True) and connection_task is None:
                            try:
                                connection_task = await asyncio.wait_for(client.start(fetch_room_info=True), 10)
                            except Exception as error:
                                self.publish('LIVE', error=f'Comment connection unavailable: {str(error)[:130]}')
                    else:
                        if session_live:
                            if client.connected:
                                await client.disconnect()
                            connection_task = None
                            session_live = False
                            self.publish('OFFLINE', event='TikTokLiveEnded', error=None)
                        else:
                            self.publish('OFFLINE', error=None)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.publish('UNKNOWN', error=str(error)[:180])
                interval = 15 if session_live else max(1, config.get('poll_interval_s', 30))
                await asyncio.sleep(max(.1, interval-(time.monotonic()-started)))
        finally:
            if connection_task is not None:
                connection_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await connection_task
            if connection_task is not None or client.connected:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.shield(client.disconnect(close_client=True))

    async def main(self):
        self.queue = asyncio.Queue()
        self.loop = asyncio.get_running_loop()
        self.ready.set()
        task = None
        try:
            while True:
                config = await self.queue.get()
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                if config is None:
                    break
                task = asyncio.create_task(self.monitor(config))
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    def run(self):
        asyncio.run(self.main())


async def test_connection(username):
    username = username.strip().lstrip('@')
    if not username or not re.fullmatch(r'[\w.]{1,24}', username):
        return {'outcome': 'NOT_FOUND', 'message': 'Username not found', 'profile_name': None}
    client = TikTokLiveClient(unique_id=username)
    try:
        try:
            data = (await asyncio.wait_for(FetchRoomIdAPIRoute.fetch_user_room_data(client.web, username), 6)).get('data', {})
            user = data.get('user', {})
            if str(user.get('uniqueId', '')).lower() == username.lower():
                live = await asyncio.wait_for(client.is_live(), 6)
                return {'outcome': 'LIVE' if live else 'OFFLINE',
                        'message': 'Found  live now' if live else 'Found  not live',
                        'profile_name': user.get('nickname') or username}
        except Exception:
            pass  # A non-streaming account can still be verified by its public profile.
        response = await asyncio.wait_for(client.web.get(url=f'https://www.tiktok.com/@{username}'), 10)
        if response.status_code == 404:
            return {'outcome': 'NOT_FOUND', 'message': 'Username not found', 'profile_name': None}
        response.raise_for_status()
        match = re.search(r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', response.text, re.S)
        if not match:
            raise RuntimeError('TikTok did not return a verifiable profile')
        detail = json.loads(match.group(1)).get('__DEFAULT_SCOPE__', {}).get('webapp.user-detail', {})
        info = detail.get('userInfo', {}).get('user', {})
        if detail.get('statusCode') in (10202, 10221):
            return {'outcome': 'NOT_FOUND', 'message': 'Username not found', 'profile_name': None}
        if str(info.get('uniqueId', '')).lower() != username.lower():
            raise RuntimeError('TikTok profile could not be verified')
        live = await asyncio.wait_for(client.is_live(), 10)
        return {'outcome': 'LIVE' if live else 'OFFLINE', 'message': 'Found  live now' if live else 'Found  not live',
                'profile_name': info.get('nickname') or username}
    except Exception as error:
        return {'outcome': 'UNREACHABLE', 'message': 'Could not reach TikTok', 'profile_name': None,
                'error': str(error)[:180]}
    finally:
        await client.web.close()


if __name__ == '__main__':
    if sys.argv[1] == '--watch':
        watcher = TikTokWatcher()
        watcher.start()
        try:
            for line in sys.stdin:
                watcher.configure(json.loads(line))
        finally:
            watcher.configure(None)
            watcher.join(3)
    else:
        print(json.dumps(asyncio.run(test_connection(sys.argv[1]))), flush=True)
