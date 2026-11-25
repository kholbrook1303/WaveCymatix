import asyncio
import ctypes
import logging
import math
import threading
import time

import sdl2

log = logging.getLogger()

EVDEV_INSTALLED = False
try:
    import evdev
    EVDEV_INSTALLED = True
except ImportError:
    log.warning('evdev is not installed and therefore will not be used!')

CONTROLLER_DEADZONE         = 10000 # adjust as needed (range is -32768 to 32767)

SWIPE_MIN_DISTANCE          = 0.04  # normalized units (~4% screen)
SWIPE_MAX_TIME              = 0.8   # seconds
SWIPE_DIRECTION_BIAS        = 1.3
TWO_FINGER_TAP_MAX_TIME     = 0.3

PINCH_MIN_SHRINK_RATIO      = 0.2   # 20% shrink required
PINCH_MIN_DISTANCE          = 0.05  # ignore tiny starting pinches

VERTICAL_ACTIVE_MIN         = 0.2   # top 20% ignored
VERTICAL_ACTIVE_MAX         = 0.8   # bottom 20% ignored

LEFT_REGION_MAX             = 0.3
RIGHT_REGION_MIN            = 0.7

class SDLInputEventListener:
    def __init__(self, config, thread_event, ui_ctrl, gui_manager=None):
        self.config                     = config
        self.thread_event               = thread_event
        self.ui_ctrl                    = ui_ctrl
        self.gui_manager                = gui_manager

        self.active_fingers             = {}
        self.input_digits               = ""
        self.input_down_catalog         = set()
        self.input_down_time_catalog    = {}
        self.last_mouse_motion_time     = time.time()
        self.mouse_inactivity_delay     = 4.0
        self.controller_inputs          = dict()
        self.last_mouse_x              = 0
        self.last_mouse_y              = 0
        self.have_mouse_position       = False

        self.controller_axis_states = {
            sdl2.SDL_CONTROLLER_AXIS_LEFTX: 'NEUTRAL',
            sdl2.SDL_CONTROLLER_AXIS_LEFTY: 'NEUTRAL',
            sdl2.SDL_CONTROLLER_AXIS_RIGHTX: 'NEUTRAL',
            sdl2.SDL_CONTROLLER_AXIS_RIGHTY: 'NEUTRAL',
            sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT: 'NEUTRAL',
            sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT: 'NEUTRAL',
        }
        
        for i in range(sdl2.SDL_NumJoysticks()):
            if sdl2.SDL_IsGameController(i):
                controller = sdl2.SDL_GameControllerOpen(i)
                if controller:
                    if not any (controller == c for c in self.controller_inputs.values()):
                        instance_id = sdl2.SDL_JoystickInstanceID(sdl2.SDL_GameControllerGetJoystick(controller))
                        self.controller_inputs[instance_id] = controller
                        log.debug(f"Controller {instance_id} connected: {sdl2.SDL_GameControllerName(controller).decode()}")

        self.sprite_logo = self.config.projectm.get("projectm.spritelogo", False)

    """Simulate a keypress
    @param sdl_key: the key to emit
    """
    def simulate_keypress(self, sdl_key):
        try:
            sdl_event = sdl2.SDL_Event()
            sdl_event.type = sdl2.SDL_KEYDOWN
            sdl_event.key.type = sdl2.SDL_KEYDOWN
            sdl_event.key.state = sdl2.SDL_PRESSED
            sdl_event.key.repeat = 0
            sdl_event.key.keysym.sym = sdl_key
            sdl_event.key.keysym.scancode = sdl2.SDL_GetScancodeFromKey(sdl2.SDL_KEYDOWN)
            sdl_event.key.keysym.mod = 0x00

            sdl2.SDL_PushEvent(sdl_event)
        except:
            log.exception('failed to process sdl event!')

    def in_active_vertical_region(self, y):
        return VERTICAL_ACTIVE_MIN <= y <= VERTICAL_ACTIVE_MAX

    def rotate_coords(self, x, y, rotation):
        rotation %= 360
        if rotation == 90:
            return y, 1.0 - x
        if rotation == 180:
            return 1.0 - x, 1.0 - y
        if rotation == 270:
            return 1.0 - y, x
        return x, y
            
    def key_event(self, event, key_down):
        key = event.key.keysym.sym
        key_modifier = event.key.keysym.mod
        modifier_pressed = (key_modifier & sdl2.KMOD_LCTRL) or (key_modifier & sdl2.KMOD_RCTRL)

        current_time = time.time()
        if self.input_digits and current_time - self.last_digit_time > 3:
            self.input_digits = ""

        if key_down:
            match key:
                case sdl2.SDLK_F1:
                    self.ui_ctrl.toggle_help()

                case sdl2.SDLK_d:
                    self.ui_ctrl.toggle_diagnostics()

                case sdl2.SDLK_f:
                    if modifier_pressed:
                        self.ui_ctrl.toggle_fullscreen()
                    else:
                        self.ui_ctrl.toggle_current_visual_favorite()

                case sdl2.SDLK_i:
                    if modifier_pressed:
                        self.audio_capture.next_audio_device()

                case sdl2.SDLK_k:
                    if modifier_pressed:
                        self.ui_ctrl.kill_sprites()

                case sdl2.SDLK_l | sdl2.SDLK_AC_HOME:
                    if self.sprite_logo:
                        for spriteIdx in self.sprite_logo.split(','):
                            self.ui_ctrl.handle_sprite(spriteIdx)

                case sdl2.SDLK_m:
                    if modifier_pressed:
                        self.ui_ctrl.toggle_media_controls_persistence()

                case sdl2.SDLK_n | sdl2.SDLK_RIGHT:
                    self.ui_ctrl.next_visual()
                    log.debug('User has requested the next visual')

                case sdl2.SDLK_p:
                    if modifier_pressed:
                        self.ui_ctrl.toggle_now_playing_persistence()
                    else:
                        self.ui_ctrl.previous_visual()

                case sdl2.SDLK_q:
                    if modifier_pressed:
                        log.info('User initiated exit!')
                        self.thread_event.set()

                case sdl2.SDLK_t | sdl2.SDLK_APPLICATION:
                    log.debug(f'User has requested track info display.')
                    if (not self.ui_ctrl.is_audio_active()) and self.config.audio_lookup.get('enabled', False):
                        self.ui_ctrl.clear_track_info()
                        try:
                            self.ui_ctrl.request_audio_lookup()
                        except Exception:
                            log.exception('Failed to request audio lookup via state')
                    else:
                        self.ui_ctrl.display_track_info()

                case sdl2.SDLK_v:
                    if modifier_pressed:
                        if self.ui_ctrl.visual_mode and not self.ui_ctrl.get_visuals_enabled(self.ui_ctrl.visual_mode):
                            self.ui_ctrl.set_visual_mode(self.ui_ctrl.visual_mode)
                        else:
                            self.ui_ctrl.set_visual_mode("none")

                case sdl2.SDLK_y:
                    if modifier_pressed:
                        self.ui_ctrl.toggle_presets_shuffle()

                case sdl2.SDLK_LEFT | sdl2.SDLK_AC_BACK:
                    log.debug('User has requested the next preset')
                    self.ui_ctrl.previous_visual()

                case sdl2.SDLK_n | sdl2.SDLK_RIGHT:
                    self.ui_ctrl.next_visual()
                    log.debug('User has requested the next visual')

                case sdl2.SDLK_AUDIONEXT:
                    self.ui_ctrl.next_track()

                case sdl2.SDLK_AUDIOPREV:
                    self.ui_ctrl.previous_track()

                case sdl2.SDLK_AUDIOSTOP:
                    pass

                case sdl2.SDLK_AUDIOPLAY:
                    self.ui_ctrl.toggle_playback()

                case sdl2.SDLK_DELETE:
                    self.ui_ctrl.delete_visual(physical=True)

                case sdl2.SDLK_SPACE:
                    self.ui_ctrl.toggle_visual_lock()
            
                case sdl2.SDLK_ESCAPE:
                    if self.ui_ctrl.toolbar_ui.help_visible:
                        self.ui_ctrl.toggle_help()
                    elif self.ui_ctrl.media_ui.sprite_popup:
                        self.ui_ctrl.media_ui.sprite_popup = False
                    elif self.ui_ctrl.media_ui.playlist_popup:
                        self.ui_ctrl.media_ui.playlist_popup = False
                    elif self.ui_ctrl.media_ui.visual_playlist_popup:
                        self.ui_ctrl.media_ui.visual_playlist_popup = False
                    elif self.ui_ctrl.media_ui.visual_playlist_create_popup:
                        self.ui_ctrl.media_ui.visual_playlist_create_popup = False
                        self.ui_ctrl.media_ui.pending_visual_playlist_name = ""
                    else:
                        self.ui_ctrl.toggle_fullscreen()

                case sdl2.SDLK_PAGEUP:
                    pass

                case sdl2.SDLK_PAGEDOWN:
                    pass
            
                case sdl2.SDLK_UP:
                    self.ui_ctrl.change_beat_sensitivity(0.1)

                case sdl2.SDLK_DOWN:
                    self.ui_ctrl.change_beat_sensitivity(-0.1)

                case key if sdl2.SDLK_0 <= key <= sdl2.SDLK_9:
                    digit = chr(key)
                    self.input_digits += digit
                    self.last_digit_time = current_time

                    log.debug(f"Digit entered: {digit}, current input: {self.input_digits}")

                    if len(self.input_digits) == 2:
                        log.debug(f"User entered sprite number: {self.input_digits}")
                        self.ui_ctrl.handle_sprite(self.input_digits)
                        self.input_digits = ""

                case _:
                    log.warning(f'unhandled key {key} ({hex(key)}) down={key_down}')
                    pass

    def controller_axis_event(self, event):
        axis = event.caxis.axis
        value = event.caxis.value

        prev_state = self.controller_axis_states.get(axis, 'NEUTRAL')
        state = 'NEUTRAL'

        # Determine direction based on axis
        if axis in (sdl2.SDL_CONTROLLER_AXIS_LEFTX, sdl2.SDL_CONTROLLER_AXIS_RIGHTX):
            if value < -CONTROLLER_DEADZONE:
                state = 'LEFT'
            elif value > CONTROLLER_DEADZONE:
                state = 'RIGHT'

        elif axis in (sdl2.SDL_CONTROLLER_AXIS_LEFTY, sdl2.SDL_CONTROLLER_AXIS_RIGHTY):
            if value < -CONTROLLER_DEADZONE:
                state = 'UP'
            elif value > CONTROLLER_DEADZONE:
                state = 'DOWN'

        elif axis == sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT:
            if value > CONTROLLER_DEADZONE:
                state = 'PRESSED'

        elif axis == sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT:
            if value > CONTROLLER_DEADZONE:
                state = 'PRESSED'

        # Only trigger action if state changes
        if state != prev_state:
            self.controller_axis_states[axis] = state

            match (axis, state):
                case (sdl2.SDL_CONTROLLER_AXIS_LEFTX, 'LEFT') | (sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT, 'PRESSED'):
                    self.ui_ctrl.previous_visual()
                    log.debug('User has requested the previous preset')

                case (sdl2.SDL_CONTROLLER_AXIS_LEFTX, 'RIGHT') | (sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT, 'PRESSED'):
                    self.ui_ctrl.next_visual()
                    log.debug('User has requested the next visual')

                case (sdl2.SDL_CONTROLLER_AXIS_LEFTY, 'UP'):
                    self.ui_ctrl.change_beat_sensitivity(0.1)

                case (sdl2.SDL_CONTROLLER_AXIS_LEFTY, 'DOWN'):
                    self.ui_ctrl.change_beat_sensitivity(-0.1)

                case _:
                    log.debug(f"Unhandled controller axis {hex(axis)} state {state}")


    def controller_button_event(self, event, button_down):
        button = event.cbutton.button

        if button_down:
            self.input_down_catalog.add(button)
            self.input_down_time_catalog[button] = time.time()

            if (sdl2.SDL_CONTROLLER_BUTTON_BACK in self.input_down_catalog and
                sdl2.SDL_CONTROLLER_BUTTON_B in self.input_down_catalog):
                self.ui_ctrl.delete_visual(physical=True)

            match button:
                case sdl2.SDL_CONTROLLER_BUTTON_LEFTSTICK | sdl2.SDL_CONTROLLER_BUTTON_RIGHTSTICK:
                    self.ui_ctrl.toggle_visual_lock()

                case sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP:
                    self.ui_ctrl.change_beat_sensitivity(0.1)

                case sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN:
                    self.ui_ctrl.change_beat_sensitivity(-0.1)

                case sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT:
                    self.ui_ctrl.previous_visual()
                    log.debug('User has requested the previous preset')

                case sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT:
                    self.ui_ctrl.next_visual()
                    log.debug('User has requested the next visual')

                case sdl2.SDL_CONTROLLER_BUTTON_GUIDE:
                    if self.sprite_logo:
                        for spriteIdx in self.sprite_logo.split(','):
                            self.ui_ctrl.handle_sprite(spriteIdx)

                case sdl2.SDL_CONTROLLER_BUTTON_BACK:
                    pass

                case sdl2.SDL_CONTROLLER_BUTTON_START:
                    pass

                case sdl2.SDL_CONTROLLER_BUTTON_A:
                    pass

                case sdl2.SDL_CONTROLLER_BUTTON_B:
                    pass

                case sdl2.SDL_CONTROLLER_BUTTON_X:
                    pass

                case sdl2.SDL_CONTROLLER_BUTTON_Y:
                    pass

                case _:
                    log.warning(f'unhandled controller button {button} ({hex(button)})')
                    pass
        else:
            self.input_down_catalog.discard(button)
            press_time = self.input_down_time_catalog.pop(button, None)
            if press_time is not None:
                held_duration = time.time() - press_time
                if held_duration >= 3.0:

                    if button == sdl2.SDL_CONTROLLER_BUTTON_GUIDE:
                        log.debug('User initiated guide hold mode')

    def mouse_event(self, event):
        self.last_mouse_motion_time = time.time()

        match event.type:
            case sdl2.SDL_MOUSEWHEEL:
                if self.ui_ctrl.media_ui.sprite_popup and hasattr(self.ui_ctrl.media_ui, 'sprite_box') and self.ui_ctrl.media_ui.sprite_box:
                    self.ui_ctrl.media_ui.sprite_box.scroll(event.wheel.y)

            case sdl2.SDL_MOUSEMOTION:
                x, y = event.motion.x, event.motion.y
                self.last_mouse_x = int(x)
                self.last_mouse_y = int(y)
                self.have_mouse_position = True

                if self.gui_manager:
                    self.gui_manager.set_mouse_position(x, y)

                if event.motion.which != sdl2.SDL_TOUCH_MOUSEID:
                    if not self.ui_ctrl.mouse_visible():
                        self.ui_ctrl.show_cursor(True)

                    self.ui_ctrl.show_ui_elements(persist=False)

                    if self.ui_ctrl.toolbar_ui_enabled:
                        self.ui_ctrl.toolbar_ui.update_visibility(y)

            case sdl2.SDL_MOUSEBUTTONDOWN:
                x, y = event.button.x, event.button.y
                self.last_mouse_x = int(x)
                self.last_mouse_y = int(y)
                self.have_mouse_position = True

                if self.gui_manager:
                    self.gui_manager.set_mouse_position(x, y)

                if event.button.button == sdl2.SDL_BUTTON_LEFT:
                    pass
                elif event.button.button == sdl2.SDL_BUTTON_RIGHT:
                    self.ui_ctrl.toggle_fullscreen()

            case sdl2.SDL_MOUSEBUTTONUP:
                x, y = event.button.x, event.button.y
                self.last_mouse_x = int(x)
                self.last_mouse_y = int(y)
                self.have_mouse_position = True

            case _:
                pass

    def _track_mouse_state(self, event):
        # Keep software cursor position and inactivity timer current even
        # when ImGui captures mouse events.
        self.last_mouse_motion_time = time.time()

        if event.type == sdl2.SDL_MOUSEMOTION:
            x, y = event.motion.x, event.motion.y
        elif event.type in (sdl2.SDL_MOUSEBUTTONDOWN, sdl2.SDL_MOUSEBUTTONUP):
            x, y = event.button.x, event.button.y
        else:
            x, y = self.last_mouse_x, self.last_mouse_y

        self.last_mouse_x = int(x)
        self.last_mouse_y = int(y)
        self.have_mouse_position = True

        if self.gui_manager:
            self.gui_manager.set_mouse_position(self.last_mouse_x, self.last_mouse_y)

    def get_mouse_position(self):
        return self.last_mouse_x, self.last_mouse_y, self.have_mouse_position

    def touch_event(self, event):
        if not hasattr(self, "active_fingers"):
            self.active_fingers = {}
        if not hasattr(self, "gesture_max_fingers"):
            self.gesture_max_fingers = 0

        match event.type:
            case sdl2.SDL_FINGERDOWN:

                rotation = int(self.config.general.get('touch_rotation_degrees', 0))
                x, y = self.rotate_coords(event.tfinger.x, event.tfinger.y, rotation)

                self.active_fingers[event.tfinger.fingerId] = {
                    "start_x": x,
                    "start_y": y,
                    "last_x": x,
                    "last_y": y,
                    "start_time": time.monotonic(),
                }

                self.gesture_max_fingers = max(
                    self.gesture_max_fingers,
                    len(self.active_fingers)
                )

                # If exactly 2 fingers → record pinch start distance
                if len(self.active_fingers) == 2:
                    fingers = list(self.active_fingers.values())
                    dx = fingers[0]["start_x"] - fingers[1]["start_x"]
                    dy = fingers[0]["start_y"] - fingers[1]["start_y"]
                    self.pinch_start_distance = math.hypot(dx, dy)

            case sdl2.SDL_FINGERMOTION:

                finger = self.active_fingers.get(event.tfinger.fingerId)
                if not finger:
                    return

                rotation = int(self.config.general.get('touch.rotation_degrees', 0))
                x, y = self.rotate_coords(event.tfinger.x, event.tfinger.y, rotation)

                finger["last_x"] = x
                finger["last_y"] = y

                # Track live pinch distance if 2 fingers active
                if len(self.active_fingers) == 2:
                    fingers = list(self.active_fingers.values())
                    self.pinch_last_positions = [
                        (fingers[0]["last_x"], fingers[0]["last_y"]),
                        (fingers[1]["last_x"], fingers[1]["last_y"]),
                    ]

            case sdl2.SDL_FINGERUP:

                finger = self.active_fingers.get(event.tfinger.fingerId)
                if not finger:
                    return

                rotation = int(self.config.general.get('touch.rotation_degrees', 0))
                x, y = self.rotate_coords(event.tfinger.x, event.tfinger.y, rotation)

                finger["last_x"] = x
                finger["last_y"] = y

                now = time.monotonic()
                duration = now - finger["start_time"]

                completed = finger
                self.active_fingers.pop(event.tfinger.fingerId)

                dx = completed["last_x"] - completed["start_x"]
                dy = completed["last_y"] - completed["start_y"]

                abs_dx = abs(dx)
                abs_dy = abs(dy)

                # Only evaluate when all fingers lifted
                if self.active_fingers:
                    return

                # Pinch gestures (must be 2 fingers, time limit, and significant distance change)
                if (
                    self.gesture_max_fingers == 2
                    and duration <= SWIPE_MAX_TIME
                    and hasattr(self, "pinch_start_distance")
                    and hasattr(self, "pinch_last_positions")
                ):
                    if self.pinch_start_distance > PINCH_MIN_DISTANCE:
                        (x1, y1), (x2, y2) = self.pinch_last_positions
                        pinch_end = math.hypot(x1 - x2, y1 - y2)

                        delta_ratio = (
                            pinch_end - self.pinch_start_distance
                        ) / self.pinch_start_distance

                        # Pinch in (shrink)
                        if delta_ratio <= -PINCH_MIN_SHRINK_RATIO:
                            log.info("Pinch in → hiding UI")
                            self.ui_ctrl.hide_ui_elements(persistent=True)

                            self.gesture_max_fingers = 0
                            del self.pinch_start_distance
                            del self.pinch_last_positions
                            return

                        # Pinch out (expand)
                        if delta_ratio >= PINCH_MIN_SHRINK_RATIO:
                            log.info("Pinch out → showing UI")
                            
                            self.ui_ctrl.show_ui_elements(persist=True)

                            self.gesture_max_fingers = 0
                            del self.pinch_start_distance
                            del self.pinch_last_positions
                            return

                # 2 finger tap (must be 2 fingers, time limit, and minimal movement)
                if (
                    self.gesture_max_fingers == 2
                    and duration <= TWO_FINGER_TAP_MAX_TIME
                    and abs_dx < SWIPE_MIN_DISTANCE
                    and abs_dy < SWIPE_MIN_DISTANCE
                ):
                    log.info("Two-finger tap → toggle visual lock")
                    self.ui_ctrl.toggle_visual_lock()
                    self.gesture_max_fingers = 0
                    return

                # Horizontal swipe (must be primarily horizontal, time limit, and significant distance)
                if (
                    abs_dx >= SWIPE_MIN_DISTANCE
                    and abs_dx > abs_dy * SWIPE_DIRECTION_BIAS
                    and duration <= SWIPE_MAX_TIME
                ):
                    if dx > 0:
                        log.info("Swipe right → previous preset")
                        self.ui_ctrl.previous_visual()
                    else:
                        log.info("Swipe left → next visual")
                        self.ui_ctrl.next_visual()

                    self.gesture_max_fingers = 0
                    return

                # Vertical swipe gestures (must be primarily vertical, time limit, and significant distance)
                # Vertical swipe gestures (relaxed detection first)
                if duration <= SWIPE_MAX_TIME and abs_dy >= SWIPE_MIN_DISTANCE:

                    start_y = completed["start_y"]
                    in_bottom_region = start_y >= 0.75
                    in_top_region = start_y <= 0.05

                    # Normalize direction first
                    is_up = dy < 0
                    is_down = dy > 0

                    # Bottom UI
                    if in_bottom_region:

                        # open
                        if is_up and not self.ui_ctrl.media_ui.visible:
                            log.info("Swipe up from bottom → open UI")
                            self.ui_ctrl.show_ui_elements(persist=True)

                            self.gesture_max_fingers = 0
                            return

                        # close
                        if is_down and self.ui_ctrl.media_ui.visible:
                            log.info("Swipe down from bottom → close UI")
                            self.ui_ctrl.hide_ui_elements(persistent=True)
                            self.gesture_max_fingers = 0
                            return

                    # Top UI
                    if in_top_region:

                        if is_down and not self.ui_ctrl.toolbar_ui.visible:
                            log.info("Swipe down from top → open toolbar")
                            self.ui_ctrl.toolbar_ui.visible = True
                            self.gesture_max_fingers = 0
                            return

                    # Close fallback
                    if is_up and self.ui_ctrl.toolbar_ui.visible:
                        log.info("Swipe up → close toolbar")
                        self.ui_ctrl.toolbar_ui.visible = False
                        self.gesture_max_fingers = 0
                        return

                # Single tap on left/right region (must be primarily stationary, time limit, and start in left/right region)
                if (
                    abs_dx < SWIPE_MIN_DISTANCE
                    and abs_dy < SWIPE_MIN_DISTANCE
                    and duration <= TWO_FINGER_TAP_MAX_TIME
                ):
                    if completed["start_x"] <= LEFT_REGION_MAX:
                        log.info("Tap left → previous preset")
                        self.ui_ctrl.previous_visual()
                    elif completed["start_x"] >= RIGHT_REGION_MIN:
                        log.info("Tap right → next visual")
                        self.ui_ctrl.next_visual()

                self.gesture_max_fingers = 0

            case _:
                pass

    def window_event(self, event):
        match event.window.event:
            case sdl2.SDL_WINDOWEVENT_CLOSE:
                self.thread_event.set()

            case sdl2.SDL_WINDOWEVENT_RESIZED | sdl2.SDL_WINDOWEVENT_SIZE_CHANGED:
                w, h = event.window.data1, event.window.data2
                self.ui_ctrl.set_window_size(w, h)

            case sdl2.SDL_WINDOWEVENT_HIDDEN | sdl2.SDL_WINDOWEVENT_MINIMIZED:
                log.debug('Restoring the window!')
                sdl2.SDL_RestoreWindow(self.ui_ctrl.get_sdl_rendiering_window())
                sdl2.SDL_ShowWindow(self.ui_ctrl.get_sdl_rendiering_window())

            case sdl2.SDL_WINDOWEVENT_FOCUS_LOST:
                log.warning("Window lost focus")

            case sdl2.SDL_WINDOWEVENT_FOCUS_GAINED:
                log.debug("Window regained focus")

            case _:
                pass

    def controller_added_event(self, event):
        device_index = event.cdevice.which
        if sdl2.SDL_IsGameController(device_index):
            controller = sdl2.SDL_GameControllerOpen(device_index)
            if controller:
                instance_id = sdl2.SDL_JoystickInstanceID(sdl2.SDL_GameControllerGetJoystick(controller))
                self.controller_inputs[instance_id] = controller
                log.debug(f"Controller added: {device_index} (instance {instance_id})")

    def controller_removed_event(self, event):
        instance_id = event.cdevice.which
        controller = self.controller_inputs.get(instance_id)
        if controller:
            sdl2.SDL_GameControllerClose(controller)
            log.debug(f"Controller removed: instance {instance_id}")
            del self.controller_inputs[instance_id]

    def poll_events(self):
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type in (
                sdl2.SDL_MOUSEWHEEL,
                sdl2.SDL_MOUSEMOTION,
                sdl2.SDL_MOUSEBUTTONDOWN,
                sdl2.SDL_MOUSEBUTTONUP,
            ):
                self._track_mouse_state(event)

            if self.gui_manager:
                self.gui_manager.process_event(event)

                # Let ImGui own keyboard/mouse events while interacting with widgets.
                if event.type in (sdl2.SDL_KEYDOWN, sdl2.SDL_KEYUP):
                    if self.gui_manager.wants_keyboard_capture() and event.key.keysym.sym != sdl2.SDLK_ESCAPE:
                        continue

                if event.type in (
                    sdl2.SDL_MOUSEWHEEL,
                    sdl2.SDL_MOUSEMOTION,
                    sdl2.SDL_MOUSEBUTTONDOWN,
                    sdl2.SDL_MOUSEBUTTONUP,
                ):
                    if self.gui_manager.wants_mouse_capture():
                        continue

            match event.type:
                case sdl2.SDL_QUIT:
                    self.thread_event.set()
                    break

                case sdl2.SDL_KEYDOWN:
                    self.key_event(event, True)

                case sdl2.SDL_KEYUP:
                    self.key_event(event, False)

                case sdl2.SDL_CONTROLLERDEVICEADDED:
                    self.controller_added_event(event)

                case sdl2.SDL_CONTROLLERDEVICEREMOVED:
                    self.controller_removed_event(event)

                case sdl2.SDL_CONTROLLERAXISMOTION:
                    self.controller_axis_event(event)

                case sdl2.SDL_CONTROLLERBUTTONDOWN:
                    self.controller_button_event(event, True)

                case sdl2.SDL_CONTROLLERBUTTONUP:
                    self.controller_button_event(event, False)

                case sdl2.SDL_MOUSEWHEEL | sdl2.SDL_MOUSEMOTION | \
                     sdl2.SDL_MOUSEBUTTONDOWN | sdl2.SDL_MOUSEBUTTONUP:
                    self.mouse_event(event)

                case sdl2.SDL_WINDOWEVENT:
                    self.window_event(event)

                case sdl2.SDL_FINGERDOWN:
                    self.touch_event(event)

                case sdl2.SDL_FINGERMOTION:
                    self.touch_event(event)

                case sdl2.SDL_FINGERUP:
                    self.touch_event(event)

                case _:
                    pass


