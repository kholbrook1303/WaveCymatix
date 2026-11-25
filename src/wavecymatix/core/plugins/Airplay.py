import asyncio
import logging
from PIL import Image

from wavecymatix.lib.abstracts import AsyncService

DBUS_INSTALLED = False
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType
    from dbus_next import Variant
    DBUS_INSTALLED = True
except ImportError:
    MessageBus = None
    BusType = None
    Variant = None
    DBUS_INSTALLED = False

log = logging.getLogger(__name__)

SERVICE = "org.gnome.ShairportSync"
PATH = "/org/gnome/ShairportSync"
REMOTE_IFACE = "org.gnome.ShairportSync.RemoteControl"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


class Airplay(AsyncService):

    SUPPORTED_PLATFORMS = {"linux"}
    MAX_TEXTURE_SIZE = 2048
    ARTWORK_WAIT = 0.5

    @classmethod
    def is_supported(cls):
        return super().is_supported() and DBUS_INSTALLED

    """Airplay plugin using dbus_next to monitor Shairport Sync metadata and control playback."""
    def __init__(self, config, now_playing):
        super().__init__()
        self.config = config
        self.now_playing = now_playing

        # Public state properties for UI binding
        self.handler_active = False
        self.handler_playlist = False

        # Internal states
        self._loop = None
        self._running = False

        # DBus connection and objects
        self._bus = None
        self._proxy = None
        self._props_iface = None
        
        # Component objects
        self._dbus_tasks = set()
        self._main_task = None
        self._pending_commit_task = None
        self._last_metadata = None
        self._player_state = None

    #region Private Helper Functions

    def _on_properties_changed(self, interface_name, changed, invalidated):
        log.info(
            "AIRPLAY DBUS: interface=%s changed=%s",
            interface_name,
            {k: v.value for k, v in changed.items()},
        )
        # Metadata
        if "Metadata" in changed:
            md = changed["Metadata"].value
            if md != self._last_metadata:
                self._last_metadata = md
                self._schedule_commit(md)

        # Playback state
        if "Active" in changed or "PlayerState" in changed:
            # Paused keeps the session active; only Active=False ends it
            active = self.handler_active
            if "PlayerState" in changed:
                state = changed["PlayerState"].value
                self._player_state = state
                if state == "Playing":
                    active = True
            if "Active" in changed:
                active = bool(changed["Active"].value)

            if active != self.handler_active:
                self.handler_active = active
                log.info(f"Airplay device active -> {self.handler_active}")
                if not active:
                    log.info("Airplay device disconnected — clearing NowPlayingUI")
                    self.now_playing.clear_track_info()

    def _schedule_commit(self, metadata):
        if not self._loop:
            return

        if self._pending_commit_task:
            self._pending_commit_task.cancel()

        self._pending_commit_task = self._loop.create_task(self._commit_after_delay(metadata))

    async def _commit_after_delay(self, metadata):
        try:
            await asyncio.sleep(self.ARTWORK_WAIT)
            self._commit_metadata(metadata)
        except asyncio.CancelledError:
            pass

    def _commit_metadata(self, md):
        title = md.get("xesam:title")
        if isinstance(title, Variant):
            title = title.value
        if not title:
            self.handler_active = False
            self.now_playing.clear_track_info()
            return

        artist = md.get("xesam:artist")
        if isinstance(artist, Variant):
            artist = artist.value
            if isinstance(artist, list):
                artist = ", ".join(artist)

        album = md.get("xesam:album")
        if isinstance(album, Variant):
            album = album.value

        cover_art = None
        art_url = md.get("mpris:artUrl")
        if isinstance(art_url, Variant):
            art_url = art_url.value
            if art_url and art_url.startswith("file://"):
                try:
                    img = Image.open(art_url[7:])
                    img.load()
                    cover_art = self._resize_album_art(img.convert("RGBA"))
                except Exception as e:
                    log.warning(f"Failed to load artwork: {e}")

        self.handler_active = True
        self.now_playing.set_track_info(title, artist=artist, album=album, album_art=cover_art)

    def _resize_album_art(self, img):
        w, h = img.size
        if w > self.MAX_TEXTURE_SIZE or h > self.MAX_TEXTURE_SIZE:
            ratio = min(self.MAX_TEXTURE_SIZE / w, self.MAX_TEXTURE_SIZE / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        return img

    def _remote_call(self, method_name):
        if not self._proxy or not self._loop:
            return

        iface = self._proxy.get_interface(REMOTE_IFACE)
        coro = getattr(iface, f"call_{method_name.lower()}")()

        task = self._loop.create_task(coro)

        self._dbus_tasks.add(task)

        def _done(t):
            self._dbus_tasks.discard(t)
            try:
                t.result()
            except (asyncio.CancelledError, Exception):
                pass

        task.add_done_callback(_done)

    def is_playing(self):
        if self._player_state is not None:
            return self._player_state == "Playing"
        if not self._proxy or not self._loop:
            return False

        async def _check():
            try:
                remote_iface = self._proxy.get_interface(
                    REMOTE_IFACE
                )

                state = await remote_iface.get_player_state()

                return state == "Playing"

            except Exception:
                return False

        future = asyncio.run_coroutine_threadsafe(_check(), self._loop)

        try:
            return future.result(timeout=2)
        except Exception:
            return False


    #endregion

    #region Public Playback Functions

    def play(self): self._remote_call("Play")
    def pause(self): self._remote_call("Pause")
    def next(self): self._remote_call("Next")
    def previous(self): self._remote_call("Previous")
    def volume_up(self): self._remote_call("VolumeUp")
    def volume_down(self): self._remote_call("VolumeDown")
    def toggle_mute(self): self._remote_call("ToggleMute")
    def get_playlist(self, addr=None): return []

    def stop(self): 
        self._remote_call("Stop")
        super().stop()

    #endregion

    #region Main Component Functions

    async def run(self):
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            introspect = await self._bus.introspect(SERVICE, PATH)
            self._proxy = self._bus.get_proxy_object(SERVICE, PATH, introspect)
            self._props_iface = self._proxy.get_interface(PROPS_IFACE)
            self._props_iface.on_properties_changed(self._on_properties_changed)
            log.info("Subscribed to PropertiesChanged signals")

            # Fetch initial metadata
            try:
                remote_iface = self._proxy.get_interface(REMOTE_IFACE)
                md = await remote_iface.get_metadata()
                if md:
                    self._schedule_commit(md)
            except Exception as e:
                log.warning(f"Initial metadata fetch failed: {e}")

            while self._running:
                await asyncio.sleep(0.25)
            log.debug('airplay ended')

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Airplay runtime error: {e}")

    async def close(self):
        try:
            self.stop()

            self.now_playing.clear_track_info()
            self.handler_active = False

            for task in list(self._dbus_tasks):
                task.cancel()

            await asyncio.gather(*self._dbus_tasks, return_exceptions=True)
            self._dbus_tasks.clear()

        except Exception:
            pass

    #endregion