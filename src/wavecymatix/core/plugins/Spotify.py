import logging
import asyncio
import time
import requests
from io import BytesIO
from PIL import Image

from wavecymatix.lib.abstracts import AsyncService

DBUS_INSTALLED = False
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType
    from dbus_next.errors import DBusError
    from dbus_next import Message, Variant
    DBUS_INSTALLED = True
except ImportError:
    MessageBus = None
    BusType = None
    DBusError = Exception
    Message = None
    Variant = None
    DBUS_INSTALLED = False

log = logging.getLogger(__name__)

SPOTIFY_CTRL_PREFIX = "rs.spotifyd.instance"
CTRL_PATH = "/rs/spotifyd/Controls"
CTRL_IFACE = "rs.spotifyd.Controls"

MPRIS_PREFIX = "org.mpris.MediaPlayer2.spotifyd.instance"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
MPRIS_PROPS_IFACE = "org.freedesktop.DBus.Properties"


class Spotify(AsyncService):
    """Spotify plugin using dbus_next to monitor Spotify Connect metadata and control playback."""

    SUPPORTED_PLATFORMS = {"linux"}

    @classmethod
    def is_supported(cls):
        return super().is_supported() and DBUS_INSTALLED
    def __init__(self, config, now_playing):
        super().__init__()
        self.config = config
        self.now_playing = now_playing
        
        # Public state properties for UI binding
        self.handler_active = False
        self.handler_playlist = False
        
        # Internal states
        self._running = False
        self._thread = None
        self._loop = None

        # DBus connection and objects
        self._bus = None
        self._player_iface = None
        self._props_iface = None

        # Component objects
        self._playing = False
        self._last_track_id = None
        self._current_mpris_bus = None

    #region Private Helper Functions

    def _on_properties_changed(self, iface, changed, invalidated):
        if iface != MPRIS_PLAYER_IFACE:
            return

        if "PlaybackStatus" in changed:
            self._playing = changed["PlaybackStatus"].value == "Playing"

        if "Metadata" in changed:
            self._handle_metadata(changed["Metadata"].value)

    def _handle_metadata(self, metadata):
        try:
            track_id = metadata.get("mpris:trackid")
            if isinstance(track_id, Variant):
                track_id = track_id.value
            track_id = str(track_id)

            if track_id == self._last_track_id:
                return
            self._last_track_id = track_id

            title = metadata.get("xesam:title", "")
            if isinstance(title, Variant):
                title = title.value

            artist_variant = metadata.get("xesam:artist", [])
            if isinstance(artist_variant, Variant):
                artist_variant = artist_variant.value

            if isinstance(artist_variant, (list, tuple)):
                artist = ", ".join(str(a) for a in artist_variant)
            else:
                artist = str(artist_variant)

            album = metadata.get("xesam:album", "")
            if isinstance(album, Variant):
                album = album.value

            art_url = metadata.get("mpris:artUrl")
            if isinstance(art_url, Variant):
                art_url = art_url.value

            album_art = None
            if art_url:
                album_art = self._fetch_artwork(art_url)

            self.now_playing.set_track_info(
                title=str(title),
                artist=str(artist),
                album=str(album),
                album_art=album_art,
            )
            self.now_playing.display_track_info()

        except Exception:
            log.exception("Metadata handling failed")

    def _fetch_artwork(self, url):
        try:
            if url.startswith("file://"):
                path = url[7:]
                img = Image.open(path)
            else:
                r = requests.get(url, timeout=5)
                r.raise_for_status()
                img = Image.open(BytesIO(r.content))
            return img.convert("RGBA")
        except Exception:
            log.warning("Artwork load failed")
            return None

    async def _find_spotifyd_control(self):
        msg = Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="ListNames"
        )
        reply = await self._bus.call(msg)
        names = reply.body[0]

        for name in names:
            if name.startswith(SPOTIFY_CTRL_PREFIX):
                return name
        return None

    async def _transfer_playback(self):
        ctrl_bus = await self._find_spotifyd_control()
        if not ctrl_bus:
            return

        msg = Message(
            destination=ctrl_bus,
            path=CTRL_PATH,
            interface=CTRL_IFACE,
            member="TransferPlayback"
        )
        await self._bus.call(msg)

    async def _connect_mpris(self, mpris_bus):
        introspection = await self._bus.introspect(mpris_bus, MPRIS_PATH)
        obj = self._bus.get_proxy_object(mpris_bus, MPRIS_PATH, introspection)

        self._player_iface = obj.get_interface(MPRIS_PLAYER_IFACE)
        self._props_iface = obj.get_interface(MPRIS_PROPS_IFACE)
        self._props_iface.on_properties_changed(self._on_properties_changed)

        props = await self._props_iface.call_get_all(MPRIS_PLAYER_IFACE)

        if "PlaybackStatus" in props:
            self._playing = props["PlaybackStatus"].value == "Playing"

        if "Metadata" in props:
            self._handle_metadata(props["Metadata"].value)

        self._current_mpris_bus = mpris_bus
        self.handler_active = True

    def _on_name_owner_changed(self, name, old_owner, new_owner):
        if name == self._current_mpris_bus and new_owner == "":
            self.now_playing.clear_track_info()
            self.handler_active = False
            self._player_iface = None
            self._props_iface = None

    async def _wait_for_mpris(self, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline and self._running:
            msg = Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="ListNames"
            )
            reply = await self._bus.call(msg)
            names = reply.body[0]

            for name in names:
                if name.startswith(MPRIS_PREFIX):
                    return name

            await asyncio.sleep(0.2)

        return None

    #endregion

    #region Public Playback Functions

    def is_playing(self):
        return self._playing

    def play(self):
        if self._player_iface and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._player_iface.call_play(),
                self._loop
            )

    def pause(self):
        if self._player_iface and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._player_iface.call_pause(),
                self._loop
            )

    def stop(self):
        self.handler_active = False
        self.now_playing.clear_track_info()
        self.pause()
        super().stop()

    def next(self):
        if self._player_iface and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._player_iface.call_next(),
                self._loop
            )

    def previous(self):
        if self._player_iface and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._player_iface.call_previous(),
                self._loop
            )

    def get_playlist(self, addr=None):
        return []

    #endregion

    #region Main Component Functions

    async def run(self):
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._loop = asyncio.get_running_loop()
        log.info("Spotify DBus loop started")

        while self._running:
            try:
                await self._transfer_playback()

                mpris_bus = await self._wait_for_mpris(timeout=5.0)
                if not mpris_bus:
                    await asyncio.sleep(1)
                    continue

                await self._connect_mpris(mpris_bus)

                introspection = await self._bus.introspect(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus"
                )
                obj = self._bus.get_proxy_object(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    introspection
                )
                dbus_iface = obj.get_interface("org.freedesktop.DBus")
                dbus_iface.on_name_owner_changed(
                    self._on_name_owner_changed
                )

                while self._running:
                    await asyncio.sleep(0.25)

            except DBusError:
                await asyncio.sleep(1)
            except Exception:
                log.exception("Spotify runtime error")
                await asyncio.sleep(1)

        log.info("Spotify async runner exiting")

    async def close(self):
        self.stop()
        self.now_playing.clear_track_info()
        self.handler_active = False

    #endregion
