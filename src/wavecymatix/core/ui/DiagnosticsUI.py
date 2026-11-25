import logging
import os

from imgui_bundle import imgui

log = logging.getLogger()


class DiagnosticsUI:
    """
    Dedicated UI for performance diagnostics and metrics.
    Handles rendering FPS overlay, frame timing, and projectM performance data.
    """

    def __init__(self, gui_manager, ui_ctrl):
        self.gui_manager = gui_manager
        self.ui_ctrl = ui_ctrl
        
        # Visibility state
        self.visible = False
        
        # Current frame metrics
        self.frame_wall_time = 0.0
        self.swap_time = 0.0
        self.current_fps = 0.0
        
        # Fonts
        self.font = None

    def update_metrics(self, frame_wall_time: float, swap_time: float = 0.0):
        """
        Update frame timing metrics.
        
        Args:
            frame_wall_time: Time in seconds from render start to buffer swap
            swap_time: Time in seconds spent in buffer swap/present
        """
        self.frame_wall_time = frame_wall_time
        self.swap_time = swap_time
        self.current_fps = (1.0 / frame_wall_time) if frame_wall_time > 0 else 0.0

    def toggle(self):
        """Toggle diagnostics overlay visibility."""
        self.visible = not self.visible
        log.debug(f"Diagnostics overlay: {'SHOWN' if self.visible else 'HIDDEN'}")

    def _fmt_enabled_disabled(self, value):
        return "Enabled" if value else "Disabled"

    def _fmt_status(self, value):
        if value is None:
            return "N/A"
        return str(value).replace("_", " ").title()

    def _fmt_reason(self, value):
        if value is None:
            return "N/A"
        return str(value).replace("_", " ").title()

    def _fmt_ms(self, value):
        if value is None:
            return "N/A"
        return f"{float(value) * 1000.0:.1f}ms"

    def _fmt_s(self, value):
        if value is None:
            return "N/A"
        return f"{float(value):.2f}s"

    def _fmt_line(self, *pairs):
        parts = []
        for label, value in pairs:
            if value is None:
                continue
            parts.append(f"{label}: {value}")
        if parts:
            imgui.text("  ".join(parts))

    def _render_section_header(self, title):
        imgui.text(title)
        imgui.separator()

    def render(self):
        """Render the diagnostics overlay if visible."""
        if not self.visible:
            return

        try:
            self._render_performance_window()
        except Exception:
            log.exception("Failed to render diagnostics window")

    def _render_performance_window(self):
        """Render the main performance metrics window."""
        imgui.set_next_window_bg_alpha(self.gui_manager.window_background_alpha)

        flags = (
            imgui.WindowFlags_.no_resize |
            imgui.WindowFlags_.no_collapse |
            imgui.WindowFlags_.always_auto_resize
        )

        expanded, self.visible = self.gui_manager.begin_window(
            "Performance Diagnostics",
            closable=True,
            flags=flags
        )

        if not expanded:
            imgui.end()
            return

        self.font = self.gui_manager.get_font()
        if self.font:
            self.gui_manager.push_font(self.font, 16)

        # Active visual details
        snapshot = self.ui_ctrl.get_diagnostics_snapshot() if hasattr(self.ui_ctrl, "get_diagnostics_snapshot") else {}
        performance = snapshot.get("performance", {})
        fps_action = performance.get("last_action") if performance.get("last_action_reason") == "fps_below_tolerance" else "none"
        fps_trigger = performance.get("fps_status", "UNKNOWN")
        fps_response_reason = performance.get("last_action_reason") if fps_action != "none" else performance.get("last_suppressed_reason", "none")

        perf_action = performance.get("last_action") if performance.get("last_action_reason") == "perf_unstable" else "none"
        perf_trigger = performance.get("perf_status", "UNKNOWN")
        perf_response_reason = performance.get("last_action_reason") if perf_action != "none" else performance.get("last_suppressed_reason", "none")

        self._render_section_header("Frame Timing")
        imgui.text(f"Status: {self._fmt_status(performance.get('fps_status', 'UNKNOWN'))}")
        imgui.text(f"Enforcement: {self._fmt_enabled_disabled(performance.get('fps_policy_enabled', False))}")
        self._fmt_line(
            ("Current FPS", f"{self.current_fps:.1f}"),
            ("Frame Time", self._fmt_ms(self.frame_wall_time)),
            ("Swap Time", self._fmt_ms(self.swap_time)),
        )
        self._fmt_line(
            ("Tgt", f"{float(performance.get('fps_target', 0.0)):.1f}"),
            ("Tol", f"{float(performance.get('tolerance', 0.0)):.2f}"),
            ("Thr", f"{float(performance.get('threshold_fps', 0.0)):.1f}"),
        )
        self._fmt_line(
            ("Trigger", self._fmt_reason(fps_trigger)),
            ("Response", self._fmt_reason(fps_action)),
            ("Why", self._fmt_reason(fps_response_reason)),
        )

        self._render_section_header("Performance Detector")
        imgui.text(f"Status: {self._fmt_status(performance.get('perf_status', 'UNKNOWN'))}")
        imgui.text(f"Enforcement: {self._fmt_enabled_disabled(performance.get('perf_detection_enabled', False))}")
        self._fmt_line(
            ("Baseline", self._fmt_ms(performance.get("baseline"))),
            ("Deviation", self._fmt_ms(performance.get("deviation_accumulator"))),
            ("Long Frame", self._fmt_ms(performance.get("long_frame_accumulator"))),
            ("Swap Time", self._fmt_ms(performance.get("swap_time"))),
            ("Hits", performance.get("unstable_count")),
        )
        self._fmt_line(
            ("Win", performance.get("baseline_window")),
            ("Min", performance.get("min_samples")),
            ("DevTh", f"{float(performance.get('deviation_threshold', 0.0)):.2f}x"),
            ("LongTh", self._fmt_ms(performance.get("long_frame_threshold"))),
            ("SwTh", self._fmt_ms(performance.get("swap_stall_threshold"))),
            ("Cd", self._fmt_s(performance.get("trigger_cooldown"))),
            ("SettleS", self._fmt_s(performance.get("settle_time_soft"))),
            ("SettleH", self._fmt_s(performance.get("settle_time_hard"))),
        )
        self._fmt_line(
            ("Trigger", self._fmt_reason(perf_trigger)),
            ("Response", self._fmt_reason(perf_action)),
            ("Why", self._fmt_reason(perf_response_reason)),
        )

        visual_name = snapshot.get("visual_name", "None")
        visual = snapshot.get("visual", {})

        self._render_section_header("Active Visual")
        imgui.text(f"Current Visual Mode: {visual_name}")

        if visual:
            label = visual.get("label")
            value = visual.get("value")
            if label and value is not None:
                value_text = str(value)
                if "/" in value_text or "\\" in value_text:
                    value_text = os.path.basename(value_text)
                imgui.text(f"{label}: {value_text}")

            if "index" in visual and "count" in visual:
                imgui.text(f"Index: {visual['index']}/{visual['count']}")

            if "locked" in visual:
                imgui.text(f"Locked: {'Yes' if visual['locked'] else 'No'}")

            if "fps" in visual and visual["fps"] is not None:
                imgui.text(f"Source FPS: {visual['fps']:.2f}")

            if "decoder_running" in visual:
                imgui.text(f"Decoder: {'Running' if visual['decoder_running'] else 'Stopped'}")

            if "transitioning" in visual:
                imgui.text(f"Transitioning: {'Yes' if visual['transitioning'] else 'No'}")

            if snapshot.get("visual_mode") == "projectm":
                settings = visual.get("projectm_settings", {})
                if settings:
                    self._render_section_header("ProjectM Visual")
                    self._fmt_line(
                        ("FPS", f"{settings['render_fps']:.1f}/{settings['target_fps']:.1f}"),
                        ("Elapsed", self._fmt_s(settings["preset_elapsed"])),
                        ("Preset Duration", self._fmt_s(settings["preset_duration"])),
                    )
                    self._fmt_line(
                        ("Beat Sens", f"{settings['beat_sensitivity']:.2f}"),
                        ("Hard Cut", self._fmt_enabled_disabled(settings["hard_cut_enabled"])),
                        ("HC Min", self._fmt_s(settings["hard_cut_duration"])),
                        ("HC Sens", f"{settings['hard_cut_sensitivity']:.2f}"),
                    )
                    mesh_x, mesh_y = settings["mesh_size"]
                    self._fmt_line(
                        ("Shuffle", self._fmt_enabled_disabled(settings["shuffle"])),
                        ("Mesh", f"{mesh_x}x{mesh_y}"),
                        (
                            "Sprites",
                            f"{settings['sprite_count']}/{settings['sprite_limit']}"
                            if settings["sprite_count"] is not None
                            and settings["sprite_limit"] is not None
                            else None,
                        ),
                        (
                            "Playlist",
                            f"{settings['playlist_index'] + 1}/{settings['playlist_count']}"
                            if settings["playlist_count"]
                            else "Empty",
                        ),
                    )
                    width, height = settings["viewport_size"]
                    self._fmt_line(
                        ("Viewport", f"{width}x{height}"),
                        ("Aspect", self._fmt_enabled_disabled(settings["aspect_correction"])),
                    )

        if imgui.button("Close"):
            self.visible = False

        if self.font:
            imgui.pop_font()

        imgui.end()