class InputEventListener:
    def __init__(self):
        self.pressed_modifiers = set()  # global modifier state
        self.devices = []  # list of evdev.InputDevice
        self.pointer_devices = []
        self.keymap = self.generate_keymap()
        self.modmap = {
            evdev.ecodes.KEY_LEFTCTRL: sdl2.KMOD_LCTRL,
            evdev.ecodes.KEY_RIGHTCTRL: sdl2.KMOD_RCTRL,
            evdev.ecodes.KEY_LEFTSHIFT: sdl2.KMOD_LSHIFT,
            evdev.ecodes.KEY_RIGHTSHIFT: sdl2.KMOD_RSHIFT,
            evdev.ecodes.KEY_LEFTALT: sdl2.KMOD_LALT,
            evdev.ecodes.KEY_RIGHTALT: sdl2.KMOD_RALT,
            evdev.ecodes.KEY_LEFTMETA: sdl2.KMOD_LGUI,
            evdev.ecodes.KEY_RIGHTMETA: sdl2.KMOD_RGUI,
        }

        self.loop = None
        self.thread = None
        self.stop_event = threading.Event()

        self.sdl_window = None
        self.pointer_x = 0
        self.pointer_y = 0

    def set_sdl_window(self, sdl_window):
        self.sdl_window = sdl_window

    def _get_window_size(self):
        width = ctypes.c_int(1280)
        height = ctypes.c_int(720)

        if self.sdl_window:
            sdl2.SDL_GetWindowSize(self.sdl_window, width, height)
            if width.value > 0 and height.value > 0:
                return width.value, height.value

        rect = sdl2.SDL_Rect()
        if sdl2.SDL_GetDisplayBounds(0, rect) == 0 and rect.w > 0 and rect.h > 0:
            return int(rect.w), int(rect.h)

        return 1280, 720

    def _clamp_pointer(self, x, y):
        width, height = self._get_window_size()
        x = max(0, min(int(x), width - 1))
        y = max(0, min(int(y), height - 1))
        return x, y

    def _push_mouse_motion(self, x, y, xrel=0, yrel=0):
        event = sdl2.SDL_Event()
        event.type = sdl2.SDL_MOUSEMOTION
        event.motion.type = sdl2.SDL_MOUSEMOTION
        event.motion.which = 0
        event.motion.state = 0
        event.motion.x = int(x)
        event.motion.y = int(y)
        event.motion.xrel = int(xrel)
        event.motion.yrel = int(yrel)
        sdl2.SDL_PushEvent(event)

    def _push_mouse_button(self, sdl_button, pressed):
        event = sdl2.SDL_Event()
        event.type = sdl2.SDL_MOUSEBUTTONDOWN if pressed else sdl2.SDL_MOUSEBUTTONUP
        event.button.type = event.type
        event.button.which = 0
        event.button.button = sdl_button
        event.button.state = sdl2.SDL_PRESSED if pressed else sdl2.SDL_RELEASED
        event.button.clicks = 1
        event.button.x = int(self.pointer_x)
        event.button.y = int(self.pointer_y)
        sdl2.SDL_PushEvent(event)

    def generate_keymap(self):
        """Auto-generate an evdev to SDL keymap using key names."""
        keymap = {}
        for code, name in evdev.ecodes.keys.items():
            if not isinstance(name, str):
                continue
            if not name.startswith('KEY_'):
                continue
            keyname = name[4:].lower()
            sdl_key = sdl2.SDL_GetKeyFromName(keyname.encode())
            if sdl_key != sdl2.SDLK_UNKNOWN:
                keymap[code] = sdl_key
        return keymap

    def get_keyboard_devices(self):
        """Return all connected keyboard devices."""
        devices = []
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            if "keyboard" in dev.name.lower():
                devices.append(dev)
        return devices

    def get_pointer_devices(self):
        """Return all connected pointer devices (mouse/touchpad/touchscreen)."""
        devices = []
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            caps = dev.capabilities(verbose=False)

            has_rel_motion = (
                evdev.ecodes.EV_REL in caps and
                evdev.ecodes.REL_X in caps.get(evdev.ecodes.EV_REL, []) and
                evdev.ecodes.REL_Y in caps.get(evdev.ecodes.EV_REL, [])
            )

            has_abs_motion = (
                evdev.ecodes.EV_ABS in caps and
                evdev.ecodes.ABS_X in caps.get(evdev.ecodes.EV_ABS, []) and
                evdev.ecodes.ABS_Y in caps.get(evdev.ecodes.EV_ABS, [])
            )

            key_codes = set(caps.get(evdev.ecodes.EV_KEY, []))
            has_mouse_button = any(
                code in key_codes
                for code in (evdev.ecodes.BTN_LEFT, evdev.ecodes.BTN_RIGHT, evdev.ecodes.BTN_MIDDLE)
            )

            if has_mouse_button and (has_rel_motion or has_abs_motion):
                devices.append(dev)

        return devices

    def start_evdev_listener(self):
        """Start async loop for all detected keyboard devices."""
        if self.thread and self.thread.is_alive():
            log.warning("Listener already running")
            return

        self.devices = self.get_keyboard_devices()
        self.pointer_devices = self.get_pointer_devices()

        if not self.devices and not self.pointer_devices:
            log.warning("No keyboard or pointer devices found via evdev")
            return

        # Seed pointer center so first click has stable coordinates.
        width, height = self._get_window_size()
        self.pointer_x = width // 2
        self.pointer_y = height // 2

        self.stop_event.clear()

        async def reader_tasks():
            keyboard_tasks = [self.evdev_reader(dev) for dev in self.devices]
            pointer_tasks = [self.evdev_pointer_reader(dev) for dev in self.pointer_devices]
            await asyncio.gather(*(keyboard_tasks + pointer_tasks))

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(reader_tasks())

        log.info(
            f"Listening to {len(self.devices)} keyboards and {len(self.pointer_devices)} pointers via evdev"
        )
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    async def evdev_pointer_reader(self, device):
        """Read pointer events from a single device and inject SDL mouse events."""
        rel_x = 0
        rel_y = 0
        abs_x = None
        abs_y = None

        abs_x_info = device.absinfo(evdev.ecodes.ABS_X) if evdev.ecodes.EV_ABS in device.capabilities() and evdev.ecodes.ABS_X in device.capabilities().get(evdev.ecodes.EV_ABS, []) else None
        abs_y_info = device.absinfo(evdev.ecodes.ABS_Y) if evdev.ecodes.EV_ABS in device.capabilities() and evdev.ecodes.ABS_Y in device.capabilities().get(evdev.ecodes.EV_ABS, []) else None

        try:
            async for event in device.async_read_loop():
                if self.stop_event.is_set():
                    break

                if event.type == evdev.ecodes.EV_REL:
                    if event.code == evdev.ecodes.REL_X:
                        rel_x += int(event.value)
                    elif event.code == evdev.ecodes.REL_Y:
                        rel_y += int(event.value)

                elif event.type == evdev.ecodes.EV_ABS:
                    if event.code == evdev.ecodes.ABS_X:
                        abs_x = int(event.value)
                    elif event.code == evdev.ecodes.ABS_Y:
                        abs_y = int(event.value)

                elif event.type == evdev.ecodes.EV_KEY:
                    if event.code == evdev.ecodes.BTN_LEFT:
                        self._push_mouse_button(sdl2.SDL_BUTTON_LEFT, event.value == 1)
                    elif event.code == evdev.ecodes.BTN_RIGHT:
                        self._push_mouse_button(sdl2.SDL_BUTTON_RIGHT, event.value == 1)
                    elif event.code == evdev.ecodes.BTN_MIDDLE:
                        self._push_mouse_button(sdl2.SDL_BUTTON_MIDDLE, event.value == 1)

                elif event.type == evdev.ecodes.EV_SYN and event.code == evdev.ecodes.SYN_REPORT:
                    moved = False
                    xrel = 0
                    yrel = 0

                    if rel_x != 0 or rel_y != 0:
                        self.pointer_x += rel_x
                        self.pointer_y += rel_y
                        xrel = rel_x
                        yrel = rel_y
                        rel_x = 0
                        rel_y = 0
                        moved = True

                    if abs_x is not None and abs_y is not None and abs_x_info and abs_y_info:
                        width, height = self._get_window_size()

                        x_min = abs_x_info.min
                        x_max = abs_x_info.max
                        y_min = abs_y_info.min
                        y_max = abs_y_info.max

                        if x_max > x_min and y_max > y_min:
                            mapped_x = (abs_x - x_min) * (width - 1) / (x_max - x_min)
                            mapped_y = (abs_y - y_min) * (height - 1) / (y_max - y_min)
                            xrel = int(mapped_x - self.pointer_x)
                            yrel = int(mapped_y - self.pointer_y)
                            self.pointer_x = mapped_x
                            self.pointer_y = mapped_y
                            moved = True

                    if moved:
                        self.pointer_x, self.pointer_y = self._clamp_pointer(self.pointer_x, self.pointer_y)
                        self._push_mouse_motion(self.pointer_x, self.pointer_y, xrel, yrel)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                device.close()
            except Exception:
                pass
            log.debug(f"Evdev pointer reader for {device.name} stopped")

    async def evdev_reader(self, device):
        """Read events from a single device."""
        try:
            async for event in device.async_read_loop():
                if self.stop_event.is_set():
                    break
                if event.type != evdev.ecodes.EV_KEY:
                    continue

                key_event = evdev.categorize(event)
                key_code = key_event.scancode
                key_state = key_event.keystate  # 0=up, 1=down

                # Track modifiers
                if key_code in self.modmap:
                    mod = self.modmap[key_code]
                    if key_state == 1:
                        self.pressed_modifiers.add(mod)
                    else:
                        self.pressed_modifiers.discard(mod)
                    continue  # skip sending modifiers as SDL events

                sdl_key = self.keymap.get(key_code)
                if not sdl_key:
                    continue

                sdl_type = sdl2.SDL_KEYDOWN if key_state else sdl2.SDL_KEYUP
                mod_state = 0
                for mod in self.pressed_modifiers:
                    mod_state |= mod

                sdl_event = sdl2.SDL_Event()
                sdl_event.type = sdl_type
                sdl_event.key.type = sdl_type
                sdl_event.key.state = sdl2.SDL_PRESSED if key_state else sdl2.SDL_RELEASED
                sdl_event.key.repeat = 0
                sdl_event.key.keysym.sym = sdl_key
                sdl_event.key.keysym.scancode = sdl2.SDL_GetScancodeFromKey(sdl_key)
                sdl_event.key.keysym.mod = mod_state

                sdl2.SDL_PushEvent(sdl_event)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                device.close()
            except Exception:
                pass
            log.debug(f"Evdev reader for {device.name} stopped")

    def close(self):
        """Stop all devices and the async loop cleanly."""
        log.info("Stopping evdev listener")
        if not self.loop:
            return

        self.stop_event.set()

        # Cancel all tasks
        def stop_loop():
            for task in asyncio.all_tasks(self.loop):
                task.cancel()
            self.loop.stop()

        self.loop.call_soon_threadsafe(stop_loop)

        if self.thread:
            self.thread.join()

        for device in self.devices:
            try:
                device.close()
            except Exception:
                pass

        for device in self.pointer_devices:
            try:
                device.close()
            except Exception:
                pass

        log.info("Evdev listener fully stopped")