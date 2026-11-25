import ctypes
import logging
import os
import sdl2

from OpenGL import GL

from wavecymatix.lib.config import APP_ROOT
from wavecymatix.lib.common import get_environment

log = logging.getLogger()

class SDLRenderingWindow:
    def __init__(self, config):
        self.config = config
        self.rendering_window = None
        self.gl_context = None

        self.fullscreen_active = False
        self.last_window_width = ctypes.c_int()
        self.last_window_height = ctypes.c_int()

        self.mouse_visible = False

        self.use_gles = False
        self.use_glew = False

        if os.name == "nt":
            dpi_hint = sdl2.SDL_HINT_WINDOWS_DPI_AWARENESS
            if not sdl2.SDL_SetHint(dpi_hint, b"permonitorv2"):
                log.warning(
                    "Could not enable per-monitor-v2 DPI awareness through SDL: %s",
                    sdl2.SDL_GetError(),
                )

        self.verify_opengl_features()

        self.create_sdl_window()

    def close(self):
        log.info('Destroying SDL rendering window')
        self.destroy_sdl_window()

    def verify_opengl_features(self):
        sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    
        window = sdl2.SDL_CreateWindow(
            b"Open GL Version/Extension Check", 
            sdl2.SDL_WINDOWPOS_CENTERED, 
            sdl2.SDL_WINDOWPOS_CENTERED, 
            800, 
            600, 
            sdl2.SDL_WINDOW_OPENGL
            )

        context = sdl2.SDL_GL_CreateContext(window)

        if os.name == "nt":
            self.use_glew = True

        gl_version = GL.glGetString(GL.GL_VERSION)
        if b"ES" in gl_version:
            self.use_gles = True

        sdl2.SDL_GL_DeleteContext(context)
        sdl2.SDL_DestroyWindow(window)
        sdl2.SDL_Quit()

    def get_drawable_size(self):
        w = ctypes.c_int()
        h = ctypes.c_int()
        sdl2.SDL_GL_GetDrawableSize(self.rendering_window, w, h)
        return w.value, h.value

    def swap(self):
        sdl2.SDL_GL_SwapWindow(self.rendering_window)

    def toggle_fullscreen(self):
        if get_environment() != 'lite':
            if self.fullscreen_active:
                self.windowed()
            else:
                self.fullscreen()

    def fullscreen(self):
        sdl2.SDL_GetWindowSize(
            self.rendering_window,
            self.last_window_width,
            self.last_window_height
        )
        fullscreen_width = self.config.projectm.get(
            'window.fullscreen.width', 1280)
        fullscreen_height = self.config.projectm.get(
            'window.fullscreen.height', 720)

        fullscreen_exclusive_mode = self.config.projectm.get(
            'window.fullscreen.exclusivemode', False
            )

        if get_environment() == 'lite' or fullscreen_exclusive_mode:
            if fullscreen_width > 0 and fullscreen_height > 0:
                sdl2.SDL_RestoreWindow(self.rendering_window)
                self._set_exclusive_display_mode(
                    fullscreen_width, fullscreen_height)
            result = sdl2.SDL_SetWindowFullscreen(
                self.rendering_window,
                sdl2.SDL_WINDOW_FULLSCREEN
            )
            if result != 0:
                log.error(
                    f"Exclusive fullscreen failed: {sdl2.SDL_GetError()}")
        else:
            result = sdl2.SDL_SetWindowFullscreen(
                self.rendering_window,
                sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP
            )
            if result != 0:
                log.error(
                    f"Desktop fullscreen failed: {sdl2.SDL_GetError()}")
        self.fullscreen_active = True
        self.fullscreen_active = True

    def _set_exclusive_display_mode(self, width, height):
        # SDL_SetWindowSize is ignored in exclusive fullscreen; the mode
        # must be set via SDL_SetWindowDisplayMode before going fullscreen.
        index = sdl2.SDL_GetWindowDisplayIndex(self.rendering_window)
        if index < 0:
            index = 0

        current = sdl2.SDL_DisplayMode()
        sdl2.SDL_GetCurrentDisplayMode(index, current)

        wanted = sdl2.SDL_DisplayMode()
        wanted.format = 0
        wanted.w = width
        wanted.h = height
        wanted.refresh_rate = current.refresh_rate
        closest = sdl2.SDL_DisplayMode()
        if not sdl2.SDL_GetClosestDisplayMode(index, wanted, closest):
            log.warning(
                f"No display mode near {width}x{height}: "
                f"{sdl2.SDL_GetError()}")
            return

        if sdl2.SDL_SetWindowDisplayMode(
            self.rendering_window, closest
        ) != 0:
            log.error(f"SDL_SetWindowDisplayMode failed: {sdl2.SDL_GetError()}")

    def windowed(self):
        sdl2.SDL_SetWindowFullscreen(self.rendering_window, 0)
        sdl2.SDL_SetWindowBordered(
            self.rendering_window,
            sdl2.SDL_FALSE
            if self.config.projectm.get('window.borderless', False)
            else sdl2.SDL_TRUE
        )

        width = self.last_window_width.value
        height = self.last_window_height.value

        if width > 0 and height > 0:
            sdl2.SDL_SetWindowSize(
                self.rendering_window, width, height)
            self.show_cursor(visible=True)

        self.fullscreen_active = False

    def show_cursor(self, visible=False):
        if get_environment() != 'lite':
            sdl2.SDL_ShowCursor(visible)
        self.mouse_visible = visible

    def set_sdl_window_title(self, title):
        sdl2.SDL_SetWindowTitle(self.rendering_window, title)

    def is_gles_context(self):
        profile = ctypes.c_int()
        sdl2.SDL_GL_GetAttribute(
            sdl2.SDL_GL_CONTEXT_PROFILE_MASK, ctypes.byref(profile)
        )
        return profile.value == sdl2.SDL_GL_CONTEXT_PROFILE_ES

    def _compute_window_geometry(self):
        width = self.config.projectm.get('window.width', 800)
        height = self.config.projectm.get('window.height', 600)
        left = self.config.projectm.get('window.left', 0)
        top = self.config.projectm.get('window.top', 0)
        positionOverridden = self.config.projectm.get(
            'window.overrideposition', False)

        if not positionOverridden:
            left = sdl2.SDL_WINDOWPOS_UNDEFINED
            top = sdl2.SDL_WINDOWPOS_UNDEFINED

        display = self.config.projectm.get('window.monitor', 0)
        if display > 0:
            numDisplays = sdl2.SDL_GetNumVideoDisplays()
            if display > numDisplays:
                display = numDisplays

            bounds = sdl2.SDL_Rect()
            sdl2.SDL_GetDisplayBounds(display - 1, bounds)

            if positionOverridden:
                left += bounds.x
                top += bounds.y
            else:
                left = bounds.x
                top = bounds.y

        return left, top, width, height

    def create_sdl_window(self):
        def sdl_error_text():
            err = sdl2.SDL_GetError()
            if isinstance(err, bytes):
                return err.decode(errors='replace')
            return str(err)

        if sdl2.SDL_Init(
            sdl2.SDL_INIT_VIDEO |
            sdl2.SDL_INIT_GAMECONTROLLER |
            sdl2.SDL_INIT_JOYSTICK
        ):
            log.error(f"SDL_Init failed: {sdl_error_text()}")
            return

        width = self.config.projectm.get('window.width', 800)
        height = self.config.projectm.get('window.height', 600)
        left = self.config.projectm.get('window.left', 0)
        top = self.config.projectm.get('window.top', 0)
        positionOverridden = self.config.projectm.get(
            'window.overrideposition', False)

        if not positionOverridden:
            left = sdl2.SDL_WINDOWPOS_UNDEFINED
            top = sdl2.SDL_WINDOWPOS_UNDEFINED

        display = self.config.projectm.get('window.monitor', 0)
        if display > 0:
            numDisplays = sdl2.SDL_GetNumVideoDisplays()
            if display > numDisplays:
                display = numDisplays

            bounds = sdl2.SDL_Rect()
            sdl2.SDL_GetDisplayBounds(display - 1, bounds)

            if positionOverridden:
                left += bounds.x
                top += bounds.y
            else:
                left = bounds.x
                top = bounds.y

        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(
            sdl2.SDL_GL_CONTEXT_PROFILE_MASK,
            sdl2.SDL_GL_CONTEXT_PROFILE_CORE,
        )

        self.rendering_window = sdl2.SDL_CreateWindow(
            b"WaveCymatix Python SDL2",
            left, top, width, height,
            sdl2.SDL_WINDOW_OPENGL |
            sdl2.SDL_WINDOW_RESIZABLE |
            sdl2.SDL_WINDOW_ALLOW_HIGHDPI
        )
        if not self.rendering_window:
            log.error(f"SDL_CreateWindow failed: {sdl_error_text()}")
            sdl2.SDL_Quit()
            return

        self.gl_context = sdl2.SDL_GL_CreateContext(self.rendering_window)
        if not self.gl_context:
            log.error(f"SDL_GL_CreateContext failed: {sdl_error_text()}")
            sdl2.SDL_DestroyWindow(self.rendering_window)
            sdl2.SDL_Quit()
            return

        self.set_sdl_window_title(b"projectM")
        if sdl2.SDL_GL_MakeCurrent(self.rendering_window, self.gl_context) != 0:
            log.error(f"SDL_GL_MakeCurrent failed: {sdl_error_text()}")
            sdl2.SDL_GL_DeleteContext(self.gl_context)
            sdl2.SDL_DestroyWindow(self.rendering_window)
            self.gl_context = None
            self.rendering_window = None
            sdl2.SDL_Quit()
            return

        log.info("GL_VENDOR   : %s", GL.glGetString(GL.GL_VENDOR).decode())
        log.info("GL_RENDERER : %s", GL.glGetString(GL.GL_RENDERER).decode())
        log.info("GL_VERSION  : %s", GL.glGetString(GL.GL_VERSION).decode())
        log.info("GLSL        : %s", GL.glGetString(GL.GL_SHADING_LANGUAGE_VERSION).decode())

        self.update_swap_interval()

        if self.use_glew:
            glew_dll = os.path.join(APP_ROOT, 'runtime', 'artifacts', 'glew32.dll')
            glewInit = ctypes.CDLL(glew_dll).glewInit
            glewInit.restype = ctypes.c_uint
            if glewInit() != 0:
                print("glewInit failed")
                return -1

        sdl2.SDL_StartTextInput()

        if get_environment() == 'lite' or self.config.projectm.get(
            'window.fullscreen', False):
            self.fullscreen()
        else:
            self.windowed()

    def destroy_sdl_window(self):
        sdl2.SDL_StopTextInput()
        sdl2.SDL_GL_DeleteContext(self.gl_context)
        sdl2.SDL_DestroyWindow(self.rendering_window)
        self.rendering_window = None
        sdl2.SDL_QuitSubSystem(
            sdl2.SDL_INIT_VIDEO |
            sdl2.SDL_INIT_GAMECONTROLLER |
            sdl2.SDL_INIT_JOYSTICK
        )

    def update_swap_interval(self):
        if self.config.projectm.get(
            'window.waitforverticalsync', True):
            sdl2.SDL_GL_SetSwapInterval(0)
            return

        if self.config.projectm.get(
            'window.adaptiveverticalsync', True):
            if sdl2.SDL_GL_SetSwapInterval(-1) == 0:
                return
