import logging
import sdl2
import signal
import time

log = logging.getLogger()

from wavecymatix.lib.common import get_environment

from wavecymatix.core.AudioCapture import AudioCapture
from wavecymatix.core.AudioLookup import AudioLookup
from wavecymatix.core.FPSLimiter import FPSLimiter
from wavecymatix.core.InputEventListener import EVDEV_INSTALLED, InputEventListener, SDLInputEventListener
from wavecymatix.core.PerformancePolicy import PerformancePolicy
from wavecymatix.core.SDLRenderingWindow import SDLRenderingWindow
from wavecymatix.core.UIController import UIController

from wavecymatix.core.monitors.Audio import Audio
from wavecymatix.core.monitors.Display import Display

from wavecymatix.core.plugins.Airplay import Airplay
from wavecymatix.core.plugins.Bluetooth import Bluetooth
from wavecymatix.core.plugins.Plexamp import Plexamp
from wavecymatix.core.plugins.Spotify import Spotify
from wavecymatix.core.plugins.VLC import VLC
from wavecymatix.core.plugins.WindowsMedia import WindowsMedia

from wavecymatix.core.ui.DiagnosticsUI import DiagnosticsUI
from wavecymatix.core.ui.ToolbarUI import ToolbarUI
from wavecymatix.core.ui.GuiManager import GuiManager
from wavecymatix.core.ui.MediaPlayerUI import MediaPlayerUI
from wavecymatix.core.ui.NowPlayingUI import NowPlayingUI

from wavecymatix.core.visual.ProjectM import ProjectM
from wavecymatix.core.visual.Slideshow import Slideshow
from wavecymatix.core.visual.VideoBackground import VideoBackground

class SignalMonitor:
    """Monitor for system signals to gracefully exit the application"""
    exit = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.set_exit)
        signal.signal(signal.SIGTERM, self.set_exit)

    def set_exit(self, signum, frame):
        self.exit = True

