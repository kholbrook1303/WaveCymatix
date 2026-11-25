import time
import logging

from imgui_bundle import imgui

log = logging.getLogger(__name__)

class ScrollingText:
    def __init__(
        self,
        lines,
        max_width=None,
        horizontal=True,
        speed=60,
        mode="pingpong",
        font=None,
        font_size=16,
        gui=None,
        color=(1, 1, 1, 1),
        outline_color=(0, 0, 0, 1),
        outline_width=None,
    ):
        self.lines = lines
        self.max_width = max_width
        self.horizontal = horizontal
        self.speed = speed
        self.mode = mode
        self.font = font
        self.font_size = font_size
        self.gui = gui
        self.color = color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.scroll_offset = 0.0
        self.direction = 1
        self.last_time = time.time()

    def _text_size(self, text):
        if not text:
            return 0.0, 0.0

        self.gui.push_font(self.font, self.font_size)

        try:
            size = imgui.calc_text_size(text)
            return float(size.x), float(size.y)
        finally:
            imgui.pop_font()

    def update(self):
        now = time.perf_counter()
        dt = now - self.last_time
        self.last_time = now

        if not self.lines or not self.horizontal:
            return

        text_w, text_h = self._text_size(self.lines[0])
        visible_width = float(self.max_width if self.max_width is not None else text_w)

        if text_w <= visible_width:
            self.scroll_offset = 0.0
            self.direction = 1
            return

        max_offset = text_w - visible_width

        if self.mode == "pingpong":
            self.scroll_offset += self.direction * self.speed * dt
            if self.scroll_offset >= max_offset:
                self.scroll_offset = max_offset
                self.direction = -1
            elif self.scroll_offset <= 0:
                self.scroll_offset = 0
                self.direction = 1
        elif self.mode == "wrap":
            self.scroll_offset += self.speed * dt
            wrap_max = text_w + 50  # wrap padding
            if self.scroll_offset >= wrap_max:
                self.scroll_offset -= wrap_max

    def draw(self, cx, cy):
        if not self.lines or not self.horizontal:
            return

        self.update()

        draw_list = imgui.get_background_draw_list()
        line = self.lines[0]

        text_w, text_h = self._text_size(line)
        visible_width = float(self.max_width if self.max_width is not None else text_w)

        left_visible = cx - visible_width / 2.0
        y_top = cy - text_h / 2.0
        
        self.gui.push_font(self.font, self.font_size)

        try:
            draw_list.push_clip_rect(
                imgui.ImVec2(left_visible, y_top - text_h),
                imgui.ImVec2(left_visible + visible_width, y_top + text_h * 2),
                True
            )

            if text_w <= visible_width:
                x = cx - text_w / 2.0
                self.gui.draw_outlined_text(
                    draw_list, x, y_top, line,
                    color=self.color,
                    outline_color=self.outline_color,
                    outline_width=self.outline_width,
                    font=self.font,
                    font_size=self.font_size
                )
            else:
                x = left_visible - self.scroll_offset
                self.gui.draw_outlined_text(
                    draw_list, x, y_top, line,
                    color=self.color,
                    outline_color=self.outline_color,
                    outline_width=self.outline_width,
                    font=self.font,
                    font_size=self.font_size
                )

        finally:
            draw_list.pop_clip_rect()
            imgui.pop_font()

    def get_total_height(self):
        if not self.lines:
            return 0.0
        _, h = self._text_size(self.lines[0])
        return h