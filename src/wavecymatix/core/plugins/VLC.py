import asyncio
import ctypes
import os
import random
import sys
import threading
import logging
import urllib.parse


def _configure_macos_vlc_runtime():
    if sys.platform != "darwin":
        return

    app_roots = (
        "/Applications/MacPorts/VLC.app/Contents/MacOS",
        "/Applications/VLC.app/Contents/MacOS",
        "/opt/local/libexec/vlc3",
        "/opt/homebrew/opt/vlc/lib",
        "/usr/local/opt/vlc/lib",
    )

    for app_root in app_roots:
        library_dir = os.path.join(app_root, "lib")
        if not os.path.isfile(os.path.join(library_dir, "libvlc.dylib")):
            library_dir = app_root

        libvlc_path = os.path.join(library_dir, "libvlc.dylib")
        libvlccore_path = os.path.join(library_dir, "libvlccore.dylib")
        if not os.path.isfile(libvlc_path) or not os.path.isfile(libvlccore_path):
            continue

        plugin_candidates = (
            os.path.join(app_root, "plugins"),
            os.path.join(os.path.dirname(app_root), "plugins"),
            "/opt/local/libexec/vlc3/lib/vlc/plugins",
        )
        plugin_dir = next((path for path in plugin_candidates if os.path.isdir(path)), None)

        os.environ.setdefault("PYTHON_VLC_LIB_PATH", libvlc_path)
        if plugin_dir:
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", plugin_dir)
            os.environ.setdefault("VLC_PLUGIN_PATH", plugin_dir)

        existing_dyld_path = os.environ.get("DYLD_LIBRARY_PATH")
        if library_dir not in (existing_dyld_path or "").split(os.pathsep):
            os.environ["DYLD_LIBRARY_PATH"] = os.pathsep.join(
                path for path in (library_dir, existing_dyld_path) if path
            )

        # python-vlc's Darwin fallback only checks /Applications/VLC.app.
        ctypes.CDLL(libvlccore_path, mode=ctypes.RTLD_GLOBAL)
        return


_configure_macos_vlc_runtime()

import vlc

from PIL import Image

from wavecymatix.core.MediaLibraryStore import MediaLibraryStore
from wavecymatix.lib.abstracts import AsyncService

try:
    import pyudev
except ImportError:
    pyudev = None

log = logging.getLogger(__name__)


