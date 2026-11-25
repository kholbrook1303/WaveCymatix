import logging
import math
import matplotlib.font_manager as fm
import os
import sdl2
import threading
from contextlib import contextmanager

from imgui_bundle import imgui
from imgui_bundle.python_backends.sdl2_backend import SDL2Renderer
from OpenGL import GL
from OpenGL import platform as gl_platform
from PIL import Image

from wavecymatix.lib.common import get_environment

log = logging.getLogger()

class GuiManager:
    # Window title bars (and their close button) are sized by the font active at begin().
    TITLE_FONT_SIZE = 22
    SAFE_AREA_MAX_ASPECT = 16.0 / 9.0

    # Supported fonts
    SUPPORTED_FONTS = {
        "DejaVuSans": {},
        "DejaVuSansMono-Bold": {},
        "LiberationSans-Regular": {},
        "LiberationSans-Bold": {}
    }

    def __init__(self, sdl_window, ui_scale_factor=1.0, ui_settings=None):
        """
        Manages ImGui context, font loading, and style. 
        Provides utilities for UI scaling and geometry caching.
        sdl_window: your SDL2 rendering window (needed for SDL2Renderer)
        """
        imgui.create_context()
        self._io = imgui.get_io()
        self._io.set_ini_filename(None)
        self._ui_settings = ui_settings or {}
        self.window_selected_color = self._get_color_setting(
            "window_selected_color",
            (41, 74, 122),
        )
        self.window_deselected_color = self._get_color_setting(
            "window_deselected_color",
            (20, 20, 20),
        )
        self.window_border_color = self._get_color_setting(
            "window_border_color",
            (0, 0, 0),
        )
        self.overlay_border_color = self._get_color_setting(
            "overlay_border_color",
            (128, 128, 128),
        )
        self.window_background_alpha = self._get_alpha_setting(
            "window_background_alpha",
            0.75,
        )

        self._software_cursor = get_environment() == 'lite'

        # Lite OS has no desktop compositor; use ImGui software cursor and
        # keep SDL hardware cursor disabled to avoid double cursors.
        if self._software_cursor:
            self._io.mouse_draw_cursor = False
            sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)
            log.info("GuiManager: enabled software cursor mode for Lite environment")

        try:
            pyopengl_ctx = gl_platform.GetCurrentContext()
            log.info(
                f"GuiManager pre-renderer context check: "
                f"pyopengl_current={bool(pyopengl_ctx)} "
                f"PYOPENGL_PLATFORM={os.environ.get('PYOPENGL_PLATFORM', '<unset>')}"
            )
        except Exception as ex:
            log.error(f"GuiManager context visibility check failed: {ex}")

        # SDL2Renderer for actual drawing
        self._impl = SDL2Renderer(sdl_window)

        # Dynamic fonts are loaded once; ImGui rasterizes glyphs as sizes are requested.
        self._loaded_fonts = {}
        self._font_families = {"DejaVuSans"}
        self._font_load_attempted = set()
        
        # Apply a style
        self._setup_style()

        # Logical design reference only; font raster sizes are not capped here.
        self._base_ui_height = 720.0
        try:
            ui_scale_factor = float(ui_scale_factor)
        except (TypeError, ValueError):
            log.warning("Invalid UI scale factor %r; using 1.0", ui_scale_factor)
            ui_scale_factor = 1.0

        if not math.isfinite(ui_scale_factor) or not 0.0 < ui_scale_factor <= 1.0:
            log.warning(
                "UI scale factor must be greater than 0 and at most 1.0; "
                "using 1.0 instead of %r",
                ui_scale_factor,
            )
            ui_scale_factor = 1.0

        self.ui_scale_factor = ui_scale_factor

        # Geometry cache
        self._geometry_cache = {}
        self._last_layout_scale = None
        self._pending_mouse_pos = None

    def set_cursor_visible(self, visible):
        if self._software_cursor:
            self._io.mouse_draw_cursor = bool(visible)

    def set_mouse_position(self, x, y):
        if self._software_cursor:
            self._pending_mouse_pos = (float(x), float(y))

    #region Private Helpers

    def _preload_fonts(self):
        # Keep the default UI font first so registered families cannot
        # become the implicit font for widgets without an explicit push.
        font_names = ["DejaVuSans"]
        font_names.extend(sorted(self._font_families - {"DejaVuSans"}))
        for font_name in font_names:
            if font_name in self._font_load_attempted:
                continue
            self._font_load_attempted.add(font_name)

            path = self.discover_font_path(font_name)
            if not path:
                log.warning("No system font found for %s", font_name)
                continue

            log.debug("Loading dynamic font: %s -> %s", font_name, path)
            self._loaded_fonts[font_name] = self._io.fonts.add_font_from_file_ttf(path, 16.0)

        if not self._loaded_fonts:
            log.warning("No configured system fonts loaded; using ImGui's default font")
            self._loaded_fonts["DejaVuSans"] = self._io.fonts.add_font_default()

    def register_font_family(self, family):
        """Register a font family for loading before the next ImGui frame."""
        self._font_families.add(family)

    def _ensure_fonts(self):
        self._preload_fonts()

    def _setup_style(self):
        style = imgui.get_style()
        background_color = imgui.ImVec4(
            0.0,
            0.0,
            0.0,
            self.window_background_alpha,
        )
        style.set_color_(imgui.Col_.window_bg, background_color)
        style.set_color_(imgui.Col_.popup_bg, background_color)
        style.set_color_(
            imgui.Col_.title_bg,
            imgui.ImVec4(*self.window_deselected_color, 1.0),
        )
        style.set_color_(
            imgui.Col_.title_bg_active,
            imgui.ImVec4(*self.window_selected_color, 1.0),
        )
        style.set_color_(
            imgui.Col_.title_bg_collapsed,
            imgui.ImVec4(*self.window_deselected_color, 1.0),
        )
        style.set_color_(
            imgui.Col_.border,
            imgui.ImVec4(*self.window_border_color, 1.0),
        )
        style.window_rounding = 1
        style.frame_rounding = 4
        style.window_padding = (6, 6)
        style.frame_padding = (4, 3)

    def _get_color_setting(self, name, default):
        value = self._ui_settings.get(name, default)
        default_color = tuple(float(component) / 255.0 for component in default)
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            log.warning(
                "Invalid UI color setting %s=%r; using %r",
                name,
                value,
                default,
            )
            return default_color

        if any(
            isinstance(component, bool)
            or not isinstance(component, int)
            or not 0 <= component <= 255
            for component in value
        ):
            log.warning(
                "UI color setting %s must have RGB components from 0 to 255; using %r",
                name,
                default,
            )
            return default_color

        return tuple(float(component) / 255.0 for component in value)

    def _get_alpha_setting(self, name, default):
        value = self._ui_settings.get(name, default)
        try:
            alpha = float(value)
        except (TypeError, ValueError):
            log.warning(
                "Invalid UI alpha setting %s=%r; using %r",
                name,
                value,
                default,
            )
            return default

        if not math.isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            log.warning(
                "UI alpha setting %s must be between 0 and 1; using %r",
                name,
                default,
            )
            return default

        return alpha

    def _reset_opengl_state_for_imgui(self):
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

    def _get_outline_width(self):
        aspect = self.screen_w / self.screen_h

        # Keep ultrawide at current outline
        if aspect > (21.0 / 9.0):
            return 1

        # Scale outlines with the UI instead of switching at a 720p threshold.
        return max(1, int(round(2.0 * self.ui_scale)))

    #endregion

    #region Public Helpers

    def discover_font_path(self, full_name):
        font_files = fm.findSystemFonts(fontext="ttf")

        target = full_name.lower()

        for path in font_files:
            filename = os.path.basename(path).lower()

            # strip extension
            name_no_ext = os.path.splitext(filename)[0]

            if name_no_ext == target:
                return path

        return None

    def get_font(self, family="DejaVuSans"):
        font = self._loaded_fonts.get(family)
        if font is None:
            font = self._loaded_fonts.get("DejaVuSans")
        return font

    def push_font(self, font, size):
        """Push a dynamic ImGui font at a logical size scaled for the display."""
        imgui.push_font(font, self.scale_px(size, as_int=False))

    def begin_window(self, title, closable=True, flags=0):
        """imgui.begin with a larger title bar; caller pushes its own body font."""
        title_font = self.get_font()
        if title_font:
            self.push_font(title_font, self.TITLE_FONT_SIZE)
        try:
            flags |= imgui.WindowFlags_.no_saved_settings
            return imgui.begin(title, closable, flags=flags)
        finally:
            if title_font:
                imgui.pop_font()

    def title_bar_height(self):
        title_font = self.get_font()
        if title_font:
            self.push_font(title_font, self.TITLE_FONT_SIZE)
        try:
            return imgui.get_font_size() + imgui.get_style().frame_padding.y * 2
        finally:
            if title_font:
                imgui.pop_font()

    def fit_child_height(self, window_h, table_button_rows=0):
        """
        Height for the one fixed-height scroll child of a window that is auto-fit
        in height, so title + body + bottom Close button stay within window_h.
        Call inside the window with the body font pushed. table_button_rows > 0
        also reserves a table header row and that many stacked button rows.
        """
        style = imgui.get_style()
        frame_h = imgui.get_frame_height()
        sp = style.item_spacing.y

        reserved = self.title_bar_height() + 2 * style.window_padding.y + frame_h + 4 * sp
        if table_button_rows:
            reserved += (frame_h + 2 * sp) + table_button_rows * frame_h + (table_button_rows + 2) * sp
        return max(60, window_h - reserved)

    def begin_modal(self, title, closable=True, flags=0):
        """begin_popup_modal with a larger title bar; caller pushes its own body font."""
        title_font = self.get_font()
        if title_font:
            self.push_font(title_font, self.TITLE_FONT_SIZE)
        try:
            return imgui.begin_popup_modal(title, closable, flags=flags)
        finally:
            if title_font:
                imgui.pop_font()

    def scale_px(self, value, min_value=1, as_int=True):
        scaled = float(value) * float(getattr(self, 'ui_scale', 1.0))
        if as_int:
            return max(int(scaled), int(min_value))
        return max(scaled, float(min_value))

    @contextmanager
    def ui_element_scale(self, scale_factor=1.0):
        """Temporarily apply an overlay-specific scale within the safe region."""
        try:
            scale_factor = float(scale_factor)
        except (TypeError, ValueError):
            log.warning("Invalid UI element scale factor %r; using 1.0", scale_factor)
            scale_factor = 1.0

        if not math.isfinite(scale_factor) or not 0.0 < scale_factor <= 1.0:
            log.warning(
                "UI element scale factor must be greater than 0 and at most 1.0; "
                "using 1.0 instead of %r",
                scale_factor,
            )
            scale_factor = 1.0

        previous_factor = self._active_element_scale_factor
        self._active_element_scale_factor *= scale_factor
        self._apply_ui_scale_factor()
        try:
            yield
        finally:
            self._active_element_scale_factor = previous_factor
            self._apply_ui_scale_factor()

    def load_texture(self, path):
        image = Image.open(path).convert("RGBA")

        image = image.transpose(Image.FLIP_TOP_BOTTOM)

        width, height = image.size
        image_data = image.tobytes("raw", "RGBA", 0, -1)

        tex_id = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)

        GL.glTexParameteri(
            GL.GL_TEXTURE_2D,
            GL.GL_TEXTURE_MIN_FILTER,
            GL.GL_LINEAR_MIPMAP_LINEAR,
        )
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)

        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGBA,
            width, height, 0,
            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, image_data
        )
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        return tex_id, width, height

    def run_in_thread(self, func, *args, **kwargs):
        def thread_func():
            try:
                func(*args, **kwargs)
            except Exception as e:
                log.exception(f"Error in thread for {func.__name__}: {e}")

        threading.Thread(target=thread_func, daemon=True).start()

    def get_colored_button(self, label, color, size=None):
        if size is None:
            size = (0, 0)
        self.push_style_color(imgui.Col_.button, *color)
        self.push_style_color(imgui.Col_.button_hovered, min(color[0]+0.2,1), min(color[1]+0.2,1), min(color[2]+0.2,1), color[3])
        self.push_style_color(imgui.Col_.button_active, max(color[0]-0.2,0), max(color[1]-0.2,0), max(color[2]-0.2,0), color[3])
        pressed = imgui.button(label, imgui.ImVec2(*size))
        imgui.pop_style_color(3)
        return pressed

    @staticmethod
    def push_style_color(index, red, green, blue, alpha):
        imgui.push_style_color(index, imgui.ImVec4(red, green, blue, alpha))

    @staticmethod
    def image_button(label, texture, width, height, tint_color=None):
        tint = imgui.ImVec4(*tint_color) if tint_color is not None else None
        return imgui.image_button(
            label,
            imgui.ImTextureRef(texture),
            imgui.ImVec2(width, height),
            tint_col=tint,
        )

    def draw_outlined_text(
        self,
        draw_list,
        x,
        y,
        text,
        color=(1, 1, 1, 1),
        outline_color=(0, 0, 0, 1),
        outline_width=None,
        font=None,
        font_size=16,
        scale=None
    ):
        if not text:
            return

        if outline_width is None:
            outline_width = self._get_outline_width()

        if not font:
            font = self.get_font()

        self.push_font(font, font_size)

        col = imgui.get_color_u32(imgui.ImVec4(*color))
        outline = imgui.get_color_u32(imgui.ImVec4(*outline_color))

        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw_list.add_text(imgui.ImVec2(x + dx, y + dy), outline, text)

        draw_list.add_text(imgui.ImVec2(x, y), col, text)

        imgui.pop_font()

    def tooltip(self, text, tooltip_font):
        """Display tooltip with scaled font if hovered."""
        if not imgui.is_item_hovered():
            return

        imgui.begin_tooltip()

        if tooltip_font:
            self.push_font(tooltip_font, 14)

        imgui.text_unformatted(text)

        if tooltip_font:
            imgui.pop_font()

        imgui.end_tooltip()

    def get_geometry_value(self, key, default=0):
        return self._geometry_cache.get(key, default)

    def get_button_dimensions(self, scale_factor=1.0):
        base_btn_h = self.get_geometry_value('btn_h', 32)
        base_btn_w = self.get_geometry_value('btn_w', 32)
        base_padding = self.get_geometry_value('padding', 8)
        base_spacing = self.get_geometry_value('spacing', 10)
        
        scaled_btn_h = int(base_btn_h * scale_factor)
        scaled_btn_w = int(base_btn_w * scale_factor)
        scaled_padding = int(base_padding * scale_factor)
        scaled_spacing = int(base_spacing * scale_factor)
        
        return (scaled_btn_h, scaled_btn_w, scaled_padding, scaled_spacing)

    def update_all_geometry(self):
        layout_key = (self.ui_scale, self.safe_w, self.safe_h)
        if self._last_layout_scale == layout_key and self._geometry_cache:
            return

        self._last_layout_scale = layout_key

        safe_h = self.safe_h
        btn_h = max(int(safe_h * 0.065), 28)
        spacing = max(int(safe_h * 0.02), 4)
        padding = max(spacing // 2, btn_h // 20)

        self._geometry_cache = {
            'btn_h': btn_h,
            'btn_w': max(28, int(btn_h * 1.1)),
            'spacing': spacing,
            'padding': padding,
            'extra_margin': int(padding * 1.5),
            'popup_w': min(int(self.safe_w), int(self.screen_w * 0.8)),
            'popup_h': int(safe_h * 0.48),
            'popup_header_h': max(int(safe_h * 0.06), 28),
            'column_w': min(int(self.safe_w), int(self.screen_w * 0.8)) // 3,
        }

    def get_safe_region_for_popups(self):
        return self.safe_x, self.safe_y, self.safe_w, self.safe_h

    def get_base_safe_region(self):
        """Return the full 16:9-capped region before UI scale factors are applied."""
        return self._base_safe_region

    def compute_safe_region(
        self,
        screen_w,
        screen_h,
        max_aspect=SAFE_AREA_MAX_ASPECT
    ):
        screen_w = float(screen_w)
        screen_h = float(screen_h)

        current_aspect = screen_w / screen_h

        # No constraint needed
        if current_aspect <= max_aspect:
            return 0.0, 0.0, screen_w, screen_h

        # Constrain to max_aspect (e.g. 16:9)
        safe_h = screen_h
        safe_w = safe_h * max_aspect

        safe_x = (screen_w - safe_w) * 0.5
        safe_y = 0.0

        return safe_x, safe_y, safe_w, safe_h

    def _compute_ui_scale(self, screen_w, screen_h, safe_w, safe_h):
        if safe_h <= 0.0:
            return 1.0
        return safe_h / self._base_ui_height

    def update_layout(self):
        io = imgui.get_io()

        screen_w = float(io.display_size.x)
        screen_h = float(io.display_size.y)

        self.screen_w = screen_w
        self.screen_h = screen_h

        self._base_safe_region = \
            self.compute_safe_region(screen_w, screen_h)

        self._active_element_scale_factor = 1.0
        self._apply_ui_scale_factor()

        self._ensure_fonts()

    def _apply_ui_scale_factor(self):
        base_x, base_y, base_w, base_h = self._base_safe_region
        factor = self.ui_scale_factor * self._active_element_scale_factor
        self.safe_x = base_x + base_w * (1.0 - factor) * 0.5
        self.safe_y = base_y + base_h * (1.0 - factor) * 0.5
        self.safe_w = base_w * factor
        self.safe_h = base_h * factor

        self.ui_scale = self._compute_ui_scale(
            self.screen_w,
            self.screen_h,
            self.safe_w,
            self.safe_h
        )

        # Compute and cache all geometry
        self.update_all_geometry()

    #endregion

    #region Main Loop

    def clear_frame(self):
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

    def new_frame(self):
        self._impl.process_inputs()

        if self._software_cursor and self._pending_mouse_pos is not None:
            self._io.mouse_pos = self._pending_mouse_pos

        # SDL input processing updates display_size; load any registered font
        # families before ImGui starts this frame.
        self.update_layout()

        imgui.new_frame()

    def process_event(self, event):
        return self._impl.process_event(event)

    def wants_keyboard_capture(self):
        return bool(self._io.want_capture_keyboard)

    def wants_mouse_capture(self):
        return bool(self._io.want_capture_mouse)

    def render(self):
        self._reset_opengl_state_for_imgui()
        imgui.render()
        self._impl.render(imgui.get_draw_data())

    #endregion