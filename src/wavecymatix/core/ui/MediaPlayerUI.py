import logging
import os
import json
import time

from imgui_bundle import imgui
from OpenGL import GL

from wavecymatix.lib.config import ASSET_ROOT
from wavecymatix.core.plugins.VLC import VLC

log = logging.getLogger()

class MediaPlayerUI:
    CONTROLS_BOTTOM_MARGIN_RATIO = 0.03

    def __init__(self, gui_manager, ui_ctrl):
        self.gui_manager = gui_manager
        self.ui_ctrl = ui_ctrl

        # Visibility flags
        self.visible = False
        self.keep_visible = False
        self.sprite_popup = False
        self.playlist_popup = False
        self.visual_playlist_popup = False
        self.visual_playlist_create_popup = False
        self.audio_playlist_create_popup = False
        self.audio_directory_create_popup = False

        self.sprite_popup_just_opened = False
        self.playlist_popup_just_opened = False
        self.visual_playlist_popup_just_opened = False

        # Internal state for playlist browser
        self.fs_roots = []
        self.expanded_dirs = set()
        self.current_dir = None
        self.dir_paths = []
        self.dir_entries = []
        self.content_selected = set()  # indices
        self.audio_playlist_name = ""
        self.audio_playlist_selection = set()
        self.audio_source_kind = "local"
        self.audio_source_value = "local"
        self.audio_local_expanded = True
        self.audio_playlists_expanded = False
        self.plugins = None
        self.queue_selected = None
        self.selected_visual_playlist = None
        self.visual_playlist_selection = set()
        self.visual_runtime_selection = set()
        self.pending_visual_playlist_name = ""
        self.pending_audio_playlist_name = ""
        self.pending_audio_directory_name = ""
        self._drag_payloads = {}

        # Cache favorite state for current visual to avoid per-frame DB checks.
        self._favorite_cache_item = None
        self._favorite_cache_is_favorite = False

        # Sprite keys list (ordered)
        self.sprite_keys = []

        # Fonts
        self.button_font = None
        self.tooltip_font = None

        # Load button textures
        self.play_tex, play_w, play_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "play-circle.png"))
        self.pause_tex, pause_w, pause_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "pause-circle.png"))
        self.next_tex, next_w, next_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "skip-next-circle-outline.png"))
        self.prev_tex, prev_w, prev_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "skip-previous-circle-outline.png"))
        self.playlist_tex, playlist_w, playlist_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "playlist-audio.png"))
        
        self.prev_preset_tex, prev_preset_w, prev_preset_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "page-previous-outline.png"))
        self.lock_preset_tex, lock_preset_w, lock_preset_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "lock-circle-outline.png"))
        self.unlock_preset_tex, unlock_preset_w, unlock_preset_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "unlock-circle-outline.png"))
        self.next_visual_tex, next_visual_w, next_visual_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "page-next-outline.png"))
        self.sprites_tex, sprites_w, sprites_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "image-plus.png"))
        self.visual_playlist_tex, visual_playlist_w, visual_playlist_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "playlist-add-icon-md.png"))
        self.favorite_on_tex, favorite_on_w, favorite_on_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "favorite.png"))
        self.favorite_off_tex, favorite_off_w, favorite_off_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "un-favorite.png"))
        self.delete_preset_tex, delete_w, delete_h = self.gui_manager.load_texture(os.path.join(ASSET_ROOT, "delete.png"))

    #region Private VLC Helpers

    def _get_vlc_handler(self):
        for handler in self.plugins:
            if handler.__class__.__name__.lower() == "vlc":
                if getattr(handler, "_running", False):
                    if getattr(handler, "handler_playlist", False):
                        return handler
        return None

    def _is_active(self):
        for handler in self.plugins:
            if getattr(handler, "handler_active", False):
                return True
        return False

    def _is_playing(self):
        for handler in self.plugins:
            handler_active = getattr(handler, "handler_active", False)
            if not handler_active:
                continue
            func = getattr(handler, "is_playing", None)
            if callable(func):
                return func()
        return False

    def _discover_local_roots(self):
        """Lists every system drive/mount so a user can traverse any disk, not just the boot drive."""
        if os.name == "nt":
            return self._discover_windows_drives()
        return self._discover_unix_mounts()

    def _discover_windows_drives(self):
        roots = []
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        except Exception:
            log.exception("Failed enumerating logical drives")
            bitmask = 0
        for i in range(26):
            if bitmask & (1 << i):
                drive = f"{chr(ord('A') + i)}:\\"
                if os.path.isdir(drive):
                    roots.append(drive)
        if not roots:
            drive, _ = os.path.splitdrive(os.getcwd())
            roots.append((drive + "\\") if drive else "C:\\")
        return roots

    def _discover_unix_mounts(self):
        roots = ["/"]
        for base in ("/media", "/mnt"):
            if not os.path.isdir(base):
                continue
            try:
                for name in sorted(os.listdir(base)):
                    path = os.path.join(base, name)
                    if not os.path.isdir(path):
                        continue
                    if os.path.ismount(path):
                        roots.append(path)
                        continue
                    # Some distros nest automounts one level deeper: /media/<user>/<label>
                    try:
                        for sub_name in sorted(os.listdir(path)):
                            sub_path = os.path.join(path, sub_name)
                            if os.path.isdir(sub_path) and os.path.ismount(sub_path):
                                roots.append(sub_path)
                    except Exception:
                        pass
            except Exception:
                log.exception("Failed discovering mounts under '%s'", base)
        return roots

    def _get_audio_extensions(self):
        """Always mirror the extensions VLC actually scans/plays so Contents never disagrees with playback."""
        vlc = self._get_vlc_handler()
        if vlc and hasattr(vlc, "_audio_extensions"):
            return vlc._audio_extensions
        return VLC.AUDIO_EXTENSIONS

    def _list_immediate_audio_files(self, path):
        """Non-recursive listing so drag/drop and double-click adds match exactly what Contents displays."""
        extensions = self._get_audio_extensions()
        files = []
        try:
            for name in sorted(os.listdir(path)):
                full_path = os.path.join(path, name)
                if os.path.isfile(full_path) and name.lower().endswith(extensions):
                    files.append(full_path)
        except Exception:
            log.exception("Failed listing directory '%s'", path)
        return files

    def _append_path_to_playlist(self, path):
        vlc = self._get_vlc_handler()
        if not vlc or not path:
            return
        try:
            self.gui_manager.run_in_thread(vlc.append_path_to_playlist, path)
        except Exception:
            log.exception("Failed to append path to playlist")

    def _append_paths_to_playlist(self, paths):
        vlc = self._get_vlc_handler()
        if not vlc or not paths:
            return
        try:
            if hasattr(vlc, "append_paths_to_playlist"):
                vlc.append_paths_to_playlist(paths)
            else:
                for path in paths:
                    vlc.append_path_to_playlist(path)
        except Exception:
            log.exception("Failed to append paths to playlist")

    def _queue_remove_selected(self):
        vlc = self._get_vlc_handler()
        if not vlc or self.queue_selected is None:
            return
        try:
            vlc.remove_item_from_playlist(self.queue_selected)
            self.queue_selected = None
        except Exception:
            log.exception("Failed to remove item from playlist")

    def _clear_queue(self):
        vlc = self._get_vlc_handler()
        if not vlc:
            return
        try:
            vlc.clear_playlist()
            self.queue_selected = None
        except Exception:
            log.exception("Failed to clear playlist")

    def _play_directory(self, path):
        """Only adds/plays files visible in the Contents column, avoiding surprise nested-folder loads."""
        vlc = self._get_vlc_handler()
        if not vlc or not path:
            return
        files = self._list_immediate_audio_files(path)
        if not files:
            return
        try:
            if hasattr(vlc, "append_paths_to_playlist"):
                vlc.append_paths_to_playlist(files)
            else:
                for file_path in files:
                    vlc.append_path_to_playlist(file_path)
            vlc.play()
        except Exception:
            log.exception("Failed to play directory '%s'", path)

    def _build_dir_tree(self):
        lines = []
        paths = []

        valid_roots = [root for root in self.fs_roots if os.path.isdir(root)]
        if not valid_roots:
            self.dir_entries = []
            return lines, paths

        def walk(path, depth):
            basename = path if depth == 0 else os.path.basename(path)
            expanded = path in self.expanded_dirs
            prefix = "[-] " if expanded else "[+] "
            lines.append("  " * depth + prefix + basename)
            paths.append(path)

            if expanded:
                try:
                    for name in sorted(os.listdir(path)):
                        full = os.path.join(path, name)
                        if os.path.isdir(full):
                            walk(full, depth + 1)
                except Exception as e:
                    log.warning(f"Failed to list directory '{path}': {e}")

        for root in valid_roots:
            walk(root, 0)

        # Ensure current_dir valid
        if self.current_dir is None or not os.path.isdir(self.current_dir):
            self.current_dir = valid_roots[0]

        # Build contents list of audio files
        self.dir_entries = []
        extensions = self._get_audio_extensions()
        try:
            for name in sorted(os.listdir(self.current_dir)):
                full_path = os.path.join(self.current_dir, name)
                if os.path.isfile(full_path) and name.lower().endswith(extensions):
                    self.dir_entries.append(full_path)
        except Exception as e:
            log.warning(f"Failed to list contents of '{self.current_dir}': {e}")

        return lines, paths

    def _get_audio_playlist_names(self, vlc):
        if not vlc or not hasattr(vlc, "get_media_playlist_names"):
            return []
        try:
            rows = vlc.get_media_playlist_names()
            return [row.get("name") for row in rows if row.get("name")]
        except Exception:
            log.exception("Failed to list audio playlists")
            return []

    def _set_audio_source_playlist(self, name):
        self.audio_source_kind = "playlist"
        self.audio_source_value = name or ""
        self.audio_playlist_name = name or ""
        self.content_selected.clear()
        self.audio_playlist_selection.clear()

    def _set_audio_source_local(self, path):
        self.audio_source_kind = "local"
        self.audio_source_value = path
        self.current_dir = path
        self.content_selected.clear()
        self.audio_playlist_selection.clear()

    def _get_selected_audio_playlist_name(self):
        if self.audio_source_kind != "playlist":
            return None
        return self.audio_source_value

    def _get_selected_local_path(self):
        if self.audio_source_kind != "local":
            return None
        return self.audio_source_value

    def _collect_drop_paths(self, data, vlc):
        dtype = data.get("type")
        if dtype in ("file", "audio_playlist_item", "queue"):
            path = data.get("path")
            return [path] if path else []

        if dtype == "dir":
            path = data.get("path")
            if path:
                # Non-recursive so drops only add what's visible in the Contents column.
                return self._list_immediate_audio_files(path)
        return []

    def _begin_drag_source(self):
        return imgui.begin_drag_drop_source(imgui.DragDropFlags_.source_allow_null_id)

    def _set_drag_payload(self, payload_type, payload):
        payload_id = id(payload)
        self._drag_payloads.clear()
        self._drag_payloads[payload_id] = payload
        return imgui.set_drag_drop_payload_py_id(payload_type, payload_id)

    def _accept_drag_payload(self, payload_type):
        payload = imgui.accept_drag_drop_payload_py_id(payload_type)
        if payload is None:
            return None
        return self._drag_payloads.get(payload.data_id)

    def _decode_dnd_payload(self, payload):
        if not payload:
            return None

        raw = getattr(payload, "data", payload)
        try:
            if isinstance(raw, str):
                text = raw
            elif isinstance(raw, (bytes, bytearray)):
                text = bytes(raw).decode("utf-8")
            elif hasattr(raw, "tobytes"):
                text = raw.tobytes().decode("utf-8")
            else:
                text = bytes(raw).decode("utf-8")
            return json.loads(text)
        except Exception:
            log.exception("[DND] Failed to decode payload")
            return None

    #endregion

    #region Private Button Helpers

    def toggle_lock(self):
        """Fallback for when ui_state is not available"""
        self.ui_ctrl.toggle_visual_lock()

    def toggle_play(self):
        """Fallback for when ui_state is not available"""
        playing = not self._is_playing()
        func = "play" if playing else "pause"
        for handler in self.plugins:
            handler_active = getattr(handler, "handler_active", False)
            if not handler_active:
                continue
            func_to_call = getattr(handler, func, None)
            if callable(func_to_call):
                func_to_call()
                return

    def toggle_sprite_popup(self):
        self.sprite_popup = not self.sprite_popup
        if self.sprite_popup:
            self.playlist_popup = False
            self.sprite_popup_just_opened = True

    def toggle_playlist_popup(self):
        self.playlist_popup = not self.playlist_popup
        if self.playlist_popup:
            self.sprite_popup = False
            self.playlist_popup_just_opened = True
            self.fs_roots = self._discover_local_roots()
            self.audio_local_expanded = True
            self.audio_playlists_expanded = False
            if self.fs_roots:
                self._set_audio_source_local(self.fs_roots[0])

    def close_playlist_popup(self):
        self.playlist_popup = False

    def toggle_visual_playlist_popup(self):
        self.visual_playlist_popup = not self.visual_playlist_popup
        if self.visual_playlist_popup:
            self.playlist_popup = False
            self.sprite_popup = False
            self.visual_playlist_popup_just_opened = True
            self.selected_visual_playlist = self.ui_ctrl.get_active_visual_playlist_name()
            self.visual_playlist_selection.clear()
            self.visual_runtime_selection.clear()

    def media_previous(self):
        """Fallback for when ui_state is not available"""
        for handler in self.plugins:
            handler_active = getattr(handler, "handler_active", False)
            if not handler_active:
                continue
            func = getattr(handler, "previous", None)
            if callable(func):
                func()
                return

    def media_next(self):
        """Fallback for when ui_state is not available"""
        for handler in self.plugins:
            handler_active = getattr(handler, "handler_active", False)
            if not handler_active:
                continue
            func = getattr(handler, "next", None)
            if callable(func):
                func()
                return

    def close_popup(self):
        self.sprite_popup = False
        self.playlist_popup = False
        self.visual_playlist_popup = False
        self.visual_playlist_create_popup = False
        self.audio_playlist_create_popup = False
        self.audio_directory_create_popup = False

    def toggle_current_visual_favorite(self):
        current_item = self.ui_ctrl.get_current_visual_item()
        if not current_item:
            return

        self._refresh_current_favorite_cache(force=(self._favorite_cache_item != current_item))

        if self._favorite_cache_is_favorite:
            self.ui_ctrl.remove_items_from_visual_favorites([current_item])
            self._favorite_cache_is_favorite = False
        else:
            self.ui_ctrl.add_items_to_visual_favorites([current_item])
            self._favorite_cache_is_favorite = True

        self._favorite_cache_item = current_item

    def delete_current_visual_item(self):
        current_item = self.ui_ctrl.get_current_visual_item()
        if not current_item:
            return

        active_playlist = self.ui_ctrl.get_active_visual_playlist_name()
        if active_playlist:
            self.ui_ctrl.remove_items_from_visual_playlist(active_playlist, [current_item])

    def _get_current_favorite_button_tex(self):
        self._refresh_current_favorite_cache()
        if self._favorite_cache_item and self._favorite_cache_is_favorite:
            return self.favorite_on_tex
        return self.favorite_off_tex

    def _invalidate_favorite_cache(self):
        self._favorite_cache_item = None
        self._favorite_cache_is_favorite = False

    def _refresh_current_favorite_cache(self, force=False):
        current_item = self.ui_ctrl.get_current_visual_item()

        if not current_item:
            self._favorite_cache_item = None
            self._favorite_cache_is_favorite = False
            return

        if force or self._favorite_cache_item != current_item:
            self._favorite_cache_item = current_item
            self._favorite_cache_is_favorite = self.ui_ctrl.is_visual_item_favorite(current_item)

    def toggle_visual_playlist_create_popup(self):
        self.visual_playlist_create_popup = not self.visual_playlist_create_popup
        if self.visual_playlist_create_popup:
            self.pending_visual_playlist_name = ""

    def toggle_audio_playlist_create_popup(self):
        self.audio_playlist_create_popup = not self.audio_playlist_create_popup
        if self.audio_playlist_create_popup:
            self.pending_audio_playlist_name = ""

    def toggle_audio_directory_create_popup(self):
        self.audio_directory_create_popup = not self.audio_directory_create_popup
        if self.audio_directory_create_popup:
            self.pending_audio_directory_name = ""

    def _load_visual_playlist(self, playlist_name):
        if not playlist_name:
            return
        self.selected_visual_playlist = playlist_name
        self.ui_ctrl.set_active_visual_playlist(playlist_name)
        self.visual_runtime_selection.clear()
        self._invalidate_favorite_cache()

    def toggle_sprite(self, name):
        try:
            self.ui_ctrl.handle_sprite(name)
        except Exception:
            log.exception("Failed to toggle sprite")

    #endregion

    #region Main Render Loop

    def render(self):
        if not self.visible and not self.keep_visible:
            return
        self.button_font = self.gui_manager.get_font()
        self.tooltip_font = self.gui_manager.get_font()

        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        btn_h, btn_w, padding, spacing = self.gui_manager.get_button_dimensions(scale_factor=1.0)
        safe_x, safe_y, safe_w, safe_h = self.gui_manager.get_safe_region_for_popups()

        top_buttons = []
        if self._is_active():
            top_buttons.extend([
                self.prev_tex,
                self.pause_tex if self._is_playing() else self.play_tex,
                self.next_tex
            ])
        if self._show_playlist_control():
            top_buttons.append(self.playlist_tex)

        bottom_buttons = []
        if self.ui_ctrl.get_visual_mode() != "none":
            bottom_buttons.extend([
                self.prev_preset_tex,
                self.lock_preset_tex if self.ui_ctrl.get_visual_locked() else self.unlock_preset_tex,
                self.next_visual_tex,
                self.visual_playlist_tex,
                self.delete_preset_tex,
            ])
        if self.ui_ctrl.projectm.visible and len(self.ui_ctrl.projectm.sprites) > 0:
            bottom_buttons.extend([self.sprites_tex])

        # Bottom row always renders favorites first, then all bottom_buttons.
        bottom_button_count = len(bottom_buttons) + 1

        top_total_width = btn_w * len(top_buttons) + spacing * (len(top_buttons)-1) + 2 * padding
        bottom_total_width = btn_w * bottom_button_count + spacing * max(bottom_button_count - 1, 0) + 2 * padding

        top_total_width = min(top_total_width, safe_w)
        bottom_total_width = min(bottom_total_width, safe_w)

        top_row_height = btn_h + 2*padding
        bottom_row_height = btn_h + 2*padding

        row_gap = max(8, spacing)
        controls_height = (
            (top_row_height + row_gap if top_buttons else 0) +
            (bottom_row_height if bottom_buttons else 0)
        )
        bottom_margin = (
            self.gui_manager.screen_h * self.CONTROLS_BOTTOM_MARGIN_RATIO
        )
        controls_top = self.gui_manager.screen_h - bottom_margin - controls_height
        top_win_y = int(controls_top)
        bottom_win_y = int(
            controls_top + (top_row_height + row_gap if top_buttons else 0)
        )

        bottom_win_x = int(safe_x + (safe_w - bottom_total_width)//2)
        top_win_x = int(safe_x + (safe_w - top_total_width)//2)

        if bottom_buttons:
            imgui.set_next_window_pos(imgui.ImVec2(bottom_win_x, bottom_win_y))
            imgui.set_next_window_size(imgui.ImVec2(bottom_total_width, bottom_row_height))
            imgui.push_style_var(imgui.StyleVar_.window_rounding, 6)
            imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding, padding))
            imgui.push_style_color(
                imgui.Col_.window_bg,
                imgui.ImVec4(0.0, 0.0, 0.0, self.gui_manager.window_background_alpha),
            )
            imgui.push_style_color(
                imgui.Col_.border,
                imgui.ImVec4(*self.gui_manager.overlay_border_color, 1.0),
            )

            _, _ = imgui.begin(
                "MediaControls_Bottom", False,
                flags=imgui.WindowFlags_.no_title_bar |
                    imgui.WindowFlags_.no_resize |
                    imgui.WindowFlags_.no_move |
                    imgui.WindowFlags_.no_saved_settings |
                    imgui.WindowFlags_.no_scrollbar
            )

            if self.button_font:
                self.gui_manager.push_font(self.button_font, 18)

            imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(0, 0))
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.1, 0.1, 0.1, 0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.8, 0.8, 0.8, 0.15))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.8, 0.8, 0.8, 0.3))

            favorite_tex = self._get_current_favorite_button_tex()

            if self.gui_manager.image_button("##favorite", favorite_tex, btn_w, btn_h):
                self.toggle_current_visual_favorite()
            if imgui.is_item_hovered():
                if favorite_tex == self.favorite_on_tex:
                    self.gui_manager.tooltip("Remove from Favorites", self.tooltip_font)
                else:
                    self.gui_manager.tooltip("Add to Favorites", self.tooltip_font)

            if bottom_buttons:
                imgui.same_line(spacing=spacing)

            for i, tex in enumerate(bottom_buttons):
                tint = (1.0,1.0,1.0,1.0)
                if tex in (self.lock_preset_tex, self.unlock_preset_tex):
                    locked = self.ui_ctrl.get_visual_locked()
                    if (tex==self.lock_preset_tex and locked) or (tex==self.unlock_preset_tex and not locked):
                        if self.gui_manager.image_button(f"##bottom-{i}", tex, btn_w, btn_h, tint):
                            if self.ui_ctrl:
                                self.ui_ctrl.toggle_visual_lock()
                            else:
                                self.toggle_lock()
                        if imgui.is_item_hovered():
                            self.gui_manager.tooltip("Unlock the preset" if locked else "Lock the preset", self.tooltip_font)
                elif tex == self.prev_preset_tex:
                    if self.gui_manager.image_button(f"##bottom-{i}", tex, btn_w, btn_h):
                        if self.ui_ctrl:
                            self.ui_ctrl.previous_visual()
                        else:
                            self.ui_ctrl.previous_visual()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Previous visual", self.tooltip_font)
                elif tex == self.next_visual_tex:
                    if self.gui_manager.image_button(f"##bottom-{i}", tex, btn_w, btn_h):
                        if self.ui_ctrl:
                            self.ui_ctrl.next_visual()
                        else:
                            self.ui_ctrl.next_visual()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Next visual", self.tooltip_font)
                elif tex == self.sprites_tex:
                    if self.gui_manager.image_button(f"##bottom-{i}", tex, btn_w, btn_h):
                        self.toggle_sprite_popup()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Open sprite browser", self.tooltip_font)
                elif tex == self.visual_playlist_tex:
                    if self.gui_manager.image_button(f"##bottom-{i}", tex, btn_w, btn_h):
                        self.toggle_visual_playlist_popup()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Open visual playlists", self.tooltip_font)
                elif tex == self.delete_preset_tex:
                    if self.gui_manager.image_button(f"##bottom-{i}", tex, btn_w, btn_h):
                        self.delete_current_visual_item()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Delete current visual item", self.tooltip_font)

                if i < len(bottom_buttons)-1:
                    imgui.same_line(spacing=spacing)

            imgui.pop_style_color(3)
            imgui.pop_style_var()

            if self.button_font:
                imgui.pop_font()

            imgui.end()
            imgui.pop_style_color(2)
            imgui.pop_style_var(2)

        if top_buttons:
            imgui.set_next_window_pos(imgui.ImVec2(top_win_x, top_win_y))
            imgui.set_next_window_size(imgui.ImVec2(top_total_width, top_row_height))
            imgui.push_style_var(imgui.StyleVar_.window_rounding, 6)
            imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding, padding))
            imgui.push_style_color(
                imgui.Col_.window_bg,
                imgui.ImVec4(0.0, 0.0, 0.0, self.gui_manager.window_background_alpha),
            )
            imgui.push_style_color(
                imgui.Col_.border,
                imgui.ImVec4(*self.gui_manager.overlay_border_color, 1.0),
            )

            _, _ = imgui.begin(
                "MediaControls_Top", False,
                flags=imgui.WindowFlags_.no_title_bar |
                      imgui.WindowFlags_.no_resize |
                      imgui.WindowFlags_.no_move |
                      imgui.WindowFlags_.no_saved_settings |
                      imgui.WindowFlags_.no_scrollbar
            )

            if self.button_font:
                self.gui_manager.push_font(self.button_font, 18)

            imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(0, 0))
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.1, 0.1, 0.1, 0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.8, 0.8, 0.8, 0.15))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.8, 0.8, 0.8, 0.3))

            for i, tex in enumerate(top_buttons):
                if tex in (self.play_tex, self.pause_tex):
                    if self._is_playing():
                        if self.gui_manager.image_button("##pause", self.pause_tex, btn_w, btn_h):
                            if self.ui_ctrl:
                                self.ui_ctrl.toggle_playback()
                            else:
                                self.toggle_play()
                        if imgui.is_item_hovered():
                            self.gui_manager.tooltip("Pause", self.tooltip_font)
                    else:
                        if self.gui_manager.image_button("##play", self.play_tex, btn_w, btn_h):
                            if self.ui_ctrl:
                                self.ui_ctrl.toggle_playback()
                            else:
                                self.toggle_play()
                        if imgui.is_item_hovered():
                            self.gui_manager.tooltip("Play", self.tooltip_font)
                elif tex == self.playlist_tex:
                    if self.gui_manager.image_button(f"##top-{i}", tex, btn_w, btn_h):
                        self.toggle_playlist_popup()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Open playlist", self.tooltip_font)
                elif tex == self.prev_tex:
                    if self.gui_manager.image_button(f"##top-{i}", tex, btn_w, btn_h):
                        if self.ui_ctrl:
                            self.ui_ctrl.previous_track()
                        else:
                            self.media_previous()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Previous track", self.tooltip_font)
                elif tex == self.next_tex:
                    if self.gui_manager.image_button(f"##top-{i}", tex, btn_w, btn_h):
                        if self.ui_ctrl:
                            self.ui_ctrl.next_track()
                        else:
                            self.media_next()
                    if imgui.is_item_hovered():
                        self.gui_manager.tooltip("Next track", self.tooltip_font)

                if i < len(top_buttons)-1:
                    imgui.same_line(spacing=spacing)

            imgui.pop_style_color(3)
            imgui.pop_style_var()  # frame padding

            if self.button_font:
                imgui.pop_font()

            imgui.end()
            imgui.pop_style_color(2)
            imgui.pop_style_var(2)

        if self.sprite_popup:
            popup_w = self.gui_manager.get_geometry_value('popup_w', int(safe_w * 0.8))
            popup_h = self.gui_manager.get_geometry_value('popup_h', int(safe_h * 0.48))
            x = int(safe_x + (safe_w - popup_w)//2)
            y = int(safe_y + (safe_h - popup_h)//2)
            self._render_sprite_popup(x, y, popup_w, popup_h)

        if self.playlist_popup:
            popup_w = self.gui_manager.get_geometry_value('popup_w', int(safe_w * 0.8))
            popup_h = self.gui_manager.get_geometry_value('popup_h', int(safe_h * 0.48))
            x = int(safe_x + (safe_w - popup_w)//2)
            y = int(safe_y + (safe_h - popup_h)//2)
            self._render_playlist_popup(x, y, popup_w, popup_h)

        if self.visual_playlist_popup:
            popup_w = min(safe_w - 16, max(self.gui_manager.get_geometry_value('popup_w', 0), int(safe_w * 0.97), 1100))
            popup_h = min(safe_h - 16, max(self.gui_manager.get_geometry_value('popup_h', 0), int(safe_h * 0.88), 620))
            x = int(safe_x + (safe_w - popup_w)//2)
            y = int(safe_y + (safe_h - popup_h)//2)
            self._render_visual_playlist_popup(x, y, popup_w, popup_h)

        if self.visual_playlist_create_popup:
            create_popup_w = min(safe_w - 80, max(int(safe_w * 0.45), 420))
            create_popup_h = min(safe_h - 80, max(int(safe_h * 0.24), 190))
            create_x = int(safe_x + (safe_w - create_popup_w)//2)
            create_y = int(safe_y + (safe_h - create_popup_h)//2)
            self._render_visual_playlist_create_popup(create_x, create_y, create_popup_w, create_popup_h)

        if self.audio_playlist_create_popup:
            create_popup_w = min(safe_w - 80, max(int(safe_w * 0.45), 420))
            create_popup_h = min(safe_h - 80, max(int(safe_h * 0.24), 190))
            create_x = int(safe_x + (safe_w - create_popup_w)//2)
            create_y = int(safe_y + (safe_h - create_popup_h)//2)
            self._render_audio_playlist_create_popup(create_x, create_y, create_popup_w, create_popup_h)

        if self.audio_directory_create_popup:
            create_popup_w = min(safe_w - 80, max(int(safe_w * 0.45), 420))
            create_popup_h = min(safe_h - 80, max(int(safe_h * 0.24), 190))
            create_x = int(safe_x + (safe_w - create_popup_w)//2)
            create_y = int(safe_y + (safe_h - create_popup_h)//2)
            self._render_audio_directory_create_popup(create_x, create_y, create_popup_w, create_popup_h)

    def _show_playlist_control(self):
        for handler in self.plugins:
            handler_running = getattr(handler, "_running", False)
            handler_playlist = getattr(handler, "handler_playlist", False)
            if handler_playlist and handler_running:
                return True
        return False

    def _render_sprite_popup(self, x, y, popup_w, popup_h):
        if not self.sprite_popup:
            return

        active = {name for name, info in self.ui_ctrl.projectm.sprites.items() if info.get("id", 0) > 0}

        if self.sprite_popup_just_opened:
            imgui.set_next_window_pos(imgui.ImVec2(x, y))
            self.sprite_popup_just_opened = False
        # Width is locked; height 0 auto-fits to the content so Close is never hidden.
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        opened, is_open = self.gui_manager.begin_window(
            "Sprites", True,
            flags=imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_resize
        )
        if not is_open or not opened:
            self.sprite_popup = False
            imgui.end()
            return
        
        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        child_height = self.gui_manager.fit_child_height(popup_h)
        imgui.begin_child("sprites_scroll", imgui.ImVec2(-1, child_height))

        self.sprite_keys = list(self.ui_ctrl.projectm.sprites.keys())
        for key in self.sprite_keys:
            info = self.ui_ctrl.projectm.sprites.get(key, {})
            label = f"{key} - {info.get('img','')}" if info.get('img') else str(key)
            selected = key in active
            changed, _ = imgui.selectable(label, selected)
            if changed:
                try:
                    self.ui_ctrl.handle_sprite(key)
                except Exception:
                    log.exception("Failed toggling sprite")
        imgui.end_child()

        if imgui.button("Close"):
            self.sprite_popup = False

        if self.button_font:
            imgui.pop_font()

        imgui.end()

    def _render_playlist_popup(self, x, y, popup_w, popup_h):        
        if not self.playlist_popup:
            return

        vlc = self._get_vlc_handler()

        if not self.fs_roots:
            self.fs_roots = self._discover_local_roots()

        dir_lines, dir_paths = self._build_dir_tree()
        self.dir_paths = dir_paths
        audio_playlist_names = self._get_audio_playlist_names(vlc)
        if self.audio_playlist_name not in audio_playlist_names:
            self.audio_playlist_name = audio_playlist_names[0] if audio_playlist_names else ""
        if self.audio_source_kind == "playlist":
            if audio_playlist_names and self.audio_source_value not in audio_playlist_names:
                self._set_audio_source_playlist(audio_playlist_names[0])
            if not audio_playlist_names:
                self.audio_source_value = ""
        if not audio_playlist_names:
            self.audio_playlists_expanded = False

        selected_playlist = self._get_selected_audio_playlist_name()
        playlist_items = []
        if selected_playlist and vlc and hasattr(vlc, "get_media_playlist_items"):
            playlist_items = vlc.get_media_playlist_items(selected_playlist)

        if self.playlist_popup_just_opened:
            imgui.set_next_window_pos(imgui.ImVec2(x, y))
            self.playlist_popup_just_opened = False
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        opened, is_open = self.gui_manager.begin_window(
            "Playlist Browser", True,
            flags=imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_resize
        )
        if not is_open or not opened:
            self.playlist_popup = False
            imgui.end()
            return

        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        child_height = self.gui_manager.fit_child_height(popup_h, table_button_rows=2)

        if imgui.begin_table("playlist_table", 3, flags=imgui.TableFlags_.borders | imgui.TableFlags_.resizable):
            imgui.table_setup_column("Library Sources")
            imgui.table_setup_column("Contents")
            imgui.table_setup_column("Play Queue")
            imgui.table_headers_row()
            imgui.table_next_row()

            # Column 0: Sources
            imgui.table_set_column_index(0)
            imgui.begin_child("dir_child", imgui.ImVec2(0, child_height))
            local_selected = self.audio_source_kind == "local"
            local_label = "[-] local" if self.audio_local_expanded else "[+] local"
            clicked, _ = imgui.selectable(local_label, local_selected)
            if clicked:
                self.audio_local_expanded = not self.audio_local_expanded

            if self.audio_local_expanded:
                for i, line in enumerate(dir_lines):
                    if i >= len(dir_paths):
                        continue
                    path = dir_paths[i]
                    selected = (self.audio_source_kind == "local" and self.current_dir == path)
                    clicked, _ = imgui.selectable(f"  {line}", selected)
                    if clicked:
                        if path in self.expanded_dirs:
                            self.expanded_dirs.remove(path)
                        else:
                            self.expanded_dirs.add(path)
                        self._set_audio_source_local(path)
                        dir_lines, dir_paths = self._build_dir_tree()
                        self.dir_paths = dir_paths
                    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                        self.gui_manager.run_in_thread(self._play_directory, path)
                    if self._begin_drag_source():
                        payload = json.dumps({"type": "dir", "path": path}).encode("utf-8")
                        self._set_drag_payload("DND_BROWSER", payload)
                        imgui.text(line)
                        imgui.end_drag_drop_source()

            playlist_selected = self.audio_source_kind == "playlist"
            playlist_root_label = "[-] playlists" if self.audio_playlists_expanded else "[+] playlists"
            clicked, _ = imgui.selectable(playlist_root_label, playlist_selected)
            if clicked:
                if audio_playlist_names:
                    self.audio_playlists_expanded = not self.audio_playlists_expanded
                    self._set_audio_source_playlist(self.audio_playlist_name)
                else:
                    # With no playlists, selecting the row should still switch mode
                    # so Add Playlist is visible, but should not expand.
                    self.audio_playlists_expanded = False
                    self._set_audio_source_playlist("")

            if self.audio_playlists_expanded:
                for playlist_name in audio_playlist_names:
                    row_selected = (
                        self.audio_source_kind == "playlist"
                        and self.audio_source_value == playlist_name
                    )
                    changed, _ = imgui.selectable(f"  {playlist_name}", row_selected)
                    if changed:
                        self._set_audio_source_playlist(playlist_name)
                    if self._begin_drag_source():
                        payload = json.dumps({"type": "audio_playlist", "name": playlist_name}).encode("utf-8")
                        self._set_drag_payload("DND_BROWSER", payload)
                        imgui.text(playlist_name)
                        imgui.end_drag_drop_source()
                    if imgui.begin_drag_drop_target():
                        payload = self._accept_drag_payload("DND_BROWSER")
                        if payload and vlc and hasattr(vlc, "add_paths_to_media_playlist"):
                            try:
                                data = self._decode_dnd_payload(payload)
                                if not data:
                                    raise ValueError("Invalid DND payload")
                                drop_paths = self._collect_drop_paths(data, vlc)
                                if drop_paths:
                                    vlc.add_paths_to_media_playlist(playlist_name, drop_paths)
                            except Exception:
                                log.exception("[DND] Failed dropping into playlist source row")
                        imgui.end_drag_drop_target()
                if not audio_playlist_names:
                    imgui.text("  (none)")
            imgui.end_child()

            # Column 1: Contents
            imgui.table_set_column_index(1)
            imgui.begin_child("content_child", imgui.ImVec2(0, child_height))
            if self.audio_source_kind == "playlist":
                if not selected_playlist:
                    imgui.text("Create a playlist to view items.")
                for idx, full_path in enumerate(playlist_items):
                    name = os.path.basename(full_path)
                    selected = idx in self.audio_playlist_selection
                    changed, _ = imgui.selectable(name, selected)
                    if changed:
                        if idx in self.audio_playlist_selection:
                            self.audio_playlist_selection.remove(idx)
                        else:
                            self.audio_playlist_selection.add(idx)

                    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                        if vlc and hasattr(vlc, "append_path_to_playlist"):
                            self._append_path_to_playlist(full_path)

                    if self._begin_drag_source():
                        payload = json.dumps({
                            "type": "audio_playlist_item",
                            "playlist": selected_playlist,
                            "index": idx,
                            "path": full_path,
                        }).encode("utf-8")
                        self._set_drag_payload("DND_BROWSER", payload)
                        imgui.text(name)
                        imgui.end_drag_drop_source()

                    if imgui.begin_drag_drop_target():
                        payload = self._accept_drag_payload("DND_BROWSER")
                        if payload and vlc and selected_playlist:
                            try:
                                data = self._decode_dnd_payload(payload)
                                if not data:
                                    raise ValueError("Invalid DND payload")
                                dtype = data.get("type")
                                if dtype == "audio_playlist_item" and data.get("playlist") == selected_playlist:
                                    vlc.move_item_in_media_playlist(selected_playlist, int(data.get("index", -1)), idx)
                                else:
                                    drop_paths = self._collect_drop_paths(data, vlc)

                                    if drop_paths:
                                        vlc.add_paths_to_media_playlist(selected_playlist, drop_paths, insert_at=idx)
                            except Exception:
                                log.exception("[DND] Failed dropping into playlist contents row")
                        imgui.end_drag_drop_target()

                self.gui_manager.push_style_color(imgui.Col_.button, 0, 0, 0, 0)
                self.gui_manager.push_style_color(imgui.Col_.button_hovered, 0, 0, 0, 0)
                self.gui_manager.push_style_color(imgui.Col_.button_active, 0, 0, 0, 0)
                imgui.invisible_button("content_drop_target", imgui.ImVec2(-1, -1))
                if imgui.begin_drag_drop_target():
                    payload = self._accept_drag_payload("DND_BROWSER")
                    if payload and vlc and selected_playlist:
                        try:
                            data = self._decode_dnd_payload(payload)
                            if not data:
                                raise ValueError("Invalid DND payload")
                            dtype = data.get("type")
                            if dtype == "audio_playlist_item" and data.get("playlist") == selected_playlist:
                                vlc.move_item_in_media_playlist(selected_playlist, int(data.get("index", -1)), max(len(playlist_items) - 1, 0))
                            else:
                                drop_paths = self._collect_drop_paths(data, vlc)

                                if drop_paths:
                                    vlc.add_paths_to_media_playlist(selected_playlist, drop_paths, insert_at=len(playlist_items))
                        except Exception:
                            log.exception("[DND] Failed dropping into playlist contents")
                    imgui.end_drag_drop_target()
                imgui.pop_style_color(3)
            else:
                for idx, full_path in enumerate(self.dir_entries):
                    name = os.path.basename(full_path)
                    selected = idx in self.content_selected
                    changed, _ = imgui.selectable(name, selected)
                    if changed:
                        if idx in self.content_selected:
                            self.content_selected.remove(idx)
                        else:
                            self.content_selected.add(idx)
                    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                        if vlc and hasattr(vlc, "append_path_to_playlist"):
                            self._append_path_to_playlist(full_path)
                    if self._begin_drag_source():
                        payload = json.dumps({"type": "file", "path": full_path}).encode("utf-8")
                        self._set_drag_payload("DND_BROWSER", payload)
                        imgui.text(name)
                        imgui.end_drag_drop_source()
            imgui.end_child()

            # Column 2: Queue
            imgui.table_set_column_index(2)
            imgui.begin_child("queue_child", imgui.ImVec2(0, child_height))
            queue_paths = vlc.get_playlist_paths() if (vlc and hasattr(vlc, "get_playlist_paths")) else []
            queue_names = [os.path.splitext(os.path.basename(p))[0] for p in queue_paths]
            for i, name in enumerate(queue_names):
                selected = (self.queue_selected == i)
                changed, _ = imgui.selectable(name, selected)
                if changed:
                    self.queue_selected = i
                if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                    if vlc and hasattr(vlc, "play_index"):
                        vlc.play_index(i)
                if self._begin_drag_source():
                    payload = json.dumps({"type": "queue", "index": i, "path": queue_paths[i]}).encode("utf-8")
                    self._set_drag_payload("DND_BROWSER", payload)
                    imgui.text(name)
                    imgui.end_drag_drop_source()

                if imgui.begin_drag_drop_target():
                    payload = self._accept_drag_payload("DND_BROWSER")
                    if payload and vlc:
                        try:
                            data = self._decode_dnd_payload(payload)
                            if not data:
                                raise ValueError("Invalid DND payload")
                            dtype = data.get("type")
                            if dtype == "queue" and hasattr(vlc, "move_playlist_item"):
                                vlc.move_playlist_item(int(data.get("index", -1)), i)
                            elif dtype in ("file", "audio_playlist_item") and hasattr(vlc, "insert_path_into_playlist"):
                                p = data.get("path")
                                if p:
                                    vlc.insert_path_into_playlist(p, i)
                            elif dtype == "dir" and vlc:
                                p = data.get("path")
                                if p:
                                    files = self._list_immediate_audio_files(p)
                                    if files:
                                        if hasattr(vlc, "insert_paths_into_playlist"):
                                            vlc.insert_paths_into_playlist(files, i)
                                        else:
                                            for offset, file_path in enumerate(files):
                                                vlc.insert_path_into_playlist(file_path, i + offset)
                        except Exception:
                            log.exception("[DND] Failed dropping into queue row")
                    imgui.end_drag_drop_target()

            self.gui_manager.push_style_color(imgui.Col_.button, 0, 0, 0, 0)
            self.gui_manager.push_style_color(imgui.Col_.button_hovered, 0, 0, 0, 0)
            self.gui_manager.push_style_color(imgui.Col_.button_active, 0, 0, 0, 0)
            imgui.invisible_button("queue_drop_target", imgui.ImVec2(-1, -1))
            if imgui.begin_drag_drop_target():
                payload = self._accept_drag_payload("DND_BROWSER")
                if payload:
                    try:
                        data = self._decode_dnd_payload(payload)
                        if not data:
                            raise ValueError("Invalid DND payload")
                        dtype = data.get("type")
                        if dtype in ("file", "audio_playlist_item") and vlc and hasattr(vlc, "append_path_to_playlist"):
                            self._append_path_to_playlist(data.get("path"))
                        elif dtype == "dir" and vlc:
                            paths = self._list_immediate_audio_files(data.get("path"))
                            if paths:
                                self.gui_manager.run_in_thread(self._append_paths_to_playlist, paths)
                        elif dtype == "queue" and hasattr(vlc, "move_playlist_item") and queue_paths:
                            src = int(data.get("index", -1))
                            vlc.move_playlist_item(src, len(queue_paths) - 1)
                    except Exception:
                        log.exception("[DND] Failed to process global drop payload")
                imgui.end_drag_drop_target()
            imgui.pop_style_color(3)
            imgui.end_child()

            imgui.table_next_row()
            imgui.table_set_column_index(0)
            if imgui.button("Refresh"):
                self._build_dir_tree()
            imgui.same_line()
            if self.audio_source_kind == "local":
                if imgui.button("Add Directory"):
                    self.toggle_audio_directory_create_popup()
                imgui.same_line()
                if imgui.button("Remove Directory"):
                    if self.current_dir and self.current_dir not in self.fs_roots:
                        try:
                            os.rmdir(self.current_dir)
                            fallback_root = self.fs_roots[0] if self.fs_roots else None
                            self._set_audio_source_local(os.path.dirname(self.current_dir) or fallback_root)
                            self._build_dir_tree()
                        except Exception:
                            log.exception("Failed removing directory '%s'", self.current_dir)
            elif self.audio_source_kind == "playlist":
                if imgui.button("Add Playlist"):
                    self.toggle_audio_playlist_create_popup()
                imgui.same_line()
                if imgui.button("Remove Playlist"):
                    if selected_playlist and vlc and hasattr(vlc, "delete_media_playlist"):
                        try:
                            deleted = vlc.delete_media_playlist(selected_playlist)
                            if deleted:
                                remaining = self._get_audio_playlist_names(vlc)
                                if remaining:
                                    self._set_audio_source_playlist(remaining[0])
                                else:
                                    self._set_audio_source_local(self.fs_roots[0] if self.fs_roots else None)
                        except Exception:
                            log.exception("Failed removing playlist '%s'", selected_playlist)
            else:
                if imgui.button("Add Directory"):
                    self.toggle_audio_directory_create_popup()

            imgui.table_set_column_index(1)
            if imgui.button("Add to Now Playing"):
                if self.audio_source_kind == "playlist":
                    for idx in sorted(self.audio_playlist_selection):
                        if idx < len(playlist_items):
                            self._append_path_to_playlist(playlist_items[idx])
                    self.audio_playlist_selection.clear()
                else:
                    for idx in sorted(self.content_selected):
                        if idx < len(self.dir_entries):
                            self._append_path_to_playlist(self.dir_entries[idx])
                    self.content_selected.clear()

            if imgui.button("Remove Selected"):
                if self.audio_source_kind == "playlist":
                    if selected_playlist and vlc and hasattr(vlc, "remove_indices_from_media_playlist"):
                        vlc.remove_indices_from_media_playlist(selected_playlist, sorted(self.audio_playlist_selection))
                    self.audio_playlist_selection.clear()
                else:
                    selected_paths = [self.dir_entries[idx] for idx in sorted(self.content_selected) if idx < len(self.dir_entries)]
                    for path in selected_paths:
                        try:
                            os.remove(path)
                        except Exception:
                            log.exception("Failed removing local file '%s'", path)
                    self._build_dir_tree()
                    self.content_selected.clear()

            imgui.table_set_column_index(2)
            if imgui.button("Remove"):
                self._queue_remove_selected()
            imgui.same_line()
            if imgui.button("Clear"):
                self._clear_queue()

            imgui.end_table()

        if imgui.button("Close"):
            self.playlist_popup = False

        if self.button_font:
            imgui.pop_font()

        imgui.end()

    def _render_visual_playlist_popup(self, x, y, popup_w, popup_h):
        if not self.visual_playlist_popup:
            return

        playlists = self.ui_ctrl.get_visual_playlist_names()
        active_playlist = self.ui_ctrl.get_active_visual_playlist_name()

        if self.selected_visual_playlist is None:
            self.selected_visual_playlist = active_playlist

        if self.visual_playlist_popup_just_opened:
            imgui.set_next_window_pos(imgui.ImVec2(x, y))
            self.visual_playlist_popup_just_opened = False
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        opened, is_open = self.gui_manager.begin_window(
            "Visual Playlists", True,
            flags=imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_resize
        )
        if not is_open or not opened:
            self.visual_playlist_popup = False
            imgui.end()
            return

        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        child_height = self.gui_manager.fit_child_height(popup_h, table_button_rows=3)

        playlist_items = self.ui_ctrl.get_visual_playlist_items(self.selected_visual_playlist) if self.selected_visual_playlist else []
        runtime_items, runtime_index_map = self.ui_ctrl.get_visual_runtime_items_with_indices()

        def handle_visual_drop_into_playlist(insert_at):
            payload = self._accept_drag_payload("DND_VISUAL_ITEM")
            if not payload or not self.selected_visual_playlist:
                return
            try:
                data = self._decode_dnd_payload(payload)
                if not data:
                    return
                path = data.get("path")
                source = data.get("source")
                src_index = int(data.get("index", -1))
                src_playlist = data.get("playlist")

                if source == "playlist" and src_playlist == self.selected_visual_playlist:
                    self.ui_ctrl.move_item_in_visual_playlist(self.selected_visual_playlist, src_index, insert_at)
                    return

                if source == "runtime" and active_playlist == self.selected_visual_playlist:
                    self.ui_ctrl.move_item_in_visual_playlist(active_playlist, src_index, insert_at)
                    return

                if path:
                    self.ui_ctrl.add_items_to_visual_playlist(self.selected_visual_playlist, [path], insert_at=insert_at)
            except Exception:
                log.exception("[DND] Failed dropping visual item into playlist")

        def handle_visual_drop_into_runtime(insert_at):
            payload = self._accept_drag_payload("DND_VISUAL_ITEM")
            if payload and active_playlist:
                try:
                    data = self._decode_dnd_payload(payload)
                    if not data:
                        return
                    path = data.get("path")
                    source = data.get("source")
                    src_index = int(data.get("index", -1))
                    src_playlist = data.get("playlist")

                    if source == "runtime":
                        self.ui_ctrl.move_visual_runtime_item(src_index, insert_at)
                        return

                    if source == "playlist" and src_playlist == active_playlist:
                        self.ui_ctrl.move_item_in_visual_playlist(active_playlist, src_index, insert_at)
                        return

                    if path:
                        self.ui_ctrl.add_items_to_visual_playlist(active_playlist, [path], insert_at=insert_at)
                except Exception:
                    log.exception("[DND] Failed dropping visual item into runtime queue")

            playlist_payload = self._accept_drag_payload("DND_VISUAL_PLAYLIST")
            if playlist_payload:
                try:
                    data = self._decode_dnd_payload(playlist_payload)
                    if not data:
                        raise ValueError("Invalid playlist payload")
                    playlist_name = data.get("name")
                    if playlist_name:
                        self._load_visual_playlist(playlist_name)
                except Exception:
                    log.exception("[DND] Failed loading playlist into runtime queue")

        if imgui.begin_table("visual_playlist_table", 3, flags=imgui.TableFlags_.borders | imgui.TableFlags_.resizable):
            imgui.table_setup_column("Playlists")
            imgui.table_setup_column("Playlist Items")
            imgui.table_setup_column("Now Playing")
            imgui.table_headers_row()
            imgui.table_next_row()

            imgui.table_set_column_index(0)
            imgui.begin_child("visual_playlists", imgui.ImVec2(0, child_height))
            for playlist in playlists:
                name = playlist.get("name")
                selected = (name == self.selected_visual_playlist)
                changed, _ = imgui.selectable(name, selected)
                if changed:
                    self.selected_visual_playlist = name
                    self.visual_playlist_selection.clear()

                if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                    self._load_visual_playlist(name)

                if self._begin_drag_source():
                    payload = json.dumps({"type": "playlist", "name": name}).encode("utf-8")
                    self._set_drag_payload("DND_VISUAL_PLAYLIST", payload)
                    imgui.text(name)
                    imgui.end_drag_drop_source()

                if imgui.begin_drag_drop_target():
                    payload = self._accept_drag_payload("DND_VISUAL_ITEM")
                    if payload:
                        try:
                            data = self._decode_dnd_payload(payload)
                            if not data:
                                raise ValueError("Invalid DND payload")
                            path = data.get("path")
                            if path:
                                self.ui_ctrl.add_items_to_visual_playlist(name, [path])
                        except Exception:
                            log.exception("[DND] Failed adding visual item to playlist")
                    imgui.end_drag_drop_target()
            imgui.end_child()

            imgui.table_set_column_index(1)
            imgui.begin_child("visual_items", imgui.ImVec2(0, child_height))
            for idx, item_path in enumerate(playlist_items):
                name = os.path.basename(item_path)
                selected = idx in self.visual_playlist_selection
                changed, _ = imgui.selectable(name, selected)
                if changed:
                    if idx in self.visual_playlist_selection:
                        self.visual_playlist_selection.remove(idx)
                    else:
                        self.visual_playlist_selection.add(idx)

                if self._begin_drag_source():
                    payload = json.dumps({
                        "path": item_path,
                        "source": "playlist",
                        "playlist": self.selected_visual_playlist,
                        "index": idx,
                    }).encode("utf-8")
                    self._set_drag_payload("DND_VISUAL_ITEM", payload)
                    imgui.text(name)
                    imgui.end_drag_drop_source()

                if imgui.begin_drag_drop_target():
                    handle_visual_drop_into_playlist(idx)
                    imgui.end_drag_drop_target()

            self.gui_manager.push_style_color(imgui.Col_.button, 0, 0, 0, 0)
            self.gui_manager.push_style_color(imgui.Col_.button_hovered, 0, 0, 0, 0)
            self.gui_manager.push_style_color(imgui.Col_.button_active, 0, 0, 0, 0)
            imgui.invisible_button("visual_items_drop", imgui.ImVec2(-1, -1))
            if imgui.begin_drag_drop_target():
                handle_visual_drop_into_playlist(len(playlist_items))
                imgui.end_drag_drop_target()
            imgui.pop_style_color(3)
            imgui.end_child()

            imgui.table_set_column_index(2)
            imgui.begin_child("visual_runtime", imgui.ImVec2(0, child_height))
            for idx, item_path in enumerate(runtime_items):
                name = os.path.basename(item_path)
                selected = idx in self.visual_runtime_selection
                changed, _ = imgui.selectable(name, selected)
                if changed:
                    if idx in self.visual_runtime_selection:
                        self.visual_runtime_selection.clear()
                    else:
                        self.visual_runtime_selection = {idx}

                if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                    if idx < len(runtime_index_map):
                        self.ui_ctrl.shift_visual_runtime_from_index(runtime_index_map[idx])
                        self.visual_runtime_selection.clear()

                if self._begin_drag_source():
                    payload = json.dumps({
                        "path": item_path,
                        "source": "runtime",
                        "playlist": active_playlist,
                        "index": idx,
                    }).encode("utf-8")
                    self._set_drag_payload("DND_VISUAL_ITEM", payload)
                    imgui.text(name)
                    imgui.end_drag_drop_source()

                # Accept drops directly on top of runtime rows, not only below the list.
                if imgui.begin_drag_drop_target():
                    handle_visual_drop_into_runtime(idx)
                    imgui.end_drag_drop_target()

            self.gui_manager.push_style_color(imgui.Col_.button, 0, 0, 0, 0)
            self.gui_manager.push_style_color(imgui.Col_.button_hovered, 0, 0, 0, 0)
            self.gui_manager.push_style_color(imgui.Col_.button_active, 0, 0, 0, 0)
            imgui.invisible_button("visual_runtime_drop", imgui.ImVec2(-1, -1))
            if imgui.begin_drag_drop_target():
                handle_visual_drop_into_runtime(len(runtime_items))
                imgui.end_drag_drop_target()
            imgui.pop_style_color(3)
            imgui.end_child()

            selected_paths = [playlist_items[i] for i in sorted(self.visual_playlist_selection) if i < len(playlist_items)]
            selected_runtime_paths = [runtime_items[i] for i in sorted(self.visual_runtime_selection) if i < len(runtime_items)]

            imgui.table_next_row()
            imgui.table_set_column_index(0)
            if imgui.button("Create Playlist"):
                self.toggle_visual_playlist_create_popup()

            if imgui.button("Delete Playlist"):
                if self.selected_visual_playlist:
                    deleted = self.ui_ctrl.delete_visual_playlist(self.selected_visual_playlist)
                    if deleted:
                        self.selected_visual_playlist = self.ui_ctrl.get_active_visual_playlist_name()

            if imgui.button("Load Playlist"):
                if self.selected_visual_playlist:
                    self._load_visual_playlist(self.selected_visual_playlist)

            imgui.table_set_column_index(1)
            if imgui.button("Add To Favorites"):
                if selected_paths:
                    self.ui_ctrl.add_items_to_visual_favorites(selected_paths)
                    self._invalidate_favorite_cache()

            if imgui.button("Remove From Favorites"):
                if selected_paths:
                    self.ui_ctrl.remove_items_from_visual_favorites(selected_paths)
                    self._invalidate_favorite_cache()

            if imgui.button("Delete Selected"):
                if selected_paths and self.selected_visual_playlist:
                    self.ui_ctrl.remove_items_from_visual_playlist(self.selected_visual_playlist, selected_paths)
                    self.visual_playlist_selection.clear()

            imgui.table_set_column_index(2)

            if imgui.button("Remove Selected"):
                if selected_runtime_paths:
                    self.ui_ctrl.remove_items_from_visual_playlist(active_playlist, selected_runtime_paths)
                    self.visual_runtime_selection.clear()

            if imgui.button("Remove All"):
                if runtime_items:
                    self.ui_ctrl.clear_visual_runtime_playlist()
                    self.visual_runtime_selection.clear()
            
            if self.ui_ctrl.get_visual_mode() != "none":
                shuffle_enabled = self.ui_ctrl.get_presets_shuffle()
                shuffle_label = "Shuffle: ON" if shuffle_enabled else "Shuffle: OFF"
                shuffle_button = (0.20, 0.65, 0.35, 0.95) if shuffle_enabled else (0.22, 0.22, 0.22, 0.95)
                shuffle_hovered = (0.28, 0.76, 0.42, 0.95) if shuffle_enabled else (0.32, 0.32, 0.32, 0.95)
                shuffle_active = (0.16, 0.55, 0.30, 1.00) if shuffle_enabled else (0.28, 0.28, 0.28, 1.00)

                self.gui_manager.push_style_color(imgui.Col_.button, *shuffle_button)
                self.gui_manager.push_style_color(imgui.Col_.button_hovered, *shuffle_hovered)
                self.gui_manager.push_style_color(imgui.Col_.button_active, *shuffle_active)
                if imgui.button(shuffle_label):
                    self.ui_ctrl.toggle_presets_shuffle()
                if imgui.is_item_hovered():
                    self.gui_manager.tooltip("Toggle playlist shuffle", self.tooltip_font)
                imgui.pop_style_color(3)
                imgui.same_line()

            imgui.end_table()

        imgui.separator()
        if imgui.button("Close", imgui.ImVec2(-1, 0)):
            self.visual_playlist_popup = False

        if self.button_font:
            imgui.pop_font()

        imgui.end()

    def _render_visual_playlist_create_popup(self, x, y, popup_w, popup_h):
        if not self.visual_playlist_create_popup:
            return
        
        imgui.set_next_window_pos(
            imgui.ImVec2(x + popup_w / 2, y + popup_h / 2),
            pivot=imgui.ImVec2(0.5, 0.5)
        )
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        imgui.open_popup("Create Visual Playlist")
        opened, is_open = self.gui_manager.begin_modal("Create Visual Playlist", True)
        if not opened or not is_open:
            self.visual_playlist_create_popup = False
            return

        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        imgui.text_unformatted("Create a new visual playlist")
        imgui.spacing()

        changed, value = imgui.input_text("##name_input", self.pending_visual_playlist_name)

        if changed:
            self.pending_visual_playlist_name = value.strip()[:255]
        
        imgui.spacing()

        if imgui.button("Create"):
            if self.pending_visual_playlist_name:
                created = self.ui_ctrl.create_visual_playlist(self.pending_visual_playlist_name)
                if created:
                    self.selected_visual_playlist = self.pending_visual_playlist_name
                    self.ui_ctrl.set_active_visual_playlist(self.pending_visual_playlist_name)
                self.visual_playlist_create_popup = False
                imgui.close_current_popup()

        imgui.same_line()
        if imgui.button("Cancel"):
            self.visual_playlist_create_popup = False
            self.pending_visual_playlist_name = ""
            imgui.close_current_popup()

        if self.button_font:
            imgui.pop_font()

        imgui.end_popup()

    def _render_audio_playlist_create_popup(self, x, y, popup_w, popup_h):
        if not self.audio_playlist_create_popup:
            return

        vlc = self._get_vlc_handler()

        imgui.set_next_window_pos(
            imgui.ImVec2(x + popup_w / 2, y + popup_h / 2),
            pivot=imgui.ImVec2(0.5, 0.5)
        )
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        imgui.open_popup("Create Audio Playlist")
        opened, is_open = self.gui_manager.begin_modal("Create Audio Playlist", True)
        if not opened or not is_open:
            self.audio_playlist_create_popup = False
            return

        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        imgui.text_unformatted("Create a new top-level audio playlist")
        imgui.spacing()

        changed, value = imgui.input_text("##audio_playlist_name_input", self.pending_audio_playlist_name)
        if changed:
            self.pending_audio_playlist_name = value.strip()[:255]

        imgui.spacing()

        if imgui.button("Create"):
            if self.pending_audio_playlist_name and vlc and hasattr(vlc, "create_media_playlist"):
                created = vlc.create_media_playlist(self.pending_audio_playlist_name)
                if created:
                    self._set_audio_source_playlist(self.pending_audio_playlist_name)
                    self.audio_playlists_expanded = True
            self.audio_playlist_create_popup = False
            self.pending_audio_playlist_name = ""
            imgui.close_current_popup()

        imgui.same_line()
        if imgui.button("Cancel"):
            self.audio_playlist_create_popup = False
            self.pending_audio_playlist_name = ""
            imgui.close_current_popup()

        if self.button_font:
            imgui.pop_font()

        imgui.end_popup()

    def _render_audio_directory_create_popup(self, x, y, popup_w, popup_h):
        if not self.audio_directory_create_popup:
            return

        imgui.set_next_window_pos(
            imgui.ImVec2(x + popup_w / 2, y + popup_h / 2),
            pivot=imgui.ImVec2(0.5, 0.5)
        )
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        imgui.open_popup("Create Directory")
        opened, is_open = self.gui_manager.begin_modal("Create Directory", True)
        if not opened or not is_open:
            self.audio_directory_create_popup = False
            return

        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        base_dir = self.current_dir if self.audio_source_kind == "local" and self.current_dir else (self.fs_roots[0] if self.fs_roots else None)
        imgui.text_unformatted(f"Create directory in: {base_dir}")
        imgui.spacing()

        changed, value = imgui.input_text("##audio_directory_name_input", self.pending_audio_directory_name)
        if changed:
            self.pending_audio_directory_name = value.strip()[:255]

        imgui.spacing()

        if imgui.button("Create"):
            name = self.pending_audio_directory_name.strip()
            if name and base_dir:
                try:
                    new_dir = os.path.join(base_dir, name)
                    os.makedirs(new_dir, exist_ok=False)
                    self.audio_local_expanded = True
                    self._set_audio_source_local(new_dir)
                    self._build_dir_tree()
                except Exception:
                    log.exception("Failed creating local directory")
            self.audio_directory_create_popup = False
            self.pending_audio_directory_name = ""
            imgui.close_current_popup()

        imgui.same_line()
        if imgui.button("Cancel"):
            self.audio_directory_create_popup = False
            self.pending_audio_directory_name = ""
            imgui.close_current_popup()

        if self.button_font:
            imgui.pop_font()

        imgui.end_popup()

    #endregion