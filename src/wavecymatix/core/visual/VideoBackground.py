import av
import ctypes
import logging
import numpy as np
import os
import random
import threading
import time

from imgui_bundle import imgui
from OpenGL import GL

from wavecymatix.core.MediaLibraryStore import MediaLibraryStore

log = logging.getLogger()


class VideoBackground:
    def __init__(self, gui_manager, config):
        self.gui_manager = gui_manager

        self.video_directory = config.video_background.get('video_background.directory', '/home/pi/Videos')
        self.randomize = config.video_background.get('video_background.randomize', True)
        self.muted = config.video_background.get('video_background.muted', True)

        self.visible = False

        self.supported_extensions = (
            ".mp4",
            ".mkv",
            ".mov",
            ".avi",
            ".webm"
        )

        self.playlist_store = MediaLibraryStore(
            media_type="video_background",
            section_config=config.video_background,
            supported_extensions=self.supported_extensions,
            key_prefix="video_background",
            general_config=config.general,
        )

        self.active_playlist = "all"

        self.videos = []
        self.current_video_index = 0

        self.current_video_path = None

        self.video_container = None
        self.video_stream = None
        self.frame_iterator = None

        self.texture_id = None
        self.texture_w = 1
        self.texture_h = 1

        self.current_frame = None
        self.frame_lock = threading.Lock()

        self.decoder_thread = None
        self.decoder_lock = threading.Lock()
        self.running = False

        self.frame_ready = False
        self.texture_initialized = False

        self.last_frame_time = 0.0
        self.video_fps = 30.0

        self._force_first_upload = True

        self.locked = False
        self.loop_single_video = False

        self.stop_event = threading.Event()

        self.reload()

    #region Private Helpers

    def _discover_videos(self):
        videos = []

        if not os.path.isdir(self.video_directory):
            log.warning(f"Video directory does not exist: {self.video_directory}")
            return videos

        for file in sorted(os.listdir(self.video_directory)):
            ext = os.path.splitext(file)[1].lower()

            if ext not in self.supported_extensions:
                continue

            full_path = os.path.join(self.video_directory, file)

            log.info(f"Found video: {full_path}")

            videos.append(full_path)

        return videos

    def _apply_videos(self, videos, shuffle=None):
        self.videos = list(videos)
        self.current_video_index = 0
        self.current_video_path = None

        if not self.videos:
            log.warning(f"No videos found in {self.video_directory}")
            return

        if shuffle is None:
            shuffle = self.randomize

        if shuffle:
            random.shuffle(self.videos)

        self.current_video_path = self.videos[self.current_video_index]

    def _load_playlist(self, playlist_name, allow_shuffle=True):
        was_running = self.running
        if was_running:
            self.stop()

        self.active_playlist = playlist_name
        items = self.playlist_store.get_playlist_items(playlist_name)
        self._apply_videos(items, shuffle=(self.randomize if allow_shuffle else False))

        if was_running and self.visible and self.videos:
            self.start()

    def _resync_library(self):
        discovered = self._discover_videos()
        self.playlist_store.sync_library(discovered)
        selected = self.playlist_store.resolve_startup_playlist()
        self._load_playlist(selected)

    def _decoder_loop(self):
        log.info("Decoder loop entered")

        last_frame_time = 0.0

        local_container = None
        local_iterator = None

        try:
            while not self.stop_event.is_set():

                # open video if needed
                if local_container is None:

                    current_path = self.videos[self.current_video_index]
                    self.current_video_path = current_path

                    log.info(f"Opening video: {current_path}")

                    try:
                        local_container = av.open(current_path)

                        local_stream = local_container.streams.video[0]

                        if local_stream.average_rate:
                            self.video_fps = float(local_stream.average_rate)
                        else:
                            self.video_fps = 30.0

                        local_iterator = local_container.decode(video=0)

                    except Exception as e:
                        log.exception(f"Video open failed: {e}")

                        try:
                            if local_container:
                                local_container.close()
                        except Exception:
                            pass

                        local_container = None
                        local_iterator = None

                        time.sleep(1.0)
                        continue

                min_frame_interval = 1.0 / max(self.video_fps, 30.0)

                try:
                    for frame in local_iterator:

                        if self.stop_event.is_set():
                            break

                        now = time.time()
                        elapsed = now - last_frame_time

                        if elapsed < min_frame_interval:
                            time.sleep(min_frame_interval - elapsed)

                        last_frame_time = time.time()

                        try:
                            rgba = frame.to_ndarray(format="rgba")
                        except Exception as e:
                            log.exception(f"Frame conversion failed: {e}")
                            continue

                        with self.frame_lock:
                            self.current_frame = rgba
                            self.frame_ready = True

                    if self.stop_event.is_set():
                        break

                    # EOF reached
                    try:
                        local_container.close()
                    except Exception:
                        pass

                    local_container = None
                    local_iterator = None

                    if not self.locked:
                        self.current_video_index += 1

                        if self.current_video_index >= len(self.videos):
                            self.current_video_index = 0

                            if self.randomize:
                                random.shuffle(self.videos)

                except Exception as e:
                    log.exception(f"Decoder iteration error: {e}")

                    try:
                        if local_container:
                            local_container.close()
                    except Exception:
                        pass

                    local_container = None
                    local_iterator = None

                    time.sleep(0.25)

        finally:

            try:
                if local_container:
                    local_container.close()
            except Exception:
                pass

            log.info("Decoder loop exited")

    def _ensure_texture(self, width, height):
        if self.texture_id is not None:
            if width == self.texture_w and height == self.texture_h:
                return
        else:
            self.texture_id = GL.glGenTextures(1)

        self.texture_w = width
        self.texture_h = height

        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture_id)

        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)

        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA,
            width,
            height,
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            None
        )

        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _upload_frame(self):
        if not self.frame_ready and not self._force_first_upload:
            return

        with self.frame_lock:
            frame = self.current_frame
            self.frame_ready = False
            self._force_first_upload = False

        if frame is None:
            return

        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        height, width, channels = frame.shape

        self._ensure_texture(width, height)

        gl_format = GL.GL_RGBA if channels == 4 else GL.GL_RGB

        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture_id)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)

        ptr = ctypes.c_void_p(frame.ctypes.data)

        GL.glTexSubImage2D(
            GL.GL_TEXTURE_2D,
            0,
            0,
            0,
            width,
            height,
            gl_format,
            GL.GL_UNSIGNED_BYTE,
            ptr
        )

        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _compute_video_rect(self, vid_w, vid_h, area_w, area_h):
        if vid_w <= 0 or vid_h <= 0:
            return 0, 0, area_w, area_h

        scale = max(area_w / vid_w, area_h / vid_h)

        draw_w = vid_w * scale
        draw_h = vid_h * scale

        x = (area_w - draw_w) * 0.5
        y = (area_h - draw_h) * 0.5

        return x, y, draw_w, draw_h

    #endregion

    #region Public Helpers

    def start(self):
        if self.running:
            return

        log.info("Starting video background decoder")

        self.running = True
        self.stop_event.clear()

        self.decoder_thread = threading.Thread(
            target=self._decoder_loop,
            daemon=True,
            name="VideoDecoderThread"
        )

        self.decoder_thread.start()

    def stop(self):
        if not self.running:
            return

        log.info("Stopping video background decoder")

        self.running = False
        self.stop_event.set()

        if self.decoder_thread:
            self.decoder_thread.join(timeout=10.0)

            if self.decoder_thread.is_alive():
                log.error("Decoder thread failed to exit")
            else:
                log.info("Decoder thread joined cleanly")

            self.decoder_thread = None

        with self.frame_lock:
            self.current_frame = None
            self.frame_ready = False

        log.info("Video background decoder stopped")

    def toggle(self):
        self.visible = not self.visible

    def reload(self):
        self._resync_library()

    def set_visible(self, visible):
        visible = bool(visible)

        if self.visible == visible:
            return

        self.visible = visible

        if self.visible:
            self.start()
        else:
            self.stop()

    def next_visual(self):
        if not self.videos:
            return

        self.current_video_index += 1

        if self.current_video_index >= len(self.videos):
            self.current_video_index = 0

        self.current_video_path = self.videos[self.current_video_index]

        self.stop()
        self.start()

    def previous_visual(self):
        if not self.videos:
            return

        self.current_video_index -= 1

        if self.current_video_index < 0:
            self.current_video_index = len(self.videos) - 1

        self.current_video_path = self.videos[self.current_video_index]

        self.stop()
        self.start()

    def delete_visual(self, physical=False):
        current_video = self.get_current_visual_item()
        if not current_video:
            log.warning("No active video background to delete")
            return False

        was_running = self.running
        if was_running:
            self.stop()

        if physical:
            try:
                os.remove(current_video)
            except OSError:
                log.exception("Failed to physically delete video background %s", current_video)
                if was_running and self.visible:
                    self.start()
                return False

            self.playlist_store.sync_library(self._discover_videos())
        else:
            self.playlist_store.remove_items_from_playlist(
                self.active_playlist,
                [current_video],
            )

        self._load_playlist(self.active_playlist, allow_shuffle=False)
        if was_running and self.visible and self.videos:
            self.start()

        log.info("Deleted video background %s (physical=%s)", current_video, physical)
        return True

    def get_visual_locked(self):
        return self.locked

    def toggle_visual_lock(self):
        self.locked = not self.locked

    def get_presets_shuffle(self):
        return self.randomize

    def toggle_presets_shuffle(self):
        self.randomize = not self.randomize
        if self.active_playlist:
            self._load_playlist(self.active_playlist)

    def get_diagnostics_snapshot(self):
        count = len(self.videos)

        current_video = self.current_video_path
        if not current_video and count > 0:
            current_video = self.videos[self.current_video_index]

        return {
            "label": "Current Video",
            "value": current_video or "N/A",
            "index": (self.current_video_index + 1) if count > 0 else 0,
            "count": count,
            "active_playlist": self.active_playlist,
            "locked": self.locked,
            "fps": self.video_fps,
            "decoder_running": self.running,
        }

    def get_visual_playlist_names(self):
        return self.playlist_store.list_playlists()

    def get_active_visual_playlist_name(self):
        return self.active_playlist

    def get_visual_playlist_items(self, playlist_name):
        return self.playlist_store.get_playlist_items(playlist_name)

    def get_runtime_playlist_items(self):
        return list(self.videos)

    def set_active_visual_playlist(self, playlist_name):
        self._load_playlist(playlist_name)

    def set_visual_runtime_index(self, index):
        if not self.videos:
            return

        self.current_video_index = index % len(self.videos)
        self.current_video_path = self.videos[self.current_video_index]

        self.stop()
        self.start()

    def shift_runtime_from_index(self, index):
        if not self.videos:
            return False

        if index < 0 or index >= len(self.videos):
            return False

        was_running = self.running
        if was_running:
            self.stop()

        self._apply_videos(self.videos[index:], shuffle=False)

        if was_running and self.visible and self.videos:
            self.start()

        return True

    def move_runtime_item(self, src_index, dst_index):
        if not self.videos:
            return False
        if src_index < 0 or src_index >= len(self.videos):
            return False

        dst_index = max(0, min(int(dst_index), len(self.videos) - 1))
        if src_index == dst_index:
            return True

        was_running = self.running
        if was_running:
            self.stop()

        updated = list(self.videos)
        item = updated.pop(src_index)
        updated.insert(dst_index, item)

        self._apply_videos(updated, shuffle=False)
        if self.active_playlist:
            self.playlist_store.replace_playlist_items(self.active_playlist, updated)

        if was_running and self.visible and self.videos:
            self.start()

        return True

    def clear_runtime_playlist(self):
        was_running = self.running
        if was_running:
            self.stop()

        self._apply_videos([], shuffle=False)

        return True

    def create_visual_playlist(self, playlist_name):
        return self.playlist_store.create_playlist(playlist_name)

    def delete_visual_playlist(self, playlist_name):
        if self.playlist_store.delete_playlist(playlist_name):
            if self.active_playlist == playlist_name:
                fallback = self.playlist_store.resolve_startup_playlist()
                self._load_playlist(fallback)
            return True
        return False

    def add_items_to_visual_playlist(self, playlist_name, items, insert_at=None):
        added = self.playlist_store.add_items_to_playlist(playlist_name, items, insert_at=insert_at)
        if playlist_name == self.active_playlist and added:
            self._load_playlist(self.active_playlist, allow_shuffle=False)
        return added

    def remove_items_from_visual_playlist(self, playlist_name, items):
        removed = self.playlist_store.remove_items_from_playlist(playlist_name, items)
        if playlist_name == self.active_playlist and removed:
            self._load_playlist(self.active_playlist, allow_shuffle=False)
        return removed

    def move_item_in_visual_playlist(self, playlist_name, src_index, dst_index):
        moved = self.playlist_store.move_item_in_playlist(playlist_name, src_index, dst_index)
        if moved and playlist_name == self.active_playlist:
            self._load_playlist(self.active_playlist, allow_shuffle=False)
        return moved

    def add_items_to_favorites(self, items):
        return self.playlist_store.add_items_to_favorites(items)

    def remove_items_from_favorites(self, items):
        return self.playlist_store.remove_items_from_favorites(items)

    def is_item_favorite(self, item):
        return self.playlist_store.is_favorite(item)

    def set_video_item_window(self, path, start_sec=None, stop_sec=None):
        return self.playlist_store.set_video_item_window(path, start_sec=start_sec, stop_sec=stop_sec)

    def get_video_item_window(self, path):
        return self.playlist_store.get_video_item_window(path)

    def get_current_visual_item(self):
        if not self.videos:
            return None
        if self.current_video_index < 0 or self.current_video_index >= len(self.videos):
            return None
        return self.videos[self.current_video_index]

    #endregion

    #region Main Render Loop

    def render(self):
        if not self.visible:
            with self.frame_lock:
                self.current_frame = None
                self.frame_ready = False
            return

        if self.texture_id is None:
            dummy = np.zeros((2, 2, 4), dtype=np.uint8)

            self._ensure_texture(2, 2)

            GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture_id)

            GL.glTexSubImage2D(
                GL.GL_TEXTURE_2D,
                0,
                0,
                0,
                2,
                2,
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                dummy.ctypes.data_as(ctypes.c_void_p)
            )

            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        self._upload_frame()
        self._force_first_upload = False

        if self.texture_id is None:
            return

        io = imgui.get_io()

        screen_w = io.display_size.x
        screen_h = io.display_size.y

        draw_list = imgui.get_background_draw_list()

        draw_list.add_image(
            imgui.ImTextureRef(self.texture_id),
            imgui.ImVec2(0.0, screen_h),
            imgui.ImVec2(screen_w, 0.0),
            uv_min=imgui.ImVec2(0, 1),
            uv_max=imgui.ImVec2(1, 0),
            col=imgui.get_color_u32(imgui.ImVec4(1, 1, 1, 1))
        )

    #endregion