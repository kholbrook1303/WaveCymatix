import time
import logging
import numpy as np

from imgui_bundle import imgui
from OpenGL import GL
from PIL import Image, ImageDraw, ImageFont

from wavecymatix.core.ui.ScrollingText import ScrollingText

log = logging.getLogger("NowPlayingUI")

class NowPlayingUI:
    """Display track metadata and artwork, with text sized relative to artwork.

    The artwork height is a fraction of the safe display height. Title and
    artist-album font sizes are then fractions of that artwork height,
    keeping the layout proportional when resolution or safe-area dimensions change.
    """

    # Maximum rendered artwork height as a fraction of the safe-area height.
    ARTWORK_HEIGHT_RATIO = 0.55
    # Text height as a percentage of displayed artwork height. At 720p, where
    # artwork is 396px tall, these ratios produce approximately 48px/34px text.
    # The dynamic font atlas rasterizes the requested sizes as they are used.
    TITLE_FONT_ARTWORK_PERCENT = 12.00
    ALBUM_FONT_ARTWORK_PERCENT = 05.50

    def __init__(self, gui_manager, ui_ctrl):
        self.gui = gui_manager
        self.ui_ctrl = ui_ctrl
        self.gui.register_font_family("LiberationSans-Bold")

        # Overlay state
        self.visible = False
        self.burned_in = False
        self.keep_visible = False
        self.time_shown = None
        self.burn_in_delay = 8.0

        # Track info
        self.text = ""
        self.artist = ""
        self.album = ""
        self.album_art = None
        self.gui.now_playing_artwork_bottom = None

        # GL textures
        self.track_tex = None
        self.track_w = 0
        self.track_h = 0
        self.artist_album_tex = None
        self.artist_album_w = 0
        self.artist_album_h = 0
        self.album_tex = None
        self.album_w = 0
        self.album_h = 0
        self.album_ready = False
        self.album_calc_w = 0.0
        self.album_calc_h = 0.0

        # Fonts
        self.title_font = None
        self.album_font = None

        # Scrolling
        self.track_scroller = None
        self.artist_album_scroller = None

        # Flag to safely create textures in main thread
        self.needs_burnin_update = False

        # Base scale
        self.scale_x = 1.0
        self.scale_y = 1.0

        self.last_ui_scale = None
        self.last_track_signature = None
        self.last_artist_album_signature = None

    #region Private Helpers

    def _should_show_overlay(self) -> bool:
        if not self.visible or not self.text:
            return False
        
        # Override: explicitly pinned to screen
        if self.keep_visible:
            return True
        
        # Auto-hide: after 10 seconds, hide (unless override is on)
        if self.time_shown is not None:
            elapsed = time.time() - self.time_shown
            if elapsed > 10.0:
                self.visible = False
                return False
        
        return True

    def _should_burn_in(self) -> bool:
        # Don't burn if already burned
        if self.burned_in:
            return False
        
        # Don't burn if we're in keep-visible mode (user is viewing)
        if self.keep_visible:
            return False

        # Don't burn if there is no elapsed time (just shown)
        if not self.time_shown:
            return False
        
        # Burn after delay
        if time.time() - self.time_shown < self.burn_in_delay:
            return False
        
        return True

    def _update_textures(self):
        ui_scale = float(self.gui.ui_scale)

        scale_changed = (
            self.last_ui_scale is None or
            abs(self.last_ui_scale - ui_scale) > 1e-6
        )

        if not self.needs_burnin_update and not scale_changed:
            return

        self.last_ui_scale = ui_scale
        self.needs_burnin_update = False

        safe_w = int(self.gui.safe_w)
        text_max_width = int(self.gui.get_base_safe_region()[2])

        self.spacing = self.gui.scale_px(20, min_value=5)
        self.top_margin = self.gui.scale_px(60, min_value=5)
        self.title_album_gap = self.gui.scale_px(10, min_value=3)

        artist_album = " - ".join(part for part in (self.artist, self.album) if part)

        # Keep text proportional to the artwork's displayed height. The
        # ratios follow the actual artwork scale at other resolutions.
        artwork_display_h = max(
            1.0,
            float(self.gui.safe_h) * self.ARTWORK_HEIGHT_RATIO
        )
        track_font_size = max(
            1,
            int(round(artwork_display_h * self.TITLE_FONT_ARTWORK_PERCENT / 100.0))
        )
        artist_album_font_size = max(
            1,
            int(round(artwork_display_h * self.ALBUM_FONT_ARTWORK_PERCENT / 100.0))
        )
        font_scale = max(ui_scale, 1e-6)

        self.title_font = self.gui.get_font(
            family="LiberationSans-Bold"
        )

        self.album_font = self.gui.get_font(
            family="LiberationSans-Bold"
        )

        self.track_scroller = ScrollingText(
            [self.text],
            max_width=text_max_width,
            horizontal=True,
            font=self.title_font,
            font_size=track_font_size / font_scale,
            gui=self.gui,
            color=(1, 1, 1, 1),
            outline_color=(0, 0, 0, 1)
        )

        self.artist_album_scroller = None
        if artist_album:
            self.artist_album_scroller = ScrollingText(
                [artist_album],
                max_width=text_max_width,
                horizontal=True,
                font=self.album_font,
                font_size=artist_album_font_size / font_scale,
                gui=self.gui,
                color=(0.78, 0.78, 0.78, 1),
                outline_color=(0, 0, 0, 1),
                outline_width=self.gui.scale_px(1, min_value=1)
            )

        # Layout measurements
        if self.artist_album_scroller:
            self.album_calc_h = self.artist_album_scroller.get_total_height()
            self.album_calc_w = safe_w
        else:
            self.album_calc_h = 0.0
            self.album_calc_w = 0.0

        track_sig = (self.text, track_font_size, ui_scale)
        artist_album_sig = (artist_album, artist_album_font_size, ui_scale)

        if track_sig != self.last_track_signature:
            self.last_track_signature = track_sig

            if self.track_tex:
                try:
                    GL.glDeleteTextures([self.track_tex])
                except Exception:
                    pass

            if self.text:
                self.track_tex, self.track_w, self.track_h = self._create_text_texture(
                    self.text,
                    track_font_size,
                    safe_w
                )
            else:
                self.track_tex = None
                self.track_w = self.track_h = 0

        if artist_album_sig != self.last_artist_album_signature:
            self.last_artist_album_signature = artist_album_sig

            if self.artist_album_tex:
                try:
                    GL.glDeleteTextures([self.artist_album_tex])
                except Exception:
                    pass

            if artist_album:
                self.artist_album_tex, self.artist_album_w, self.artist_album_h = self._create_text_texture(
                    artist_album,
                    artist_album_font_size,
                    safe_w
                )
            else:
                self.artist_album_tex = None
                self.artist_album_w = self.artist_album_h = 0

        if self.album_art:
            self._create_album_art_texture(safe_w, int(self.gui.safe_h))

    def _create_text_texture(self, text, font_size, max_width, color=(255,255,255,255)):
        font_path = self.gui.discover_font_path("LiberationSans-Bold")
        log.info(f"Loading font for text texture: {font_path} at size {font_size}")
        font = ImageFont.truetype(font_path, font_size)

        dummy = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), text, font=font)

        text_w = min(max_width, bbox[2] - bbox[0])
        text_h = bbox[3] - bbox[1]

        img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), text, font=font, fill=color)

        data = np.array(img)

        tex_id = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)

        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)

        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGBA,
            img.width, img.height, 0,
            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE,
            data
        )

        return tex_id, img.width, img.height

    def _create_album_art_texture(self, safe_w, safe_h):
        if not self.album_art:
            self.album_ready = False
            return

        ui_scale = float(self.gui.ui_scale)

        scroller_h = self.track_scroller.get_total_height() if self.track_scroller else 0.0
        text_block_h = scroller_h + (
            self.title_album_gap + self.album_calc_h
            if self.artist_album_scroller else 0.0
        )
        available_h = safe_h - text_block_h - self.spacing

        max_art_h = max(128.0, available_h)
        min_art_h = 128.0

        orig_w, orig_h = self.album_art.width, self.album_art.height
        aspect_ratio = orig_w / orig_h if orig_h > 0 else 1.0

        log.debug(
            f"_create_album_art_texture() original: {orig_w}x{orig_h} | "
            f"available_h={available_h:.2f} | "
            f"min={min_art_h} max={max_art_h:.2f} ui_scale={ui_scale}"
        )

        # Determine target height
        target_h = min(orig_h, max_art_h)
        if target_h < min_art_h:
            target_h = min_art_h
        target_w = int(target_h * aspect_ratio)

        log.debug(
            f"_create_album_art_texture() target (pre-scale): {target_w}x{target_h}"
        )

        img = self.album_art.resize((target_w, int(target_h)), Image.LANCZOS)
        data = np.array(img.convert("RGBA"))

        if self.album_tex:
            try:
                GL.glDeleteTextures([self.album_tex])
            except Exception:
                log.warning("NowPlayingUI: glDeleteTextures failed (ignored)")

        tex_id = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, target_w, int(target_h), 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        self.album_tex = tex_id
        self.album_w = float(target_w)
        self.album_h = float(target_h)
        self.album_ready = True

        log.debug(
            f"_create_album_art_texture() stored: {self.album_w:.2f}x{self.album_h:.2f}"
        )

    def _perform_burn_in(self):
        if not self._should_burn_in():
            return
        
        io = imgui.get_io()
        screen_w, screen_h = int(io.display_size[0]), int(io.display_size[1])

        # Burn track text
        text_left = int(round((screen_w - self.track_w) / 2.0))
        text_top = int(round((screen_h - self.track_h) / 2.0))
        if self.track_tex:
            self.ui_ctrl.projectm.burn_in_texture(self.track_tex, text_left, text_top, int(self.track_w), int(self.track_h))

        # Burn artist-album text
        if self.artist_album_tex:
            artist_album_left = int(round((screen_w - self.artist_album_w) / 2.0))
            artist_album_top = int(text_top + self.track_h + self.spacing)
            self.ui_ctrl.projectm.burn_in_texture(self.artist_album_tex, artist_album_left, artist_album_top, int(self.artist_album_w), int(self.artist_album_h))

        # Burn album artwork
        if self.album_ready and self.album_tex:
            art_left = int(round((screen_w - self.album_w) / 2.0))
            art_top = int(text_top - self.album_h - self.spacing)
            self.ui_ctrl.projectm.burn_in_texture(self.album_tex, art_left, art_top, int(self.album_w), int(self.album_h))

        self.burned_in = True
        self.visible = False
        self.time_shown = None

    #endregion

    #region Public Helpers

    def display_track_info(self):
        self.visible = True
        self.burned_in = False
        self.time_shown = time.time()

    def set_track_info(self, title, artist=None, album=None, album_art=None):
        title = title or ""
        artist = artist or ""
        album = album or ""

        if title == self.text and artist == self.artist and album == self.album:
            return

        self.text = title
        self.artist = artist
        self.album = album
        self.album_art = album_art

        self.visible = True
        self.burned_in = False
        self.time_shown = time.time()
        self.track_scroller = None
        self.artist_album_scroller = None
        self.album_ready = False
        self.needs_burnin_update = True

        log.info(f"NowPlayingUI: artist='{artist}' title='{title}' album='{album}' artwork={album_art}")

    def clear_track_info(self):
        self.text = ""
        self.artist = ""
        self.album = ""
        self.album_art = None
        self.visible = False
        self.burned_in = False
        self.time_shown = None
        self.track_scroller = None
        self.artist_album_scroller = None
        self.album_ready = False

    #endregion

    #region Main Render Loop

    def render(self):
        self.gui.now_playing_artwork_bottom = None
        if not self._should_show_overlay():
            return

        io = imgui.get_io()
        screen_w, screen_h = int(io.display_size[0]), int(io.display_size[1])

        safe_x = self.gui.safe_x
        safe_y = self.gui.safe_y
        safe_w = self.gui.safe_w
        safe_h = self.gui.safe_h
        ui_scale = float(self.gui.ui_scale)
        cx = safe_x + safe_w / 2.0

        self._update_textures()

        scroller_h = self.track_scroller.get_total_height() if self.track_scroller else 0.0
        album_h = self.artist_album_scroller.get_total_height() if self.artist_album_scroller else 0.0
        text_block_h = scroller_h + (self.title_album_gap + album_h if self.artist_album_scroller else 0.0)

        art_x = art_y = art_w = art_h = None

        if self.album_ready and self.album_tex and self.album_h > 0:
            max_art_h = safe_h * self.ARTWORK_HEIGHT_RATIO
            aspect_ratio = self.album_w / self.album_h

            scale = max_art_h / self.album_h

            art_h = self.album_h * scale
            art_w = self.album_w * scale

            art_x = cx - art_w / 2.0
            art_y = safe_y + (safe_h - art_h) / 2.0
            self.gui.now_playing_artwork_bottom = art_y + art_h

            text_start_y = art_y - self.spacing - text_block_h
        else:
            text_start_y = safe_y + (safe_h - text_block_h) / 2.0

        # Draw track scroller (white)
        if self.track_scroller:
            scroller_h = self.track_scroller.get_total_height()
            track_bias = scroller_h * 0.50
            self.track_scroller.draw(cx, text_start_y + track_bias)

        # Draw artist-album scroller below the track (grey)
        if self.artist_album_scroller:
            album_text_y = text_start_y + scroller_h + self.title_album_gap + album_h * 0.5
            self.artist_album_scroller.draw(cx, album_text_y)

        if self.album_ready and self.album_tex:
            draw_list = imgui.get_background_draw_list()
            draw_list.add_image(
                imgui.ImTextureRef(self.album_tex),
                imgui.ImVec2(art_x, art_y),
                imgui.ImVec2(art_x + art_w, art_y + art_h),
                imgui.ImVec2(0, 0),
                imgui.ImVec2(1, 1),
                imgui.get_color_u32(imgui.ImVec4(1, 1, 1, 0.9))
            )

        self._perform_burn_in()

    #endregion