import logging
import os

log = logging.getLogger()


class UIController:
    """
    Centralized interface for managing UI state and interactions across components.
     - Manages visibility and state of UI elements (now playing, media controls, toolbar, diagnostics)
     - Manages visual modes (projectM, video background, slideshow)
     - Provides helper methods for common actions (playback control, visual navigation)
    """

    def __init__(self, config, sdl_rendering, plugins):
        """
        Initialize the UIController.

        Args:
            config: Configuration instance
            sdl_rendering: SDL rendering instance
            plugins: List of plugin handler instances
        """
        self.config = config
        self.sdl_rendering = sdl_rendering
        self.plugins = plugins

        self.visuals_enabled = config.ui.get('visuals_enabled', True)
        self.default_visual_mode = config.ui.get('default_visual_mode', 'none')

        self.projectm = None
        self.slideshow_ui = None
        self.video_background = None

        self.now_playing = None
        self.now_playing_enabled = config.ui.get('now_playing_enabled', True)
        self.now_playing_persistent = config.ui.get('now_playing_persistent', False)

        self.media_ui = None
        self.media_ui_enabled = config.ui.get('media_ui_enabled', True)
        self.media_ui_persistent = config.ui.get('media_ui_persistent', False)

        self.toolbar_ui = None
        self.toolbar_ui_enabled = config.ui.get('toolbar_ui_enabled', True)

        self.diagnostics_ui = None
        self.diagnostics_ui_enabled = config.ui.get('diagnostics_ui_enabled', True)

        self.audio_lookup = None
        
        # Track explicit user toggles (separate from visibility)
        # When False, don't show on mouse movement, but auto-hide still works
        self._media_controls_allowed = True
        self._toolbar_allowed = True

        self.visual_mode = "none"
        self.visual_modes = self.get_available_visual_modes()
        self.performance_policy_snapshot = {
            "mode": "none",
            "state": "INIT",
            "last_action": "none",
            "last_action_reason": "none",
            "last_suppressed_reason": "none",
        }

    # UI State

    def show_ui_elements(self, persist=True):
        """Show all UI elements"""
        if self.now_playing_enabled:
            if not self.is_now_playing_keep_visible() and persist:
                self.toggle_now_playing_persistence()
                self.now_playing.visible = True
            elif not self.is_now_playing_visible() and not persist:
                self.now_playing.display_track_info()

        if self.media_ui_enabled:
            if not self.is_media_controls_keep_visible() and persist:
                self.toggle_media_controls_persistence()

            self.media_ui.visible = True

    def hide_ui_elements(self, persistent=True):
        """Hide all UI elements"""
        if self.now_playing_enabled:
            if self.is_now_playing_keep_visible() and persistent:
                self.toggle_now_playing_persistence()
                self.now_playing.visible = False
            elif not self.is_now_playing_keep_visible() and not persistent:
                self.now_playing.visible = False

        if self.media_ui_enabled:
            if self.is_media_controls_keep_visible() and persistent:
                self.toggle_media_controls_persistence()
                self.media_ui.visible = False
            elif not self.is_media_controls_keep_visible() and not persistent:
                self.media_ui.visible = False
                self.media_ui.sprite_popup = False
                self.media_ui.playlist_popup = False
                self.media_ui.visual_playlist_popup = False
                self.media_ui.visual_playlist_create_popup = False

        if self.toolbar_ui_enabled:
            self.toolbar_ui.visible = False
            self.toolbar_ui.help_visible = False
            self.toolbar_ui.ui_popup_open = False
            self.toolbar_ui.visuals_popup_open = False

        self.sdl_rendering.show_cursor(False)

    # Visual state

    def get_available_visual_modes(self):
        modes = []

        if self.config.visuals.get('projectm_enabled', False):
            modes.append(("projectm", "ProjectM"))

        if self.config.visuals.get('video_background_enabled', False):
            modes.append(("video_background", "VideoBackground"))

        if self.config.visuals.get('slideshow_enabled', False):
            modes.append(("slideshow", "Slideshow"))

        modes.append(("none", "None"))

        return modes

    def get_visual_mode(self) -> str:
        return getattr(self, "visual_mode", "none")

    def _get_active_visual_component(self):
        if self.projectm and self.projectm.visible:
            return self.projectm
        if self.video_background and self.video_background.visible:
            return self.video_background
        if self.slideshow_ui and self.slideshow_ui.visible:
            return self.slideshow_ui
        return None

    def get_visuals_enabled(self, visual=None) -> bool:

        current = self.get_visual_mode()

        if visual is None:
            return current != "none"

        return current == visual

    def set_visual_mode(self, mode: str):
        self.projectm.visible = False
        self.slideshow_ui.visible = False
        self.video_background.visible = False
        if hasattr(self.video_background, "stop"):
            self.video_background.stop()

        if mode == "projectm":
            self.projectm.visible = True

        elif mode == "slideshow":
            self.slideshow_ui.visible = True

        elif mode == "video_background":
            self.video_background.visible = True

            if hasattr(self.video_background, "start"):
                self.video_background.start()

        elif mode == "none":
            pass

        self.visual_mode = mode

        log.info(f"Visual mode set to: {mode}")

    def get_visual_locked(self) -> bool:
        if self.projectm.visible:
            return self.projectm.get_visual_locked()
        elif self.video_background.visible:
            return self.video_background.get_visual_locked()
        elif self.slideshow_ui.visible:
            return self.slideshow_ui.get_visual_locked()
        return False

    def toggle_visual_lock(self):
        if self.projectm.visible:
            self.projectm.toggle_visual_lock()
            log.info(f"Visual lock toggled: {'LOCKED' if self.projectm.get_visual_locked() else 'UNLOCKED'}")
        elif self.video_background.visible:
            self.video_background.toggle_visual_lock()
            log.info(f"Video background visual lock toggled: {'LOCKED' if self.video_background.get_visual_locked() else 'UNLOCKED'}")
        elif self.slideshow_ui.visible:
            self.slideshow_ui.toggle_visual_lock()
            log.info(f"Slideshow visual lock toggled: {'LOCKED' if self.slideshow_ui.get_visual_locked() else 'UNLOCKED'}")

    def next_visual(self):
        if self.projectm.visible:
            self.projectm.next_visual()
            log.debug("User requested next preset")
        elif self.slideshow_ui.visible:
            self.slideshow_ui.next_visual()
            log.debug("User requested next slideshow image")
        elif self.video_background.visible:
            self.video_background.next_visual()
            log.debug("User requested next video background")

    def delete_visual(self, physical: bool = False):
        if self.projectm.visible:
            self.projectm.delete_visual(physical=physical)
            log.debug("User requested delete preset")
        elif self.slideshow_ui.visible:
            self.slideshow_ui.delete_visual(physical=physical)
            log.debug("User requested delete slideshow image")
        elif self.video_background.visible:
            self.video_background.delete_visual(physical=physical)
            log.debug("User requested delete video background")

    def previous_visual(self):
        if self.projectm.visible:
            log.debug("User requested previous preset")
            self.projectm.previous_visual()
        elif self.slideshow_ui.visible:
            log.debug("User requested previous slideshow image")
            self.slideshow_ui.previous_visual()
        elif self.video_background.visible:
            log.debug("User requested previous video background")
            self.video_background.previous_visual()

    # SDL rendering state

    def mouse_visible(self) -> bool:
        return self.sdl_rendering.mouse_visible

    def show_cursor(self, show: bool):
        self.sdl_rendering.show_cursor(show)
        log.info(f"Mouse cursor visibility set to: {'VISIBLE' if show else 'HIDDEN'}")

    def get_sdl_rendiering_window(self):
        return self.sdl_rendering.rendering_window

    def toggle_fullscreen(self):
        self.sdl_rendering.toggle_fullscreen()
        log.info(f"Fullscreen mode toggled: {'ON' if self.sdl_rendering.fullscreen else 'OFF'}")

    # Media controls state

    def is_media_controls_visible(self) -> bool:
        return self.media_ui.visible

    def is_media_controls_keep_visible(self) -> bool:
        return self.media_ui.keep_visible

    def get_media_controls_visibility(self, visibility: str):
        if visibility == "on":
            return self.media_ui_enabled and self.media_ui.keep_visible
        elif visibility == "auto":
            return self.media_ui_enabled and not self.media_ui.keep_visible
        elif visibility == "off":
            return not self.media_ui_enabled and not self.media_ui.visible
        return False

    def set_media_controls_visibility(self, visibility: str):
        if visibility == "on":
            self.media_ui_enabled = True
            self.media_ui.keep_visible = True
        elif visibility == "auto":
            self.media_ui_enabled = True
            self.media_ui.keep_visible = False
        elif visibility == "off":
            self.media_ui_enabled = False
            self.media_ui.visible = False
            self.media_ui.keep_visible = False

    def toggle_media_controls_persistence(self):
        self.media_ui.keep_visible = not self.media_ui.keep_visible
        
        # If enabling persistence, show the controls
        if self.media_ui.keep_visible:
            self.media_ui.visible = True
            log.info("Media controls persistence: ENABLED (pinned to screen)")
        # If disabling persistence, reset timing so it will auto-hide
        elif not self.media_ui.keep_visible:
            log.info("Media controls persistence: DISABLED (auto-hide enabled)")

    # Diagnostic state

    def is_diagnostics_visible(self) -> bool:
        return self.diagnostics_ui.visible

    def toggle_diagnostics(self):
        """Toggle diagnostics overlay visibility."""
        if hasattr(self, 'diagnostics_ui') and self.diagnostics_ui:
            self.diagnostics_ui.toggle()

    def get_diagnostics_snapshot(self):
        """Return normalized diagnostics payload for the active visual."""
        visual_mode = self.get_visual_mode()

        snapshot = {
            "visual_mode": visual_mode,
            "visual_name": visual_mode.replace('_', ' ').title(),
            "visual": {},
            "performance": self.performance_policy_snapshot,
        }

        if visual_mode == "projectm" and self.projectm:
            current_preset = self.projectm.get_current_preset() if hasattr(self.projectm, "get_current_preset") else None
            snapshot["visual"] = {
                "label": "Current Preset",
                "value": os.path.basename(current_preset) if current_preset else "N/A",
                "locked": self.projectm.get_visual_locked(),
                "projectm_settings": self.projectm.get_diagnostics_snapshot(),
            }

        elif visual_mode == "video_background" and self.video_background:
            if hasattr(self.video_background, "get_diagnostics_snapshot"):
                snapshot["visual"] = self.video_background.get_diagnostics_snapshot()
            else:
                snapshot["visual"] = {
                    "label": "Current Video",
                    "value": "N/A",
                    "locked": self.video_background.get_visual_locked(),
                }

        elif visual_mode == "slideshow" and self.slideshow_ui:
            if hasattr(self.slideshow_ui, "get_diagnostics_snapshot"):
                snapshot["visual"] = self.slideshow_ui.get_diagnostics_snapshot()
            else:
                snapshot["visual"] = {
                    "label": "Current Image",
                    "value": "N/A",
                    "locked": self.slideshow_ui.get_visual_locked(),
                }

        return snapshot

    def set_performance_policy_snapshot(self, snapshot):
        self.performance_policy_snapshot = dict(snapshot or {})

    # Toolbar state
    
    def is_toolbar_allowed(self) -> bool:
        return self._toolbar_allowed

    def is_toolbar_visible(self) -> bool:
        return self.toolbar_ui.visible

    def set_toolbar_visible(self, visible: bool):
        if not self._toolbar_allowed and visible:
            log.debug("Toolbar visibility change blocked (toolbar is not allowed)")
            return
        self.toolbar_ui.visible = visible
        log.info(f"Toolbar visibility set to: {'VISIBLE' if visible else 'HIDDEN'}")

    def toggle_toolbar(self):
        self._toolbar_allowed = not self._toolbar_allowed
        log.info(f"Toolbar {'ALLOWED' if self._toolbar_allowed else 'BLOCKED'}")

    # Now Playing override state

    def get_now_playing_visibility(self, visibility: str):
        if visibility == "on":
            return self.now_playing_enabled and self.now_playing.keep_visible
        elif visibility == "auto":
            return self.now_playing_enabled and not self.now_playing.keep_visible
        elif visibility == "off":
            return not self.now_playing_enabled and not self.now_playing.visible
        return False

    def set_now_playing_visibility(self, visibility: str):
        if visibility == "on":
            self.now_playing_enabled = True
            self.now_playing.keep_visible = True
        elif visibility == "auto":
            self.now_playing_enabled = True
            self.now_playing.keep_visible = False
        elif visibility == "off":
            self.now_playing_enabled = False
            self.now_playing.visible = False
            self.now_playing.keep_visible = False

    def is_now_playing_visible(self) -> bool:
        return self.now_playing.visible

    def is_now_playing_keep_visible(self) -> bool:
        return self.now_playing.keep_visible

    def toggle_now_playing_persistence(self):
        self.now_playing.keep_visible = not self.now_playing.keep_visible
        
        # If enabling override and we have track info, show it
        if self.now_playing.keep_visible and self.now_playing.text:
            self.now_playing.display_track_info()
            log.info("Now playing persistence: ENABLED (pinned to screen)")
        # If disabling override, reset timing so it will auto-hide
        elif not self.now_playing.keep_visible:
            log.info("Now playing persistence: DISABLED (auto-hide enabled)")

    def clear_track_info(self):
        """Clear track info from now playing UI."""
        if self.now_playing:
            self.now_playing.clear_track_info()

    def display_track_info(self):
        """Display current track info on now playing UI."""
        if (not self.is_audio_active() and self.config.audio_lookup.get('enabled', False)):
            self.request_audio_lookup()
        elif self.now_playing and self.now_playing.text:
            self.now_playing.display_track_info()

    def request_audio_lookup(self):
        """Request the audio lookup service to perform a lookup."""
        if hasattr(self, 'audio_lookup') and self.audio_lookup:
            try:
                self.audio_lookup.request_lookup()
            except Exception:
                log.exception('Audio lookup request failed')

    # Playback state

    def is_playing(self) -> bool:
        """Check if any audio handler is currently playing."""
        for handler in self.plugins:
            handler_active = getattr(handler, "handler_active", False)
            if not handler_active:
                continue
            func = getattr(handler, "is_playing", None)
            if callable(func):
                return func()
        return False

    def is_audio_active(self) -> bool:
        """Check if any audio handler is active (running)."""
        for handler in self.plugins:
            if getattr(handler, "handler_active", False):
                return True
        return False

    def toggle_playback(self):
        """Toggle playback between play and pause for active handler."""
        if not self.is_audio_active():
            log.info("No active audio handler available for playback toggle")
            return
        
        playing = self.is_playing()
        func_name = "pause" if playing else "play"
        self._invoke_audio_handler(func_name)

    def play_audio(self):
        """Play audio on active handler."""
        self._invoke_audio_handler("play")

    def pause_audio(self):
        """Pause audio on active handler."""
        self._invoke_audio_handler("pause")

    def next_track(self):
        """Skip to next track on active handler."""
        self._invoke_audio_handler("next")

    def previous_track(self):
        """Skip to previous track on active handler."""
        self._invoke_audio_handler("previous")

    def _invoke_audio_handler(self, func_name: str):
        for handler in self.plugins:
            handler_active = getattr(handler, "handler_active", False)
            if not handler_active:
                continue
            
            func = getattr(handler, func_name, None)
            if callable(func):
                log.info(f"Invoking '{func_name}' on {handler.__class__.__name__}")
                func()
                return
        
        log.debug(f"No active handler found to invoke '{func_name}'")

    # ProjectM Helpers

    def get_presets_shuffle(self) -> bool:
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "get_presets_shuffle"):
            return visual.get_presets_shuffle()
        return False

    def toggle_presets_shuffle(self):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "toggle_presets_shuffle"):
            visual.toggle_presets_shuffle()
            log.info(f"Presets shuffle toggled: {'ENABLED' if visual.get_presets_shuffle() else 'DISABLED'}")

    def set_window_size(self, width, height):
        if self.projectm.visible:
            self.projectm.set_window_size(width, height)

    def toggle_help(self):
        self.toolbar_ui.help_visible = not self.toolbar_ui.help_visible
        log.debug(f"Help dialog toggled: {'OPEN' if self.toolbar_ui.help_visible else 'CLOSED'}")

    def get_current_preset(self):
        if self.projectm.visible:
            return self.projectm.get_current_preset()

        return None

    def change_beat_sensitivity(self, amount):
        if self.projectm.visible:
            log.debug(f"User requested change beat sensitivity by {amount} in ProjectM")
            self.projectm.change_beat_sensitivity(amount)

    def kill_sprites(self):
        if self.projectm.visible:
            log.debug("User requested kill sprites in ProjectM")
            self.projectm.kill_sprites()

    def handle_sprite(self, spriteIdx):
        if self.projectm.visible:
            log.debug(f"User requested handle sprite {spriteIdx} in ProjectM")
            self.projectm.handle_sprite(spriteIdx)

    # Visual playlist APIs

    def get_visual_playlist_names(self):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "get_visual_playlist_names"):
            return visual.get_visual_playlist_names()
        return []

    def get_active_visual_playlist_name(self):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "get_active_visual_playlist_name"):
            return visual.get_active_visual_playlist_name()
        return "all"

    def get_visual_playlist_items(self, playlist_name):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "get_visual_playlist_items"):
            return visual.get_visual_playlist_items(playlist_name)
        return []

    def get_visual_runtime_items(self):
        items, _ = self.get_visual_runtime_items_with_indices()
        return items

    def get_visual_runtime_items_with_indices(self):
        visual = self._get_active_visual_component()
        if not visual or not hasattr(visual, "get_runtime_playlist_items"):
            return [], []

        runtime_items = list(visual.get_runtime_playlist_items())
        return runtime_items, list(range(len(runtime_items)))

    def set_visual_runtime_index(self, index):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "set_visual_runtime_index"):
            return visual.set_visual_runtime_index(index)
        return False

    def shift_visual_runtime_from_index(self, index):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "shift_runtime_from_index"):
            return visual.shift_runtime_from_index(index)
        return False

    def clear_visual_runtime_playlist(self):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "clear_runtime_playlist"):
            return visual.clear_runtime_playlist()
        return False

    def move_visual_runtime_item(self, src_index, dst_index):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "move_runtime_item"):
            return visual.move_runtime_item(src_index, dst_index)
        return False

    def set_active_visual_playlist(self, playlist_name):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "set_active_visual_playlist"):
            visual.set_active_visual_playlist(playlist_name)

    def create_visual_playlist(self, playlist_name):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "create_visual_playlist"):
            return visual.create_visual_playlist(playlist_name)
        return False

    def delete_visual_playlist(self, playlist_name):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "delete_visual_playlist"):
            return visual.delete_visual_playlist(playlist_name)
        return False

    def add_items_to_visual_playlist(self, playlist_name, items, insert_at=None):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "add_items_to_visual_playlist"):
            return visual.add_items_to_visual_playlist(playlist_name, items, insert_at=insert_at)
        return 0

    def remove_items_from_visual_playlist(self, playlist_name, items):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "remove_items_from_visual_playlist"):
            return visual.remove_items_from_visual_playlist(playlist_name, items)
        return 0

    def move_item_in_visual_playlist(self, playlist_name, src_index, dst_index):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "move_item_in_visual_playlist"):
            return visual.move_item_in_visual_playlist(playlist_name, src_index, dst_index)
        return False

    def add_items_to_visual_favorites(self, items):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "add_items_to_favorites"):
            result = visual.add_items_to_favorites(items)
            if self.media_ui and hasattr(self.media_ui, "_invalidate_favorite_cache"):
                self.media_ui._invalidate_favorite_cache()
            return result
        return 0

    def remove_items_from_visual_favorites(self, items):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "remove_items_from_favorites"):
            result = visual.remove_items_from_favorites(items)
            if self.media_ui and hasattr(self.media_ui, "_invalidate_favorite_cache"):
                self.media_ui._invalidate_favorite_cache()
            return result
        return 0

    def is_visual_item_favorite(self, item):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "is_item_favorite"):
            return visual.is_item_favorite(item)
        return False

    def toggle_current_visual_favorite(self):
        current_item = self.get_current_visual_item()
        if not current_item:
            return False

        if self.is_visual_item_favorite(current_item):
            self.remove_items_from_visual_favorites([current_item])
            return False

        self.add_items_to_visual_favorites([current_item])
        return True

    def get_current_visual_item(self):
        visual = self._get_active_visual_component()
        if visual and hasattr(visual, "get_current_visual_item"):
            return visual.get_current_visual_item()
        return None