class VLC(AsyncService):
    """VLC controller for managing physical media audio listeners such as USB and local directories."""

    SUPPORTED_PLATFORMS = {"linux", "win32", "darwin"}

    AUDIO_EXTENSIONS = (
        '.mp3', '.wav', '.flac', '.ogg', '.m4a',
        '.aac', '.wma', '.opus', '.aiff', '.ape',
    )

    @classmethod
    def is_supported(cls):
        return super().is_supported()
    def __init__(self, config, now_playing):
        super().__init__()
        self.config = config
        self.now_playing = now_playing

        # Public state properties for UI binding
        self.handler_active = False
        self.handler_playlist = True

        # Internal states
        self._running = False
        self._pending_meta = None
        self._playlist_lock = threading.RLock()
        self._meta_lock = threading.Lock()
        self._playlist_owner = "listener"

        # VLC configuration
        self._listener_enabled = self.config.vlc.get('listener_enabled', True)
        self._listener_source = self.config.vlc.get('listener_source', 'usb')
        self._listener_path = self.config.vlc.get('listener_path', '')
        self.local_path = self._listener_path
        self._shuffle = self.config.vlc.get('listener_shuffle', True)
        self._audio_extensions = self.AUDIO_EXTENSIONS

        self.playlist_store = MediaLibraryStore(
            media_type="audio_local",
            section_config=self.config.vlc,
            supported_extensions=self._audio_extensions,
            key_prefix="vlc",
            general_config=getattr(self.config, "general", {}),
            system_playlists=(),
            default_playlist="",
        )

        # VLC objects
        self._context = None
        self._monitor = None
        self._current_file_count = 0
        self._last_media_event_mgr = None
        self._vlc_instance = vlc.Instance()
        self._vlc_list_player = self._vlc_instance.media_list_player_new()
        self._vlc_media_list = self._vlc_instance.media_list_new()
        self._vlc_list_player.set_media_list(self._vlc_media_list)
        self._media_player = self._vlc_list_player.get_media_player()

    #region Private Helper Functions
    def _init_audio(self):
        self._setup_audio_device()
        self._attach_vlc_events()

    def _setup_audio_device(self):
        try:
            devices = self._media_player.audio_output_device_enum()
            if devices:
                dev = devices.contents
                device_id = dev.device.decode()
                self._media_player.audio_output_device_set(None, device_id)
        except Exception:
            log.exception("Audio device setup failed")

    def _attach_vlc_events(self):
        try:
            self._media_player.event_manager().event_attach(
                vlc.EventType.MediaPlayerMediaChanged,
                self._on_media_changed
            )
            self._vlc_list_player.event_manager().event_attach(
                vlc.EventType.MediaListPlayerNextItemSet,
                self._on_media_changed
            )
            self._vlc_list_player.event_manager().event_attach(
                vlc.EventType.MediaListPlayerStopped,
                self._on_playlist_ended
            )
        except Exception:
            log.exception("Failed attaching VLC events")

    def _usb_present(self):
        for device in self._context.list_devices(subsystem='block', DEVTYPE='partition'):
            if device.get('ID_BUS') == 'usb':
                return True
        return False

    async def _run_usb_listener(self):

        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.start()

        if self._playlist_owner == "listener" and self._usb_present():
            self._start_playback("/media", owner="listener")

        while self._running:

            device = await asyncio.to_thread(self._monitor.poll, 1)

            if not device:
                continue

            if device.action == "add":

                await asyncio.sleep(1)

                if self._playlist_owner == "listener":
                    self._start_playback("/media", owner="listener")

            elif device.action == "remove":

                if self._playlist_owner == "listener":
                    self.stop()

    async def _run_local_listener(self):

        path = self._listener_path

        if not path:
            user = os.getenv("USER")
            path = f"/home/{user}/Music"
            os.makedirs(path, exist_ok=True)

        while self._running:

            files = await asyncio.to_thread(self._get_supported_audio_files, path)

            if (
                self._playlist_owner == "listener"
                and len(files) != self._current_file_count
            ):
                self._start_playback(path, owner="listener")

            await asyncio.sleep(1)

    def _get_supported_audio_files(self, path):
        audio_files = []
        for root, _, files in os.walk(path):
            for f in files:
                if f.lower().endswith(self._audio_extensions):
                    audio_files.append(os.path.join(root, f))
        return audio_files

    def _file_uri_to_path(self, uri):
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme != "file":
            return urllib.parse.unquote(uri)
        path = urllib.parse.unquote(parsed.path)
        # file:///C:/... parses to "/C:/..."; strip the leading slash before the drive letter.
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path

    def _decode_media_path(self, media):
        if not media:
            return None
        mrl = media.get_mrl()
        if not mrl:
            return None
        return self._file_uri_to_path(mrl)

    def _current_playlist_paths(self):
        paths = []
        count = self._vlc_media_list.count()
        for i in range(count):
            media = self._vlc_media_list.item_at_index(i)
            path = self._decode_media_path(media)
            if path:
                paths.append(path)
        return paths

    def _set_playlist_paths(self, paths, preserve_current=True):
        current_media = self._media_player.get_media()
        current_path = self._decode_media_path(current_media)
        was_playing = self.is_playing()

        new_list = self._vlc_instance.media_list_new()
        for file_path in paths:
            if not file_path:
                continue
            media = self._vlc_instance.media_new_path(file_path)
            if media is None:
                log.warning("Skipping invalid media path '%s'", file_path)
                continue
            new_list.add_media(media)

        self._vlc_list_player.set_media_list(new_list)
        self._vlc_media_list = new_list
        self._current_file_count = len(paths)

        if preserve_current and current_path and current_path in paths:
            idx = paths.index(current_path)
            if was_playing:
                self._vlc_list_player.play_item_at_index(idx)

    def _expand_path_input(self, path):
        if not path:
            return []
        if os.path.isdir(path):
            return self._get_supported_audio_files(path)
        ext = os.path.splitext(path)[1].lower()
        if ext in self._audio_extensions:
            return [path]
        return []

    def _build_playlist(self, path):
        media_paths = self._get_supported_audio_files(path)

        if self._shuffle:
            random.shuffle(media_paths)

        new_list = self._vlc_instance.media_list_new()
        for file_path in media_paths:
            media = self._vlc_instance.media_new_path(file_path)
            new_list.add_media(media)

        self._vlc_list_player.set_media_list(new_list)
        self._vlc_media_list = new_list
        self._current_file_count = len(media_paths)

    def _start_playback(self, path, owner="listener"):
        with self._playlist_lock:
            self._playlist_owner = owner
            self._build_playlist(path)

            if self._current_file_count > 0:
                self._vlc_list_player.play()
                self.handler_active = True

    def _on_media_changed(self, event):
        media = self._media_player.get_media()
        if not media:
            return

        self._process_metadata(media)

        media_event_mgr = media.event_manager()
        if self._last_media_event_mgr:
            try:
                self._last_media_event_mgr.event_detach(vlc.EventType.MediaParsedChanged)
            except: pass

        media_event_mgr.event_attach(
            vlc.EventType.MediaParsedChanged, 
            lambda ev: self._process_metadata(media)
        )
    
        self.handler_active = True
        self._last_media_event_mgr = media_event_mgr
        media.parse_with_options(1 | 2, timeout=3000)

    def _process_metadata(self, media):
        try:
            title = media.get_meta(vlc.Meta.Title)
            if not title:
                decoded_path = self._decode_media_path(media)
                title = os.path.basename(decoded_path) if decoded_path else media.get_mrl()
            artist = media.get_meta(vlc.Meta.Artist)
            album = media.get_meta(vlc.Meta.Album)
        
            art_url = media.get_meta(vlc.Meta.ArtworkURL)
            album_art = None
        
            if art_url and art_url.startswith("file://"):
                path = self._file_uri_to_path(art_url)
                try:
                    album_art = Image.open(path).convert("RGBA")
                except Exception:
                    pass

            # Thread-safe handoff
            with self._meta_lock:
                self._pending_meta = {
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "album_art": album_art
                }
        except Exception:
            log.exception("Failed processing metadata")

    def _on_playlist_ended(self, event):
        self.handler_active = False
        self.now_playing.clear_track_info()

    def _update_ui(self):
        """
        Call this EVERY FRAME from the main thread (where OpenGL context is valid).
        """
        with self._meta_lock:
            if self._pending_meta is None:
                return
        
            data = self._pending_meta
            self._pending_meta = None

        self.now_playing.set_track_info(
            data["title"],
            artist=data["artist"],
            album=data["album"],
            album_art=data["album_art"]
        )

    #endregion

    #region Playback Controls

    def is_playing(self):
        try:
            return bool(self._media_player.is_playing())
        except Exception:
            return False

    def play(self):
        self._vlc_list_player.play()

    def play_index(self, index):
        try:
            count = self._vlc_media_list.count()
            if 0 <= index < count:
                self._vlc_list_player.play_item_at_index(index)
                return True
            return False
        except Exception:
            log.exception("play_index failed")
            return False

    def pause(self):
        self._media_player.pause()

    def stop_playback(self):
        try:
            self._vlc_list_player.stop()
        except Exception:
            pass

    def next(self):
        self._vlc_list_player.next()

    def previous(self):
        index = self._vlc_media_list.index_of_item(
            self._media_player.get_media()
        )
        self._vlc_list_player.play_item_at_index(max(0, index - 1))

    def get_playlist(self):
        playlist = []
        count = self._vlc_media_list.count()
        for i in range(count):
            media = self._vlc_media_list.item_at_index(i)
            path = self._decode_media_path(media) or ""
            name = os.path.splitext(os.path.basename(path))[0]
            playlist.append((i, name))
        return playlist

    def get_playlist_paths(self):
        return self._current_playlist_paths()

    def clear_playlist(self):
        with self._playlist_lock:
            self._playlist_owner = "ui"
            count = self._vlc_media_list.count()
            for i in reversed(range(count)):
                self._vlc_media_list.remove_index(i)
            self._current_file_count = 0
            self.stop()

    def remove_item_from_playlist(self, index):
        with self._playlist_lock:
            self._playlist_owner = "ui"
            self._vlc_media_list.remove_index(index)
            self._current_file_count = self._vlc_media_list.count()

    def remove_paths_from_queue(self, paths):
        if not paths:
            return 0

        path_set = {os.path.normpath(p) for p in paths}
        with self._playlist_lock:
            current = self._current_playlist_paths()
            updated = [p for p in current if os.path.normpath(p) not in path_set]
            removed = len(current) - len(updated)
            if removed:
                self._playlist_owner = "ui"
                self._set_playlist_paths(updated)
            return removed

    def append_path_to_playlist(self, path):
        self.insert_paths_into_playlist([path] if path else [], None)

    def append_paths_to_playlist(self, paths):
        self.insert_paths_into_playlist(paths, None)

    def insert_path_into_playlist(self, path, index=None):
        self.insert_paths_into_playlist([path] if path else [], index)

    def insert_paths_into_playlist(self, paths, index=None):
        """Batches all paths into a single media-list rebuild instead of one rebuild per file."""
        if not paths:
            return

        with self._playlist_lock:
            self._playlist_owner = "ui"

            new_items = []
            for path in paths:
                new_items.extend(self._expand_path_input(path))
            if not new_items:
                return

            current_paths = self._current_playlist_paths()

            if index is None:
                index = len(current_paths)
            index = max(0, min(int(index), len(current_paths)))

            updated = current_paths[:index] + new_items + current_paths[index:]
            self._set_playlist_paths(updated)

    def move_playlist_item(self, src_index, dst_index):
        with self._playlist_lock:
            paths = self._current_playlist_paths()
            if not paths:
                return False

            if src_index < 0 or src_index >= len(paths):
                return False

            dst_index = max(0, min(int(dst_index), len(paths) - 1))
            if src_index == dst_index:
                return True

            item = paths.pop(src_index)
            paths.insert(dst_index, item)
            self._playlist_owner = "ui"
            self._set_playlist_paths(paths)
            return True

    def get_media_playlist_names(self):
        return self.playlist_store.list_playlists()

    def get_media_playlist_items(self, playlist_name):
        return self.playlist_store.get_playlist_items(playlist_name)

    def create_media_playlist(self, playlist_name):
        return self.playlist_store.create_playlist(playlist_name)

    def delete_media_playlist(self, playlist_name):
        return self.playlist_store.delete_playlist(playlist_name)

    def add_paths_to_media_playlist(self, playlist_name, paths, insert_at=None):
        return self.playlist_store.add_items_to_playlist(playlist_name, paths, insert_at=insert_at)

    def remove_paths_from_media_playlist(self, playlist_name, paths):
        return self.playlist_store.remove_items_from_playlist(playlist_name, paths)

    def remove_indices_from_media_playlist(self, playlist_name, indices):
        return self.playlist_store.remove_indices_from_playlist(playlist_name, indices)

    def move_item_in_media_playlist(self, playlist_name, src_index, dst_index):
        return self.playlist_store.move_item_in_playlist(playlist_name, src_index, dst_index)

    #endregion

    #region Main Component Functions

    async def run(self):
        self._init_audio()

        if self._listener_enabled and sys.platform == 'linux':
            if self._listener_source == "usb":
                asyncio.create_task(self._run_usb_listener())

            elif self._listener_source == "local":
                asyncio.create_task(self._run_local_listener())

        while self._running:
            self._update_ui() 
            await asyncio.sleep(0.5)

    async def close(self):

        try:
            self.stop()
        except Exception:
            pass

        if self._last_media_event_mgr:
            try:
                self._last_media_event_mgr.event_detach(
                    vlc.EventType.MediaParsedChanged
                )
            except Exception:
                pass

        self._last_media_event_mgr = None
        self.playlist_store.close()

    #endregion