class RenderingLoop:
    ALL_MONITORS = [
        ('audio', Audio),
        ('display', Display),
    ]

    ALL_PLUGINS = [
        ('airplay', Airplay),
        ('bluetooth', Bluetooth),
        ('plexamp', Plexamp),
        ('spotify', Spotify),
        ('vlc', VLC),
        ('windows_media', WindowsMedia),
    ]

    MONITOR_REGISTRY = [(name, cls) for name, cls in ALL_MONITORS if cls.is_supported()]
    PLUGIN_REGISTRY = [(name, cls) for name, cls in ALL_PLUGINS if cls.is_supported()]

    def __init__(self, config, thread_event):
        self.config             = config
        self.thread_event       = thread_event
        self.environment        = get_environment()
        self.threads            = list()
        self.signal_event       = SignalMonitor()
        self.plugins            = list()
        self.monitors           = list()
        self.audio_lookup       = False

        if EVDEV_INSTALLED and self.environment == 'lite':
            self.input_event_lstn   = InputEventListener()

        self.performance_policy = PerformancePolicy(self.config)
        
        self.render_width       = None
        self.render_height      = None

        # Monitor registration
        for monitor_name, monitor_class in self.MONITOR_REGISTRY:
            enabled = self.config.monitors.get(monitor_name)
            if enabled:
                monitor = monitor_class(self.config)
                monitor.start()
                self.monitors.append(monitor)

        # SDL Rendering setup
        self.sdl_rendering      = SDLRenderingWindow(self.config)

        if not self.sdl_rendering.rendering_window or not self.sdl_rendering.gl_context:
            current_ctx = sdl2.SDL_GL_GetCurrentContext()
            sdl_err = sdl2.SDL_GetError()
            sdl_err = sdl_err.decode(errors='replace') if isinstance(sdl_err, bytes) else str(sdl_err)
            log.error(
                f"OpenGL context was not ready after SDLRenderingWindow init "
                f"(window={bool(self.sdl_rendering.rendering_window)} "
                f"context={bool(self.sdl_rendering.gl_context)} "
                f"current={bool(current_ctx)} sdl_error='{sdl_err}')"
            )
            raise RuntimeError("SDL/OpenGL initialization failed before GUI startup")

        self.gui_manager        = GuiManager(
            self.sdl_rendering.rendering_window,
            self.config.ui.get('ui_scale_factor', 1.0),
            getattr(self.config, 'ui', {}),
        )
        
        # Visual components
        self.projectm           = ProjectM(self.config, self.sdl_rendering)
        self.slideshow          = Slideshow(self.gui_manager, self.config)
        self.video_background   = VideoBackground(self.gui_manager, self.config)

        # State manager to coordinate between components
        self.ui_ctrl            = UIController(self.config, self.sdl_rendering, self.plugins)

        if EVDEV_INSTALLED and self.environment == 'lite':
            self.input_event_lstn.set_sdl_window(self.sdl_rendering.rendering_window)

        # UI components
        self.diagnostics_ui     = DiagnosticsUI(self.gui_manager, self.ui_ctrl)
        self.now_playing        = NowPlayingUI(self.gui_manager, self.ui_ctrl)
        self.media_ui           = MediaPlayerUI(self.gui_manager, self.ui_ctrl)
        self.toolbar_ui         = ToolbarUI(self.gui_manager, self.thread_event, self.ui_ctrl)

        # SDL Input listener setup
        self.sdl_input_listener = SDLInputEventListener(self.config, self.thread_event, self.ui_ctrl, self.gui_manager)

        # Inject components into state manager for cross-component communication
        self.ui_ctrl.projectm = self.projectm
        self.ui_ctrl.video_background = self.video_background
        self.ui_ctrl.slideshow_ui = self.slideshow
        self.ui_ctrl.now_playing = self.now_playing
        self.ui_ctrl.media_ui = self.media_ui
        self.ui_ctrl.toolbar_ui = self.toolbar_ui
        self.ui_ctrl.diagnostics_ui = self.diagnostics_ui
        self.ui_ctrl.set_performance_policy_snapshot({
            "mode": "none",
            "state": "INIT",
            "last_action": "none",
            "last_action_reason": "none",
            "last_suppressed_reason": "none",
        })
        
        # Expose now_playing to gui_manager for other uses
        self.gui_manager.now_playing = self.now_playing

        # Audio capture setup
        self.audio_capture = AudioCapture(self.config, self.projectm)
        self.sdl_input_listener.audio_capture = self.audio_capture

        # Start audio lookup feature
        if self.config.audio_lookup.get('enabled', False):
            self.audio_lookup = AudioLookup(
                self.thread_event, 
                self.config, 
                self.audio_capture, 
                self.now_playing,
                lookup_gate=lambda: not self.ui_ctrl.is_audio_active()
                )
            self.audio_lookup.start()

            # expose audio lookup to state for lookup requests
            self.ui_ctrl.audio_lookup = self.audio_lookup

        # Plugin registration
        for plugin_name, plugin_class in self.PLUGIN_REGISTRY:
            enabled = self.config.plugins.get(plugin_name)
            plugin = plugin_class(self.config, self.now_playing)
            if enabled:
                plugin.start()
            self.plugins.append(plugin)

        self.ui_ctrl.plugins = self.plugins
        self.media_ui.plugins = self.plugins
        self.toolbar_ui.plugins = self.plugins

        # Set default visual mode on startup
        if self.ui_ctrl.visuals_enabled:
            self.ui_ctrl.set_visual_mode(self.ui_ctrl.default_visual_mode)
        else:
            self.ui_ctrl.set_visual_mode("none")

    def close(self):
        if self.config.audio_lookup.get('enabled', False):
            self.audio_lookup.join()
            self.audio_lookup.close()

        for monitor in self.monitors:
            monitor.stop()

        for plugin in self.plugins:
            plugin.stop()

    def run(self):
        limiter = FPSLimiter()

        if EVDEV_INSTALLED and self.environment == 'lite':
            # Start evdev input thread
            self.input_event_lstn.start_evdev_listener()

        if self.ui_ctrl.now_playing_persistent:
            self.ui_ctrl.toggle_now_playing_persistence()

        if self.ui_ctrl.media_ui_persistent:
            self.ui_ctrl.toggle_media_controls_persistence()

        # Start projectM
        self.projectm.display_initial_preset()

        while not (self.thread_event.is_set() or self.signal_event.exit):
            limiter.target_fps(self.config.projectm.get('projectm.fps', 60))
            limiter.start_frame();

            # Process SDL events before beginning a new ImGui frame so key-mod
            # state is coherent for the frame render pass.
            self.sdl_input_listener.poll_events()

            # Keep software cursor visibility aligned with app cursor state.
            self.gui_manager.set_cursor_visible(self.ui_ctrl.mouse_visible())

            self.gui_manager.new_frame()
            self.check_viewport_size()

            # measure wall-clock for render + swap to capture swap/driver stalls
            frame_start = time.perf_counter()

            self.audio_capture.fill_buffer()
            
            self.gui_manager.clear_frame()

            # Render projectM frame if active
            if self.projectm.visible:
                self.projectm.render_frame()

            try:
                self.gui_manager.update_layout()

                if self.ui_ctrl.visuals_enabled:
                    self.video_background.render()
                    self.slideshow.render()

                if self.ui_ctrl.now_playing_enabled:
                    with self.gui_manager.ui_element_scale(
                        self.config.ui.get('now_playing_ui_scale_factor', 1.0)
                    ):
                        self.now_playing.render()

                if self.ui_ctrl.media_ui_enabled:
                    with self.gui_manager.ui_element_scale(
                        self.config.ui.get('media_ui_scale_factor', 1.0)
                    ):
                        self.media_ui.render()

                if self.ui_ctrl.toolbar_ui_enabled:
                    with self.gui_manager.ui_element_scale(
                        self.config.ui.get('toolbar_ui_scale_factor', 1.0)
                    ):
                        self.toolbar_ui.render()

                if self.ui_ctrl.diagnostics_ui_enabled:
                    with self.gui_manager.ui_element_scale(
                        self.config.ui.get('diagnostics_ui_scale_factor', 1.0)
                    ):
                        self.diagnostics_ui.render()

                self.gui_manager.render()
            except:
                log.exception('UI rendering failed!')

            # perform buffer swap and include it in timing
            swap_start = time.perf_counter()
            self.sdl_rendering.swap()
            frame_end = time.perf_counter()

            swap_time = frame_end - swap_start
            frame_wall_time = frame_end - frame_start

            # Always update diagnostics timing so benchmarking is independent of enforcement switches.
            self.diagnostics_ui.update_metrics(frame_wall_time, swap_time)

            visual_mode = self.ui_ctrl.get_visual_mode()
            if visual_mode == "projectm" and hasattr(self.projectm, "consume_transition_event"):
                transition_event = self.projectm.consume_transition_event()
                if transition_event:
                    self.performance_policy.on_visual_transition(
                        "projectm",
                        is_hard=bool(transition_event.get("is_hard", False)),
                    )

            if self.ui_ctrl.visuals_enabled and visual_mode != "none":
                mode_label = "N/A"
                if visual_mode == "projectm" and hasattr(self.projectm, "get_current_preset"):
                    mode_label = self.projectm.get_current_preset() or "N/A"
                elif visual_mode == "slideshow" and hasattr(self.slideshow, "get_current_visual_item"):
                    mode_label = self.slideshow.get_current_visual_item() or "N/A"
                elif visual_mode == "video_background" and hasattr(self.video_background, "get_current_visual_item"):
                    mode_label = self.video_background.get_current_visual_item() or "N/A"

                policy_snapshot = self.performance_policy.evaluate(
                    mode=visual_mode,
                    mode_label=mode_label,
                    frame_wall_time=frame_wall_time,
                    swap_time=swap_time,
                    locked=self.ui_ctrl.get_visual_locked(),
                )

                if policy_snapshot.get("last_action") == "advance_visual":
                    self.ui_ctrl.next_visual()
                    log.warning(
                        "[%s] performance policy action=advance_visual reason=%s state=%s",
                        mode_label,
                        policy_snapshot.get("last_action_reason", "unknown"),
                        policy_snapshot.get("state", "unknown"),
                    )
                elif policy_snapshot.get("last_action") == "delete_visual":
                    self.ui_ctrl.delete_visual()
                    log.warning(
                        "[%s] performance policy action=delete_visual reason=%s state=%s",
                        mode_label,
                        policy_snapshot.get("last_action_reason", "unknown"),
                        policy_snapshot.get("state", "unknown"),
                    )

                self.ui_ctrl.set_performance_policy_snapshot(policy_snapshot)
            else:
                self.ui_ctrl.set_performance_policy_snapshot(
                    {
                        "mode": "none",
                        "state": "INACTIVE",
                        "last_action": "none",
                        "last_action_reason": "none",
                        "last_suppressed_reason": "none",
                    }
                )

            # Hide UI elements after mouse inactivity
            if self.ui_ctrl.mouse_visible() and (time.time() - self.sdl_input_listener.last_mouse_motion_time > self.sdl_input_listener.mouse_inactivity_delay):
                media_ui = self.ui_ctrl.media_ui
                if media_ui and (media_ui.playlist_popup or media_ui.visual_playlist_popup):
                    pass
                else:
                    self.ui_ctrl.hide_ui_elements(persistent=False)
                    
            limiter.end_frame();

            self.projectm.update_real_fps(limiter.fps())

        if self.signal_event.exit:
            self.thread_event.set()

        for instance_id,controller in self.sdl_input_listener.controller_inputs.items():
            try:
                sdl2.SDL_GameControllerClose(controller)
            except Exception as e:
                log.error(f'Error closing controller: {e}')

        self.audio_capture.close()
        self.projectm.close()
        self.sdl_rendering.close()

    def check_viewport_size(self):
        renderWidth, renderHeight = self.sdl_rendering.get_drawable_size()
        if (renderWidth != self.render_width or renderHeight != self.render_height):
            self.render_width = renderWidth
            self.render_height = renderHeight