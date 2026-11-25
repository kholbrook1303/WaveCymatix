import threading
import asyncio
import logging
import os
import tempfile
import traceback

from PIL import Image

from wavecymatix.lib.abstracts import AsyncService

DBUS_INSTALLED = False
try:
    from dbus_next import Variant
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType
    from dbus_next.errors import DBusError
    DBUS_INSTALLED = True
except ImportError:
    Variant = None
    MessageBus = None
    BusType = None
    DBusError = Exception
    DBUS_INSTALLED = False

log = logging.getLogger(__name__)


class Bluetooth(AsyncService):
    """Controller for monitoring Bluetooth audio devices and retrieving metadata."""

    SUPPORTED_PLATFORMS = {"linux"}
    MAX_TEXTURE_SIZE = 2048

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
        self._obj = None
        self._obex_bus = None
        self._obex_obj = None

        # Component objects
        self._player_objects = {}
        self._last_metadata = {}
        self._signal_handlers = {}
        self._active_addr = None
        self._obex_sessions = {}
        self._artwork_tasks = {}
        self._last_artwork_handle = {}

    #region Private Helpers

    def _unwrap(self, v):
        return getattr(v, "value", v) if v is not None else None

    async def _init_dbus(self):
        log.info("Initializing Bluetooth DBus connection")
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        intro = await self._bus.introspect("org.bluez", "/")
        self._obj = self._bus.get_proxy_object("org.bluez", "/", intro)

        # Optional: OBEX service is required for cover-art retrieval but may
        # be absent on older BlueZ setups.
        try:
            self._obex_bus = await MessageBus(bus_type=BusType.SESSION).connect()
            obex_intro = await self._obex_bus.introspect("org.bluez.obex", "/org/bluez/obex")
            self._obex_obj = self._obex_bus.get_proxy_object(
                "org.bluez.obex",
                "/org/bluez/obex",
                obex_intro,
            )
            log.warning("Bluetooth OBEX initialized and available")
        except Exception as e:
            self._obex_bus = None
            self._obex_obj = None
            log.warning(f"Bluetooth OBEX unavailable. Cover art disabled: {e}")

    async def _get_audio_devices(self):
        manager = self._obj.get_interface(
            "org.freedesktop.DBus.ObjectManager"
        )

        objects = await manager.call_get_managed_objects()

        devices = {}

        for path, interfaces in objects.items():
            props = interfaces.get("org.bluez.Device1")
            if not props:
                continue

            if props.get("Connected", False):
                addr = self._unwrap(props.get("Address"))
                devices[addr] = path

        return devices

    async def _find_player_for_device(self, device_path):
        manager = self._obj.get_interface(
            "org.freedesktop.DBus.ObjectManager"
        )

        objects = await manager.call_get_managed_objects()

        for path, interfaces in objects.items():
            if (
                path.startswith(device_path)
                and "org.bluez.MediaPlayer1" in interfaces
            ):
                intro = await self._bus.introspect("org.bluez", path)

                log.info(f"Found MediaPlayer1: {path}")

                return self._bus.get_proxy_object("org.bluez", path, intro)

        return None

    def _get_active_player(self):
        log.info(f"_get_active_player called. active_addr={self._active_addr}, players={list(self._player_objects.keys())}")
        if self._active_addr in self._player_objects:
            log.info(f"Using active player: {self._active_addr}")
            return self._player_objects[self._active_addr].get_interface(
                "org.bluez.MediaPlayer1"
            )

        if len(self._player_objects) == 1:
            addr, obj = next(iter(self._player_objects.items()))
            self._active_addr = addr
            log.info(f"Only one player found. Auto-selecting {addr}")
            return obj.get_interface("org.bluez.MediaPlayer1")

        log.info("No active Bluetooth player available")
        return None

    async def _get_track(self, player_obj):
        props_iface = player_obj.get_interface(
            "org.freedesktop.DBus.Properties"
        )

        try:
            value = await props_iface.call_get(
                "org.bluez.MediaPlayer1",
                "Track",
            )
            track = self._unwrap(value) or {}
            if not isinstance(track, dict):
                return {}
            return {
                key: self._unwrap(val)
                for key, val in track.items()
            }
        except Exception:
            log.exception("Failed reading MediaPlayer1.Track")
            return {}

    async def _get_obex_port(self, player_obj):
        props_iface = player_obj.get_interface(
            "org.freedesktop.DBus.Properties"
        )

        try:
            value = await props_iface.call_get(
                "org.bluez.MediaPlayer1",
                "ObexPort",
            )
            port = self._unwrap(value)
            log.warning(f"Bluetooth OBEX ObexPort payload: {port}")
            return int(port) if port is not None else None
        except Exception as e:
            # Older BlueZ versions may not expose ObexPort.
            log.warning(f"Bluetooth OBEX ObexPort unavailable: {e}")
            return None

    async def _get_adapter_address(self, addr):
        try:
            devices = await self._get_audio_devices()
            device_path = devices.get(addr)
            if not device_path:
                return None
            adapter_path = device_path.rsplit("/", 1)[0]
            intro = await self._bus.introspect("org.bluez", adapter_path)
            adapter = self._bus.get_proxy_object("org.bluez", adapter_path, intro)
            props = adapter.get_interface("org.freedesktop.DBus.Properties")
            source = self._unwrap(await props.call_get("org.bluez.Adapter1", "Address"))
            log.warning(f"OBEX Source adapter for {addr}: {source}")
            return source
        except Exception as e:
            log.warning(f"Could not resolve adapter address for {addr}: {e!r}")
            return None

    async def _create_cover_art_session(self, addr, port):
        if not self._obex_obj or port is None:
            return None

        existing = self._obex_sessions.get(addr)
        if existing:
            return existing

        client = self._obex_obj.get_interface(
            "org.bluez.obex.Client1"
        )

        args = {
            "Target": Variant("s", "bip-avrcp"),
            "PSM": Variant("q", int(port)),
        }

        # obexd may bind to the wrong/any adapter without an explicit Source.
        source = await self._get_adapter_address(addr)
        if source:
            args["Source"] = Variant("s", source)

        try:
            log.warning(f"Creating OBEX cover-art session for {addr} with PSM={port}")
            session_path = await client.call_create_session(addr, args)
            self._obex_sessions[addr] = session_path
            log.warning(f"Created OBEX cover-art session: {session_path}")
            return session_path
        except Exception as e:
            # str(e) is empty for many dbus-next errors; log type, repr and D-Bus error fields.
            log.warning(
                f"Failed to create OBEX cover-art session for {addr}: "
                f"type={type(e).__name__} repr={e!r} "
                f"dbus_type={getattr(e, 'type', None)!r} dbus_text={getattr(e, 'text', None)!r} "
                f"args={args}"
            )
            log.warning(f"OBEX CreateSession traceback:\n{traceback.format_exc()}")
            return None

    async def _remove_cover_art_session(self, addr):
        session_path = self._obex_sessions.pop(addr, None)
        if not session_path or not self._obex_obj:
            return

        try:
            client = self._obex_obj.get_interface("org.bluez.obex.Client1")
            await client.call_remove_session(session_path)
            log.warning(f"Removed OBEX cover-art session for {addr}")
        except Exception as e:
            log.warning(f"Failed to remove OBEX cover-art session for {addr}: {e}")

    async def _wait_for_file_ready(self, target_file, timeout_seconds=10, stable_polls=3):
        if not target_file:
            return None

        end_time = asyncio.get_running_loop().time() + timeout_seconds
        last_size = -1
        stable_count = 0

        while asyncio.get_running_loop().time() < end_time:
            if os.path.exists(target_file):
                size = os.path.getsize(target_file)
                if size > 0:
                    if size == last_size:
                        stable_count += 1
                    else:
                        stable_count = 1
                        last_size = size

                    if stable_count >= stable_polls:
                        log.warning(f"OBEX file ready: {target_file} size={size}")
                        return target_file

            await asyncio.sleep(0.2)

        return None

    async def _wait_for_transfer(self, transfer_path, target_file=None, timeout_seconds=10):
        if not self._obex_bus or not transfer_path:
            return await self._wait_for_file_ready(target_file, timeout_seconds)

        intro = await self._obex_bus.introspect("org.bluez.obex", transfer_path)
        transfer_obj = self._obex_bus.get_proxy_object(
            "org.bluez.obex",
            transfer_path,
            intro,
        )
        props_iface = transfer_obj.get_interface("org.freedesktop.DBus.Properties")

        end_time = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < end_time:
            try:
                status = self._unwrap(
                    await props_iface.call_get("org.bluez.obex.Transfer1", "Status")
                )
            except DBusError as e:
                log.info(f"OBEX transfer status polling unavailable ({e}); falling back to file readiness")
                return await self._wait_for_file_ready(target_file, timeout_seconds)

            log.warning(f"OBEX transfer status: {status} path={transfer_path}")

            if status == "complete":
                try:
                    filename = self._unwrap(
                        await props_iface.call_get("org.bluez.obex.Transfer1", "Filename")
                    )
                except DBusError:
                    filename = target_file
                return filename

            if status == "error":
                log.warning(f"OBEX transfer failed for path={transfer_path}")
                return None

            await asyncio.sleep(0.2)

        log.warning(f"OBEX transfer timed out for path={transfer_path}")
        return None

    def _extract_transfer_path(self, result):
        # org.bluez.obex.Image1.Get returns (object, dict). Depending on
        # dbus-next decoding this can appear as tuple or list.
        if isinstance(result, str):
            return result

        if isinstance(result, (tuple, list)) and len(result) > 0:
            path = result[0]
            if isinstance(path, str) and path.startswith("/"):
                return path

        return None

    def _load_album_art_image(self, artwork_file):
        try:
            img = Image.open(artwork_file)
            img.load()
            cover_art = img.convert("RGBA")

            w, h = cover_art.size
            if w > self.MAX_TEXTURE_SIZE or h > self.MAX_TEXTURE_SIZE:
                ratio = min(self.MAX_TEXTURE_SIZE / w, self.MAX_TEXTURE_SIZE / h)
                cover_art = cover_art.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

            return cover_art
        except Exception as e:
            log.warning(f"Failed to load Bluetooth artwork image '{artwork_file}': {e}")
            return None

    async def _download_cover_art(self, addr, player_obj):
        if not self._obex_obj or not self._obex_bus:
            return None

        port = await self._get_obex_port(player_obj)
        if port is None:
            return None

        session_path = await self._create_cover_art_session(addr, port)
        if not session_path:
            return None

        handle = None
        for _ in range(10):
            track = await self._get_track(player_obj)
            handle = track.get("ImgHandle")
            log.warning(f"Track payload during artwork poll for {addr}: {track}")
            if handle:
                break
            await asyncio.sleep(0.2)

        if not handle:
            log.warning(f"No ImgHandle exposed for {addr} after OBEX session setup")
            return None

        if self._last_artwork_handle.get(addr) == handle:
            return None

        session_intro = await self._obex_bus.introspect("org.bluez.obex", session_path)
        session_obj = self._obex_bus.get_proxy_object("org.bluez.obex", session_path, session_intro)
        image_iface = session_obj.get_interface("org.bluez.obex.Image1")

        image_properties = await image_iface.call_properties(handle)
        log.warning(f"OBEX image properties for {addr}: {image_properties}")

        description = {}
        if image_properties:
            for entry in image_properties:
                plain = {k: self._unwrap(v) for k, v in entry.items()}
                if plain.get("type") == "native":
                    description = entry
                    break

        safe_addr = addr.replace(":", "_")
        fd, target_file = tempfile.mkstemp(prefix=f"bluetooth_art_{safe_addr}_", suffix=".img")
        os.close(fd)

        result = await image_iface.call_get(target_file, handle, description)
        log.warning(f"OBEX image get result for {addr}: {result}")

        transfer_path = self._extract_transfer_path(result)
        transfer_file = None
        if isinstance(result, (tuple, list)) and len(result) > 1 and isinstance(result[1], dict):
            transfer_file = self._unwrap(result[1].get("Filename"))

        if not transfer_path:
            log.warning(f"No transfer path returned from OBEX image get for {addr}")
            return None

        final_file = await self._wait_for_transfer(
            transfer_path,
            target_file=transfer_file or target_file,
        )
        if not final_file:
            if os.path.exists(target_file):
                final_file = target_file
            else:
                return None

        if not os.path.exists(final_file):
            return None

        if os.path.getsize(final_file) == 0:
            return None

        self._last_artwork_handle[addr] = handle
        return final_file

    async def _fetch_artwork_for_track(self, addr, player_obj):
        try:
            artwork_file = await self._download_cover_art(addr, player_obj)
            if not artwork_file:
                return

            cover_art = self._load_album_art_image(artwork_file)
            if cover_art is None:
                return

            metadata = self._last_metadata.get(addr, {})
            if not metadata:
                return

            same_track = (
                self.now_playing.text == (metadata.get("Title") or "") and
                self.now_playing.artist == (metadata.get("Artist") or "") and
                self.now_playing.album == (metadata.get("Album") or "")
            )

            if same_track:
                # NowPlayingUI ignores identical text updates; clear first so artwork-only
                # refresh for the current track is applied.
                self.now_playing.clear_track_info()

            self.now_playing.set_track_info(
                metadata.get("Title"),
                artist=metadata.get("Artist"),
                album=metadata.get("Album"),
                album_art=cover_art,
            )

            metadata["ArtworkPath"] = artwork_file
            self._last_metadata[addr] = metadata
            log.warning(f"Applied Bluetooth artwork for {addr}: {artwork_file}")
        except Exception:
            log.exception(f"Failed applying Bluetooth artwork for {addr}")

    def _schedule_artwork_fetch(self, addr, player_obj):
        if not self._loop:
            return

        old_task = self._artwork_tasks.get(addr)
        if old_task and not old_task.done():
            old_task.cancel()

        self._artwork_tasks[addr] = asyncio.create_task(
            self._fetch_artwork_for_track(addr, player_obj)
        )

    def _handle_track_update(self, addr, track_dict):

        track_dict = self._unwrap(track_dict) or {}

        if not isinstance(track_dict, dict):
            track_dict = {}

        track = {
            key: self._unwrap(value)
            for key, value in track_dict.items()
        }

        log.warning(f"Bluetooth track payload [{addr}]: {track}")

        title = track.get("Title")
        artist = track.get("Artist")
        album = track.get("Album")
        img_handle = track.get("ImgHandle")

        track_info = {
            "Title": title,
            "Artist": artist,
            "Album": album,
            "ArtworkURL": None,
            "ImgHandle": img_handle,
        }

        if not title:
            if addr in self._last_metadata:
                log.info(f"Bluetooth cleared track for {addr}")
                self.now_playing.clear_track_info()
                self._last_metadata.pop(addr, None)
            return

        if track_info != self._last_metadata.get(addr):

            log.info(
                f"Bluetooth track update {addr}: {artist} - {title}"
            )

            self._active_addr = addr

            self.now_playing.set_track_info(
                title,
                artist=artist,
                album=album,
                album_art=None,
            )

            self._last_metadata[addr] = track_info

            player_obj = self._player_objects.get(addr)
            if player_obj:
                self._schedule_artwork_fetch(addr, player_obj)

    def _on_properties_changed(self, addr):

        def handler(interface, changed, invalidated):

            if interface != "org.bluez.MediaPlayer1":
                return

            if "Track" in changed:
                log.debug(f"Track signal received from {addr}")
                self._handle_track_update(addr, changed["Track"])

            if "Status" in changed:

                status = self._unwrap(changed["Status"])

                log.info(f"Status change {addr}: {status}")

                if status == "stopped":
                    if addr in self._last_metadata:
                        log.info(f"Bluetooth stopped: {addr}")
                        self.now_playing.clear_track_info()
                        self._last_metadata.pop(addr, None)

        return handler

    #endregion

    #region Public Playback Functions

    def is_playing(self):

        player_obj = self._player_objects.get(self._active_addr)

        if not player_obj or not self._loop:
            return False

        async def _check():
            try:

                props_iface = player_obj.get_interface(
                    "org.freedesktop.DBus.Properties"
                )

                status_variant = await props_iface.call_get(
                    "org.bluez.MediaPlayer1",
                    "Status",
                )

                status = self._unwrap(status_variant)

                return status == "playing"

            except Exception:
                return False

        future = asyncio.run_coroutine_threadsafe(_check(), self._loop)

        try:
            return future.result(timeout=2)
        except Exception:
            return False

    def play(self):
        player = self._get_active_player()

        log.info(f"Play requested. player={player is not None}, loop={self._loop is not None}")

        if player and self._loop:

            async def _play():
                try:
                    log.debug("Calling DBus Play()")
                    await player.call_play()
                    log.debug("DBus Play() succeeded")
                except Exception as e:
                    log.exception(f"DBus Play() failed: {e}")

            asyncio.run_coroutine_threadsafe(_play(), self._loop)

    def pause(self):
        player = self._get_active_player()

        log.info(f"Pause requested. player={player is not None}, loop={self._loop is not None}")

        if player and self._loop:

            async def _pause():
                try:
                    log.debug("Calling DBus Pause()")
                    await player.call_pause()
                    log.debug("DBus Pause() succeeded")
                except Exception as e:
                    log.exception(f"DBus Pause() failed: {e}")

            asyncio.run_coroutine_threadsafe(_pause(), self._loop)

    def next(self):
        player = self._get_active_player()

        log.info(f"Next requested. player={player is not None}, loop={self._loop is not None}")

        if player and self._loop:

            async def _next():
                try:
                    log.debug("Calling DBus Next()")
                    await player.call_next()
                    log.debug("DBus Next() succeeded")
                except Exception as e:
                    log.exception(f"DBus Next() failed: {e}")

            asyncio.run_coroutine_threadsafe(_next(), self._loop)

    def previous(self):
        player = self._get_active_player()

        log.info(f"Previous requested. player={player is not None}, loop={self._loop is not None}")

        if player and self._loop:

            async def _previous():
                try:
                    log.debug("Calling DBus Previous()")
                    await player.call_previous()
                    log.debug("DBus Previous() succeeded")
                except Exception as e:
                    log.exception(f"DBus Previous() failed: {e}")

            asyncio.run_coroutine_threadsafe(_previous(), self._loop)

    def stop(self):
        self.pause()
        super().stop()
        return 

    def get_playlist(self, addr=None):
        return []

    #endregion

    #region Main Component Functions

    async def run(self):
        self._loop = asyncio.get_running_loop()
        log.info(f"Bluetooth event loop captured: {self._loop}")

        await self._init_dbus()

        log.info("Bluetooth monitor started")

        while self._running:
            try:

                devices = await self._get_audio_devices()

                connected = set(devices.keys())
                known = set(self._player_objects.keys())

                # Handle disconnects
                for addr in known - connected:

                    log.info(f"Bluetooth device disconnected: {addr}")

                    if addr == self._active_addr:
                        self._active_addr = None

                    self._player_objects.pop(addr, None)
                    self._signal_handlers.pop(addr, None)
                    self._last_metadata.pop(addr, None)
                    self._last_artwork_handle.pop(addr, None)

                    task = self._artwork_tasks.pop(addr, None)
                    if task and not task.done():
                        task.cancel()

                    await self._remove_cover_art_session(addr)

                    self.now_playing.clear_track_info()

                # Handle connections
                for addr, path in devices.items():

                    try:

                        player_obj = self._player_objects.get(addr)

                        # Player may appear AFTER device connects
                        if not player_obj:

                            player_obj = await self._find_player_for_device(path)

                            if not player_obj:
                                continue

                            log.info(f"Registering player for {addr}")

                            self._player_objects[addr] = player_obj

                            props_iface = player_obj.get_interface(
                                "org.freedesktop.DBus.Properties"
                            )

                            try:
                                supported = await props_iface.call_get(
                                    "org.bluez.MediaPlayer1",
                                    "SupportedFeatures",
                                )
                                log.info(f"{addr} SupportedFeatures: {self._unwrap(supported)}")
                            except Exception:
                                log.info(f"{addr} SupportedFeatures: unavailable")

                            handler = self._on_properties_changed(addr)

                            props_iface.on_properties_changed(handler)

                            self._signal_handlers[addr] = handler

                            # fetch current track immediately
                            try:
                                track_variant = await props_iface.call_get(
                                    "org.bluez.MediaPlayer1",
                                    "Track",
                                )

                                self._handle_track_update(
                                    addr, track_variant
                                )

                            except DBusError:
                                pass

                    except Exception:
                        log.exception(
                            f"Bluetooth device error: {addr}"
                        )

                self.handler_active = bool(self._player_objects)

                await asyncio.sleep(2)

            except asyncio.CancelledError:
                break

            except Exception:
                log.exception("Bluetooth monitor error")
                await asyncio.sleep(2)

        log.info("Bluetooth monitor exiting")

    async def close(self):
        self.stop()

        for addr, task in list(self._artwork_tasks.items()):
            if task and not task.done():
                task.cancel()
            self._artwork_tasks.pop(addr, None)

        for addr in list(self._obex_sessions.keys()):
            await self._remove_cover_art_session(addr)

        self.now_playing.clear_track_info()
        self.handler_active = False

    #endregion