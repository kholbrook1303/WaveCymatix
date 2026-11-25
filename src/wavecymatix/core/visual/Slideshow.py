import logging
import os
import random
import time

from imgui_bundle import imgui
from OpenGL import GL

from wavecymatix.core.MediaLibraryStore import MediaLibraryStore

log = logging.getLogger()


class Slideshow:
    def __init__(self, gui_manager, config):
        self.gui_manager = gui_manager

        self.image_directory = config.slideshow.get('slideshow.directory', '/home/pi/Pictures')
        self.slide_duration = float(config.slideshow.get('slideshow.slide_duration', 8.0))
        self.fade_duration = float(config.slideshow.get('slideshow.fade_duration', 1.5))
        self.randomize = config.slideshow.get('slideshow.randomize', True)

        self.visible = False

        self.images = []
        self.current_index = 0
        self.next_index = 1

        self.last_switch_time = time.time()
        self.transitioning = False

        self.current_texture = None
        self.next_texture = None

        self.current_size = (1, 1)
        self.next_size = (1, 1)

        self.locked = False

        self.supported_extensions = (
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".webp"
        )

        self.playlist_store = MediaLibraryStore(
            media_type="slideshow",
            section_config=config.slideshow,
            supported_extensions=self.supported_extensions,
            key_prefix="slideshow",
            general_config=config.general,
        )

        self.active_playlist = "all"

        self.reload()

    #region Private Helpers

    def _discover_images(self):
        images = []

        if not os.path.isdir(self.image_directory):
            log.warning(f"Slideshow directory does not exist: {self.image_directory}")
            return images

        for file in sorted(os.listdir(self.image_directory)):
            ext = os.path.splitext(file)[1].lower()

            if ext not in self.supported_extensions:
                continue

            full_path = os.path.join(self.image_directory, file)
            log.info(f"Found slideshow image: {full_path}")
            images.append(full_path)

        return images

    def _apply_images(self, images, shuffle=None):
        self.images = list(images)
        self.current_index = 0
        self.next_index = 1
        self.current_texture = None
        self.next_texture = None
        self.current_size = (1, 1)
        self.next_size = (1, 1)

        if not self.images:
            log.warning(f"No slideshow images found in {self.image_directory}")
            return

        if shuffle is None:
            shuffle = self.randomize

        if shuffle:
            random.shuffle(self.images)

        self.current_index = 0
        self.next_index = 1 % len(self.images)

        self.current_texture, *self.current_size = \
            self.gui_manager.load_texture(self.images[self.current_index])

        if len(self.images) > 1:
            self.next_texture, *self.next_size = \
                self.gui_manager.load_texture(self.images[self.next_index])

    def _load_playlist(self, playlist_name, allow_shuffle=True):
        items = self.playlist_store.get_playlist_items(playlist_name)
        self.active_playlist = playlist_name
        self._apply_images(items, shuffle=(self.randomize if allow_shuffle else False))

    def _resync_library(self):
        discovered = self._discover_images()
        self.playlist_store.sync_library(discovered)
        selected = self.playlist_store.resolve_startup_playlist()
        self._load_playlist(selected)

    def _advance_slide(self):
        """Move slideshow forward."""
        if len(self.images) <= 1:
            return

        self.current_index = self.next_index

        self.current_texture = self.next_texture
        self.current_size = self.next_size

        self.next_index = (self.current_index + 1) % len(self.images)

        self.next_texture, *self.next_size = \
            self.gui_manager.load_texture(self.images[self.next_index])

        self.last_switch_time = time.time()
        self.transitioning = False

    def _set_current_index(self, index):
        if not self.images:
            return

        self.current_index = index % len(self.images)

        self.current_texture, *self.current_size = \
            self.gui_manager.load_texture(
                self.images[self.current_index]
            )

        self.next_index = (self.current_index + 1) % len(self.images)

        self.next_texture, *self.next_size = \
            self.gui_manager.load_texture(
                self.images[self.next_index]
            )

        self.last_switch_time = time.time()
        self.transitioning = False

    def _compute_image_rect(self, img_w, img_h, area_w, area_h):
        """
        Scale image to fill screen while preserving aspect ratio.
        The smallest dimension fills first (cover behavior).
        """

        if img_w <= 0 or img_h <= 0:
            return 0, 0, area_w, area_h

        scale = max(area_w / img_w, area_h / img_h)

        draw_w = img_w * scale
        draw_h = img_h * scale

        x = (area_w - draw_w) * 0.5
        y = (area_h - draw_h) * 0.5

        return x, y, draw_w, draw_h

    def _draw_texture(
        self,
        draw_list,
        texture,
        tex_w,
        tex_h,
        alpha,
        area_x,
        area_y,
        area_w,
        area_h
    ):
        if texture is None:
            return

        x, y, w, h = self._compute_image_rect(
            tex_w,
            tex_h,
            area_w,
            area_h
        )

        tint = imgui.get_color_u32(imgui.ImVec4(1.0, 1.0, 1.0, alpha))

        draw_list.add_image(
            imgui.ImTextureRef(texture),
            imgui.ImVec2(area_x + x, area_y + y),
            imgui.ImVec2(area_x + x + w, area_y + y + h),
            uv_min=imgui.ImVec2(0, 0),
            uv_max=imgui.ImVec2(1, 1),
            col=tint
        )

    #endregion

    #region Public Helpers

    def toggle(self):
        self.visible = not self.visible

    def set_visible(self, visible):
        self.visible = bool(visible)

    def reload(self):
        self._resync_library()

    def next_visual(self):
        if not self.images:
            return

        self._set_current_index(self.current_index + 1)

    def previous_visual(self):
        if not self.images:
            return

        self._set_current_index(self.current_index - 1)

    def delete_visual(self, physical=False):
        current_image = self.get_current_visual_item()
        if not current_image:
            log.warning("No active slideshow image to delete")
            return False

        if physical:
            try:
                os.remove(current_image)
            except OSError:
                log.exception("Failed to physically delete slideshow image %s", current_image)
                return False

            self.playlist_store.sync_library(self._discover_images())
        else:
            self.playlist_store.remove_items_from_playlist(
                self.active_playlist,
                [current_image],
            )

        self._load_playlist(self.active_playlist, allow_shuffle=False)
        log.info("Deleted slideshow image %s (physical=%s)", current_image, physical)
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
        current_image = None
        count = len(self.images)

        if count > 0 and 0 <= self.current_index < count:
            current_image = self.images[self.current_index]

        return {
            "label": "Current Image",
            "value": current_image or "N/A",
            "index": (self.current_index + 1) if count > 0 else 0,
            "count": count,
            "active_playlist": self.active_playlist,
            "locked": self.locked,
            "transitioning": self.transitioning,
            "slide_duration": self.slide_duration,
            "fade_duration": self.fade_duration,
        }

    def get_visual_playlist_names(self):
        return self.playlist_store.list_playlists()

    def get_active_visual_playlist_name(self):
        return self.active_playlist

    def get_visual_playlist_items(self, playlist_name):
        return self.playlist_store.get_playlist_items(playlist_name)

    def get_runtime_playlist_items(self):
        return list(self.images)

    def set_active_visual_playlist(self, playlist_name):
        self._load_playlist(playlist_name)

    def set_visual_runtime_index(self, index):
        self._set_current_index(index)

    def shift_runtime_from_index(self, index):
        if not self.images:
            return False

        if index < 0 or index >= len(self.images):
            return False

        self._apply_images(self.images[index:], shuffle=False)
        return True

    def move_runtime_item(self, src_index, dst_index):
        if not self.images:
            return False
        if src_index < 0 or src_index >= len(self.images):
            return False

        dst_index = max(0, min(int(dst_index), len(self.images) - 1))
        if src_index == dst_index:
            return True

        updated = list(self.images)
        item = updated.pop(src_index)
        updated.insert(dst_index, item)

        self._apply_images(updated, shuffle=False)
        if self.active_playlist:
            self.playlist_store.replace_playlist_items(self.active_playlist, updated)
        return True

    def clear_runtime_playlist(self):
        self._apply_images([], shuffle=False)
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

    def get_current_visual_item(self):
        if not self.images:
            return None
        if self.current_index < 0 or self.current_index >= len(self.images):
            return None
        return self.images[self.current_index]

    #endregion

    #region Main Render Loop

    def render(self):
        if not self.visible:
            return

        if not self.images:
            return

        io = imgui.get_io()

        screen_w = float(
            io.display_size.x
            if hasattr(io.display_size, "x")
            else io.display_size[0]
        )

        screen_h = float(
            io.display_size.y
            if hasattr(io.display_size, "y")
            else io.display_size[1]
        )

        safe_x, safe_y, safe_w, safe_h = \
            self.gui_manager.get_safe_region_for_popups()

        now = time.time()
        elapsed = now - self.last_switch_time

        if (
            not self.locked and
            not self.transitioning and
            elapsed >= self.slide_duration
        ):
            self.transitioning = True

        fade_progress = 0.0

        if self.transitioning:
            fade_progress = min(
                1.0,
                (elapsed - self.slide_duration) / self.fade_duration
            )

            if fade_progress >= 1.0:
                self._advance_slide()
                fade_progress = 0.0

        flags = (
            imgui.WindowFlags_.no_title_bar |
            imgui.WindowFlags_.no_move |
            imgui.WindowFlags_.no_resize |
            imgui.WindowFlags_.no_scrollbar |
            imgui.WindowFlags_.no_saved_settings |
            imgui.WindowFlags_.no_inputs |
            imgui.WindowFlags_.no_bring_to_front_on_focus |
            imgui.WindowFlags_.no_background
        )

        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(screen_w, screen_h))

        imgui.begin("##slideshow_background", flags=flags)

        draw_list = imgui.get_background_draw_list()

        # Current image
        self._draw_texture(
            draw_list,
            self.current_texture,
            self.current_size[0],
            self.current_size[1],
            1.0 - fade_progress,
            safe_x,
            safe_y,
            safe_w,
            safe_h
        )

        # Next image fades in
        if self.transitioning:
            self._draw_texture(
                draw_list,
                self.next_texture,
                self.next_size[0],
                self.next_size[1],
                fade_progress,
                safe_x,
                safe_y,
                safe_w,
                safe_h
            )

        imgui.end()

    #endregion