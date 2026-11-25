import asyncio
import logging
from io import BytesIO

from PIL import Image

from wavecymatix.lib.abstracts import AsyncService

log = logging.getLogger(__name__)

WINSDK_INSTALLED = False
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus,
    )
    from winsdk.windows.storage.streams import DataReader
    WINSDK_INSTALLED = True
except Exception:
    GlobalSystemMediaTransportControlsSessionManager = None
    GlobalSystemMediaTransportControlsSessionPlaybackStatus = None
    DataReader = None
    WINSDK_INSTALLED = False


class WindowsMedia(AsyncService):
    """Windows media integration using GSMTC WinRT APIs via winsdk."""

    SUPPORTED_PLATFORMS = {"win32"}

    @classmethod
    def is_supported(cls):
        return super().is_supported() and WINSDK_INSTALLED

    def __init__(self, config, now_playing):
        super().__init__()
        self.config = config
        self.now_playing = now_playing

        # Public state properties for UI binding
        self.handler_active = False
        self.handler_playlist = False

        # Internal state
        self._manager = None
        self._session = None
        self._session_app_id = None
        self._playing = False
        self._last_signature = None
        
        # True only while WindowsMedia itself owns the currently displayed track,
        # so it never clobbers track info set by another source (e.g. AudioLookup/Shazam)
        self._owns_track_info = False

    async def _ensure_manager(self):
        if not WINSDK_INSTALLED:
            return False
        if self._manager is None:
            log.info("Requesting GSMTC session manager...")
            try:
                self._manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
            except Exception:
                log.exception("Failed to acquire GSMTC session manager")
                return False
            log.info("GSMTC session manager acquired: %s", self._manager)
        return self._manager is not None

    async def _refresh_session(self):
        if not await self._ensure_manager():
            if self._session is not None:
                log.info("GSMTC session manager unavailable; clearing session")
            self._session = None
            self._session_app_id = None
            self.handler_active = False
            self._playing = False
            return

        try:
            session = self._manager.get_current_session()
        except Exception:
            log.exception("Failed to get current GSMTC session")
            session = None

        app_id = getattr(session, "source_app_user_model_id", None) if session is not None else None
        if app_id != self._session_app_id:
            if app_id is not None:
                log.info("GSMTC session acquired: %s", app_id)
            elif self._session_app_id is not None:
                log.info("GSMTC session ended (no app currently reporting media)")
            self._session_app_id = app_id

        self._session = session
        self.handler_active = self._session is not None

    async def _load_thumbnail_rgba(self, thumbnail_ref):
        if thumbnail_ref is None:
            return None

        try:
            stream = await thumbnail_ref.open_read_async()
            size = int(stream.size)
            if size <= 0:
                return None

            reader = DataReader(stream)
            await reader.load_async(size)
            data = bytearray(size)
            reader.read_bytes(data)
            reader.detach_stream()
            stream.close()
            return Image.open(BytesIO(data)).convert("RGBA")
        except Exception:
            log.debug("Failed to decode GSMTC thumbnail", exc_info=True)
            return None

    async def _update_metadata(self):
        if not self._session:
            if self._owns_track_info:
                log.info("No GSMTC session; clearing WindowsMedia track info")
                self.now_playing.clear_track_info()
                self._owns_track_info = False
            self._last_signature = None
            return

        try:
            playback = self._session.get_playback_info()
            status = playback.playback_status
            self._playing = status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

            props = await self._session.try_get_media_properties_async()
            title = str(props.title or "")
            artist = str(props.artist or "")
            album = str(props.album_title or "")

            signature = f"{title}|{artist}|{album}|{self._playing}"
            if signature == self._last_signature:
                return

            self._last_signature = signature

            log.info(
                "GSMTC media properties: title='%s' artist='%s' album_artist='%s' album='%s' "
                "track_number=%s genres=%s playback_type=%s subtitle='%s' thumbnail=%s playing=%s",
                title, artist, str(props.album_artist or ""), album,
                props.track_number, list(props.genres), props.playback_type,
                str(props.subtitle or ""), props.thumbnail, self._playing,
            )

            if title or artist or album:
                thumbnail = await self._load_thumbnail_rgba(props.thumbnail)
                self.now_playing.set_track_info(
                    title=title,
                    artist=artist,
                    album=album,
                    album_art=thumbnail,
                )
                self.now_playing.display_track_info()
                self._owns_track_info = True
            elif self._owns_track_info:
                log.info("GSMTC session reported no metadata; clearing WindowsMedia track info")
                self.now_playing.clear_track_info()
                self._owns_track_info = False
        except Exception:
            log.exception("Failed to update Windows media metadata")

    async def _invoke(self, method_name):
        if not self._session:
            await self._refresh_session()
        if not self._session:
            return

        method = getattr(self._session, method_name, None)
        if method is None:
            return

        try:
            await method()
        except Exception:
            log.exception("Failed media control method: %s", method_name)

    def is_playing(self):
        return self._playing

    def play(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._invoke("try_play_async"), self._loop)

    def pause(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._invoke("try_pause_async"), self._loop)

    def next(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._invoke("try_skip_next_async"), self._loop)

    def previous(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._invoke("try_skip_previous_async"), self._loop)

    def stop(self):
        self.handler_active = False
        self._playing = False
        if self._owns_track_info:
            self.now_playing.clear_track_info()
            self._owns_track_info = False
        super().stop()

    async def run(self):
        log.info("WindowsMedia run loop starting (winsdk_installed=%s)", WINSDK_INSTALLED)

        if not WINSDK_INSTALLED:
            log.warning("winsdk is not installed; Windows media plugin disabled")
            self.handler_active = False
            while self._running:
                await asyncio.sleep(1.0)
            return

        while self._running:
            try:
                await self._refresh_session()
                await self._update_metadata()
            except Exception:
                log.exception("Windows media polling iteration failed")
            await asyncio.sleep(0.5)

    async def close(self):
        self.handler_active = False
        self._playing = False
        self._session = None
        self._manager = None
        self._owns_track_info = False
