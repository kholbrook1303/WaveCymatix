import logging
import os

from imgui_bundle import imgui

from wavecymatix.lib.config import ASSET_ROOT

log = logging.getLogger()

class ToolbarUI:
    def __init__(self, gui_manager, thread_event, ui_ctrl):
        self.gui_manager = gui_manager
        self.thread_event = thread_event
        self.ui_ctrl = ui_ctrl

        self.visible = False
        self.help_visible = False
        self.ui_popup_open = False
        self.ui_popup_request_open = False
        self.visuals_popup_open = False
        self.help_section = "keyboard"
        
        self.plugins = None

        # Fonts (will be fetched from gui_manager)
        self.title_font = None
        self.button_font = None
        self.tooltip_font = None

        # Map plugin key -> asset filename (assets should exist)
        self.plugin_asset_map = {
            "airplay": "airplay.png",
            "bluetooth": "bluetooth.png",
            "plexamp": "plexamp.png",
            "spotify": "spotify.png",
            "vlc": "vlc.png",
            "windowsmedia": "windowsmedia.png"
        }

        # Cache loaded textures
        self.plugin_textures = {}
        # ordered list of (key, handler, tex) prepared each frame
        self.plugin_entries = []

        self.help_sections = [
            {
                "key": "keyboard",
                "label": "Keyboard",
                "title": "Keyboard Input",
                "rows": [
                    ("F1", "Show/hide this help"),
                    ("D", "Toggle diagnostics"),
                    ("F", "Toggle favorite for current visual"),
                    ("F (Ctrl)", "Toggle fullscreen mode"),
                    ("I (Ctrl)", "Next audio device"),
                    ("K (Ctrl)", "Kill all active sprites"),
                    ("L / Home", "Trigger logo sprite(s) if configured"),
                    ("M (Ctrl)", "Toggle media controls persistence"),
                    ("N / Right Arrow", "Load next visual"),
                    ("P (Ctrl)", "Toggle now playing persistence"),
                    ("P / Left Arrow / Back", "Load previous visual"),
                    ("Q (Ctrl)", "Exit application"),
                    ("T / Application", "Toggle track info / request audio lookup"),
                    ("V (Ctrl)", "Toggle visual mode on/off"),
                    ("Y (Ctrl)", "Toggle playlist shuffle"),
                    ("Delete", "Delete current preset"),
                    ("Space", "Toggle preset lock"),
                    ("Escape", "Close help/popups or toggle fullscreen"),
                    ("Arrow Up", "Increase beat sensitivity"),
                    ("Arrow Down", "Decrease beat sensitivity (-0.1)"),
                    ("0-9", "Enter sprite digits (2 digits triggers)"),
                ],
            },
            {
                "key": "media",
                "label": "Media",
                "title": "Controller Media Input",
                "rows": [
                    ("GUIDE", "Trigger logo sprite(s) if configured"),
                    ("AUDIO NEXT", "Next track"),
                    ("AUDIO PREV", "Previous track"),
                    ("AUDIO PLAY", "Toggle playback"),
                    ("AUDIO STOP", "No action"),
                ],
            },
            {
                "key": "axis",
                "label": "Axis",
                "title": "Controller Axis Input (Desktop only)",
                "rows": [
                    ("Left Stick X / Trigger Left", "Load previous visual"),
                    ("Left Stick X / Trigger Right", "Load next visual"),
                    ("Left Stick Y Up", "Increase beat sensitivity (+0.1)"),
                    ("Left Stick Y Down", "Decrease beat sensitivity (-0.1)"),
                ],
            },
            {
                "key": "buttons",
                "label": "Buttons",
                "title": "Controller Button Input (Desktop only)",
                "rows": [
                    ("Left/Right Stick Click", "Toggle preset lock"),
                    ("D-Pad Up", "Increase beat sensitivity (+0.1)"),
                    ("D-Pad Down", "Decrease beat sensitivity (-0.1)"),
                    ("D-Pad Left", "Load previous visual"),
                    ("D-Pad Right", "Load next visual"),
                    ("BACK + B", "Delete current preset"),
                    ("GUIDE", "Trigger logo sprite(s) if configured"),
                    ("GUIDE (held >= 3s)", "Enter guide hold mode"),
                ],
            },
            {
                "key": "mouse",
                "label": "Mouse",
                "title": "Mouse Input",
                "rows": [
                    ("Mouse motion", "Show cursor/UI and update toolbar visibility"),
                    ("Mouse wheel", "Scroll sprite box if popup is open"),
                    ("Left click", "No default action"),
                    ("Right click", "Toggle fullscreen mode"),
                ],
            },
            {
                "key": "touch",
                "label": "Touch",
                "title": "Touch Input",
                "rows": [
                    ("Two-finger pinch in", "Hide UI"),
                    ("Two-finger pinch out", "Show UI"),
                    ("Two-finger tap", "Toggle preset lock"),
                    ("Horizontal swipe", "Previous/next visual"),
                    ("Swipe down from top", "Open toolbar"),
                    ("Swipe up from top", "Close toolbar"),
                    ("Swipe up from bottom", "Show UI"),
                    ("Swipe down from bottom", "Hide UI"),
                    ("Single tap left edge", "Previous visual"),
                    ("Single tap right edge", "Next visual"),
                ],
            },
            {
                "key": "window",
                "label": "Window",
                "title": "Window Input",
                "rows": [
                    ("Close", "Exit application"),
                    ("Resize / size change", "Update render window size"),
                    ("Hidden / minimized", "Restore and show window"),
                    ("Focus lost / gained", "Log status"),
                ],
            },
        ]

    #region Private Button Helpers

    def toggle_ui_menu(self):
        """
        Open/close the UI submenu.
        """
        self.ui_popup_open = not self.ui_popup_open
        self.ui_popup_request_open = self.ui_popup_open
        if not self.ui_popup_open:
            self.visuals_popup_open = False

    #endregion

    #region Private Helpers

    def _ensure_plugin_textures(self):
        """Build self.plugin_entries from self.plugins and load textures if needed."""
        self.plugin_entries = []
        for handler in (self.plugins or []):
            try:
                key = handler.__class__.__name__.lower()
            except Exception:
                continue

            tex_info = self.plugin_textures.get(key)
            if not tex_info:
                asset_name = self.plugin_asset_map.get(key, f"{key}.png")
                path = os.path.join(ASSET_ROOT, asset_name)
                try:
                    tex, w, h = self.gui_manager.load_texture(path)
                    self.plugin_textures[key] = (tex, w, h)
                except Exception:
                    log.warning(f"Failed to load plugin asset: {path}")
                    self.plugin_textures[key] = (None, 0, 0)
                tex = self.plugin_textures[key][0]
            else:
                tex = tex_info[0]

            self.plugin_entries.append((key, handler, tex))

    def _render_ui_popup(self, x, y, popup_w, popup_h):
        """
        UI submenu popup.
        """

        if self.ui_popup_request_open:
            imgui.open_popup("UI Menu")
            self.ui_popup_request_open = False

        imgui.set_next_window_pos(imgui.ImVec2(x, y))
        # A popup defaults to its content's auto-fit width. At larger UI
        # scales that can exceed the width used to position it, so constrain
        # its width to the measured, screen-clamped value while retaining an
        # auto-fit height.
        imgui.set_next_window_size(imgui.ImVec2(popup_w, 0))
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)
        opened = imgui.begin_popup(
            "UI Menu",
            flags=imgui.WindowFlags_.no_saved_settings
        )

        if not opened:
            self.ui_popup_open = False
            self.visuals_popup_open = False
            return

        if self.button_font:
            self.gui_manager.push_font(self.button_font, 18)

        self.visuals_popup_open = False

        if self.ui_ctrl:
            if imgui.begin_menu("Visuals"):
                self.visuals_popup_open = True
                for mode_key, mode_label in self.ui_ctrl.visual_modes:
                    selected = self.ui_ctrl.get_visuals_enabled(mode_key)
                    clicked, _ = imgui.menu_item(mode_label, "", selected)
                    if clicked and not selected:
                        self.ui_ctrl.visuals_enabled = True
                        self.ui_ctrl.set_visual_mode(mode_key)
                imgui.end_menu()

        if self.ui_ctrl:
            if imgui.begin_menu("Media Player"):
                for action in ['on', 'auto', 'off']:
                    media_label = action.capitalize()
                    clicked, _ = imgui.menu_item(
                        media_label,
                        "",
                        self.ui_ctrl.get_media_controls_visibility(action)
                    )
                    if clicked:
                        self.ui_ctrl.set_media_controls_visibility(action)
                imgui.end_menu()

        if self.ui_ctrl:
            if imgui.begin_menu("Now Playing"):
                for action in ['on', 'auto', 'off']:
                    now_playing_label = action.capitalize()
                    clicked, _ = imgui.menu_item(
                        now_playing_label,
                        "",
                        self.ui_ctrl.get_now_playing_visibility(action)
                    )
                    if clicked:
                        self.ui_ctrl.set_now_playing_visibility(action)
                imgui.end_menu()

        if self.ui_ctrl and self.ui_ctrl.diagnostics_ui_enabled:
            clicked, _ = imgui.menu_item(
                "Diagnostics",
                "",
                self.ui_ctrl.is_diagnostics_visible()
            )
            if clicked:
                self.ui_ctrl.toggle_diagnostics()

        if self.button_font:
            imgui.pop_font()

        imgui.end_popup()

    #endregion

    #region Public Helpers

    def update_visibility(self, mouse_y):
        """Show toolbar if mouse near top of screen."""
        if not self.visible and mouse_y <= 5:
            self.visible = True

    def _get_help_section(self, section_key):
        for section in self.help_sections:
            if section["key"] == section_key:
                return section
        return self.help_sections[0]

    def _render_help_header_buttons(self, width, button_height):
        button_count = len(self.help_sections)
        if button_count == 0:
            return

        button_spacing = self.gui_manager.scale_px(6) if button_count > 1 else 0
        button_width = (width - (button_spacing * (button_count - 1))) / button_count

        for index, section in enumerate(self.help_sections):
            if index > 0:
                imgui.same_line(0, button_spacing)

            is_selected = (self.help_section == section["key"])
            if is_selected:
                imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.20, 0.55, 0.90, 1.0))
                imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.25, 0.65, 1.00, 1.0))
                imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.15, 0.45, 0.80, 1.0))
            else:
                imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.18, 0.18, 0.18, 1.0))
                imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.28, 0.28, 0.28, 1.0))
                imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.12, 0.12, 0.12, 1.0))

            if imgui.button(section["label"], imgui.ImVec2(button_width, button_height)):
                self.help_section = section["key"]

            imgui.pop_style_color(3)

    def _render_help_body(self, section, close_button_height):
        imgui.text(section["title"])
        imgui.separator()

        avail = imgui.get_content_region_avail()
        spacing = imgui.get_style().item_spacing.y
        footer_height = close_button_height + 1 + 3 * spacing
        scroll_h = max(1.0, avail.y - footer_height)

        rows = section.get("rows", [])
        label_col_width = 0.0
        if rows:
            label_col_width = max(imgui.calc_text_size(label).x for label, _ in rows)
        label_col_width += 18.0

        imgui.begin_child(
            "help_scroll",
            imgui.ImVec2(avail.x, scroll_h),
            imgui.ChildFlags_.borders
        )
        for label, description in rows:
            imgui.text(label)
            imgui.same_line(label_col_width)
            imgui.text_wrapped(description)
        imgui.end_child()

    #endregion

    #region Main Render Loop

    def render(self):
        io = imgui.get_io()

        screen_w = int(io.display_size.x if hasattr(io.display_size, "x") else io.display_size[0])
        screen_h = int(io.display_size.y if hasattr(io.display_size, "y") else io.display_size[1])

        # Fonts are preloaded, just fetch from cache
        self.title_font = self.gui_manager.get_font()
        self.button_font = self.gui_manager.get_font()
        self.tooltip_font = self.gui_manager.get_font()
        self.help_font = self.gui_manager.get_font()

        # Get button dimensions from centralized cache
        # Use full-size buttons for toolbar
        btn_h, btn_w, padding, plugin_spacing = self.gui_manager.get_button_dimensions(scale_factor=0.75)
        safe_x, safe_y, safe_w, safe_h = self.gui_manager.get_base_safe_region()

        # Toolbar height always tied to button size
        window_height = btn_h + (2 * padding)

        if self.visible:
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(screen_w, window_height))

            imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding, padding))
            imgui.push_style_var(imgui.StyleVar_.window_rounding, 0)
            imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(0, 0))

            imgui.begin(
                "Toolbar",
                flags=(
                    imgui.WindowFlags_.no_title_bar |
                    imgui.WindowFlags_.no_resize |
                    imgui.WindowFlags_.no_move |
                    imgui.WindowFlags_.no_scrollbar |
                    imgui.WindowFlags_.no_saved_settings
                )
            )

            button_font_active = False
            if self.button_font:
                self.gui_manager.push_font(self.button_font, 18)
                button_font_active = True

            # Plugin buttons
            self._ensure_plugin_textures()

            x = safe_x + padding
            for key, handler, tex in self.plugin_entries:
                imgui.set_cursor_pos(imgui.ImVec2(x, padding))

                if tex is None:
                    bg = (0.15, 0.15, 0.15, 0.6)
                    imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(*bg))

                    if imgui.button(key[0].upper(), imgui.ImVec2(btn_w, btn_h)):
                        if getattr(handler, "_running", False):
                            if hasattr(handler, "stop"):
                                self.gui_manager.run_in_thread(handler.stop)
                        else:
                            if hasattr(handler, "start"):
                                self.gui_manager.run_in_thread(handler.start)

                    imgui.pop_style_color()
                else:
                    active = getattr(handler, "_running", False)

                    imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
                    imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.8, 0.8, 0.8, 0.15))
                    imgui.push_style_color(
                        imgui.Col_.button_active,
                        imgui.ImVec4(*( (0.25, 0.6, 0.25, 1.0) if active else (0.25, 0.25, 0.25, 0.2) ))
                    )

                    tint = (0.95, 0.95, 0.95, 1.0) if not active else (0.0078, 0.6, 0.0863, 1.0)

                    if self.gui_manager.image_button(f"##plugin-{key}", tex, btn_w, btn_h, tint):
                        if active:
                            if hasattr(handler, "stop"):
                                self.gui_manager.run_in_thread(handler.stop)
                        else:
                            if hasattr(handler, "start"):
                                self.gui_manager.run_in_thread(handler.start)

                    imgui.pop_style_color(3)

                if imgui.is_item_hovered():
                    self.gui_manager.tooltip(f"{key.capitalize()} (click to toggle)", self.tooltip_font)

                x += btn_w + plugin_spacing

            # UI submenu button
            # Calculate button widths based on text
            close_text = "Close"
            close_text_w = imgui.calc_text_size(close_text).x
            close_width = max(btn_w, close_text_w + 24)

            help_text = "Help"
            help_text_w = imgui.calc_text_size(help_text).x
            help_width = max(btn_w, help_text_w + 24)

            ui_text = "Display"
            ui_text_w = imgui.calc_text_size(ui_text).x
            ui_width = max(btn_w, ui_text_w + 24)

            # Position from right to left: Close, Help, UI
            close_x = safe_x + safe_w - padding - close_width
            help_x = close_x - help_width - plugin_spacing
            ui_button_x = help_x - ui_width - plugin_spacing

            # Render UI button
            imgui.set_cursor_pos(imgui.ImVec2(ui_button_x, padding))
            ui_button_color = (0.2, 0.6, 0.9, 1.0) if self.ui_popup_open else (0.9, 0.6, 0.2, 1.0)
            if self.gui_manager.get_colored_button("Display", ui_button_color, (ui_width, btn_h)):
                self.toggle_ui_menu()

            if imgui.is_item_hovered():
                self.gui_manager.tooltip("Display Settings", self.tooltip_font)

            # Render Help button
            imgui.set_cursor_pos(imgui.ImVec2(help_x, padding))
            help_color = (0.2, 0.6, 0.9, 1.0) if self.help_visible else (0.9, 0.6, 0.2, 1.0)
            if self.gui_manager.get_colored_button("Help", help_color, (help_width, btn_h)):
                self.help_visible = not self.help_visible

            if imgui.is_item_hovered():
                self.gui_manager.tooltip("Help Menu", self.tooltip_font)

            # Render Close button
            imgui.set_cursor_pos(imgui.ImVec2(close_x, padding))
            if self.gui_manager.get_colored_button("Close", (1.0, 0.2, 0.2, 1.0), (close_width, btn_h)):
                self.thread_event.set()

            if imgui.is_item_hovered():
                self.gui_manager.tooltip("Close Application", self.tooltip_font)

            if button_font_active:
                imgui.pop_font()

            # Title text (centered)
            if self.title_font:
                self.gui_manager.push_font(self.title_font, 28)

            text = "WaveCymatix"
            text_w = imgui.calc_text_size(text).x
            text_h = imgui.get_font_size()

            center_x = safe_x + (safe_w - text_w) * 0.5
            center_y = (window_height - text_h) * 0.5

            imgui.set_cursor_pos(imgui.ImVec2(center_x, center_y))
            imgui.text_colored(imgui.ImVec4(1.0, 1.0, 1.0, 1.0), text)

            if self.title_font:
                imgui.pop_font()

            imgui.end()
            imgui.pop_style_var(3)

        ui_popup_x = None
        ui_popup_y = None

        # UI popup
        if self.ui_popup_open:
            margin = min(
                self.gui_manager.scale_px(8, min_value=1),
                max(0, (screen_w - 1) // 2),
                max(0, (screen_h - 1) // 2),
            )
            menu_labels = ["Visuals", "Media Player", "Now Playing"]
            if self.ui_ctrl and self.ui_ctrl.diagnostics_ui_enabled:
                menu_labels.append("Diagnostics")

            if self.button_font:
                self.gui_manager.push_font(self.button_font, 18)
            try:
                label_width = max(imgui.calc_text_size(label).x for label in menu_labels)
                row_height = imgui.calc_text_size("Diagnostics").y
            finally:
                if self.button_font:
                    imgui.pop_font()

            # Include menu-arrow/spacing and window padding. Cap to the actual
            # display width, not just the 16:9 safe region, so narrow windows
            # still get a fully visible dropdown.
            desired_popup_w = label_width + self.gui_manager.scale_px(64, min_value=1)
            available_w = max(1, screen_w - 2 * margin)
            ui_popup_w = max(1, min(int(desired_popup_w), available_w))
            ui_popup_h = (
                row_height * len(menu_labels) +
                self.gui_manager.scale_px(24, min_value=1)
            )

            right_edge = min(safe_x + safe_w, screen_w) - margin
            ui_popup_x = min(right_edge - ui_popup_w, screen_w - ui_popup_w - margin)
            ui_popup_x = max(margin, ui_popup_x)

            ui_popup_y = safe_y + window_height + self.gui_manager.scale_px(4, min_value=1)
            ui_popup_y = min(ui_popup_y, screen_h - ui_popup_h - margin)
            ui_popup_y = max(margin, ui_popup_y)

            self._render_ui_popup(ui_popup_x, ui_popup_y, ui_popup_w, ui_popup_h)

        # Help popup
        if self.help_visible:
            popup_w = int(safe_w * 0.6)
            popup_h = int(safe_h * 0.6)
            popup_x = safe_x + (safe_w - popup_w) // 2
            popup_y = safe_y + (safe_h - popup_h) // 2

            imgui.set_next_window_pos(imgui.ImVec2(popup_x, popup_y))
            imgui.set_next_window_size(imgui.ImVec2(popup_w, popup_h))
            imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

            opened, is_open = self.gui_manager.begin_window(
                "Help",
                True,
                flags=(
                    imgui.WindowFlags_.no_collapse |
                    imgui.WindowFlags_.no_resize |
                    imgui.WindowFlags_.no_saved_settings
                )
            )

            if not opened or not is_open:
                self.help_visible = False
                imgui.end()
            else:
                if self.help_font:
                    self.gui_manager.push_font(self.help_font, 16)

                imgui.text("Help - Input Event Handling")
                imgui.separator()

                header_button_height = self.gui_manager.scale_px(30)
                close_button_width = self.gui_manager.scale_px(80)
                close_button_height = self.gui_manager.scale_px(25)
                self._render_help_header_buttons(
                    imgui.get_content_region_avail().x,
                    header_button_height,
                )

                imgui.separator()

                section = self._get_help_section(self.help_section)
                self._render_help_body(section, close_button_height)

                imgui.separator()

                if imgui.button(
                    "Close",
                    imgui.ImVec2(close_button_width, close_button_height),
                ):
                    imgui.close_current_popup()
                    self.help_visible = False

                if self.help_font:
                    imgui.pop_font()

                imgui.end()

    #endregion