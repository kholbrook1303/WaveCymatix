import asyncio
import ctypes
import logging
import os

EVDEV_INSTALLED = False
try:
    import pyudev
    EVDEV_INSTALLED = True
except ImportError:
    EVDEV_INSTALLED = False

import shutil

from wavecymatix.lib.abstracts import AsyncService
from wavecymatix.lib.common import execute_managed, load_library, get_environment

log = logging.getLogger()

class drmModeModeInfo(ctypes.Structure):
    _fields_ = [
        ("clock", ctypes.c_uint32),
        ("hdisplay", ctypes.c_uint16),
        ("hsync_start", ctypes.c_uint16),
        ("hsync_end", ctypes.c_uint16),
        ("htotal", ctypes.c_uint16),
        ("hskew", ctypes.c_uint16),
        ("vdisplay", ctypes.c_uint16),
        ("vsync_start", ctypes.c_uint16),
        ("vsync_end", ctypes.c_uint16),
        ("vtotal", ctypes.c_uint16),
        ("vscan", ctypes.c_uint16),
        ("vrefresh", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
    ]

class drmModeConnector(ctypes.Structure):
    DRM_MODE_FLAG_INTERLACE = 0x10

    DRM_MODE_CONNECTED = 1
    DRM_MODE_DISCONNECTED = 2
    DRM_MODE_UNKNOWNCONNECTION = 3

    DRM_MODE_CONNECTOR_Unknown = 0
    DRM_MODE_CONNECTOR_VGA = 1
    DRM_MODE_CONNECTOR_DVII = 2
    DRM_MODE_CONNECTOR_DVID = 3
    DRM_MODE_CONNECTOR_DVIA = 4
    DRM_MODE_CONNECTOR_Composite = 5
    DRM_MODE_CONNECTOR_SVIDEO = 6
    DRM_MODE_CONNECTOR_LVDS = 7
    DRM_MODE_CONNECTOR_Component = 8
    DRM_MODE_CONNECTOR_9PinDIN = 9
    DRM_MODE_CONNECTOR_DisplayPort = 10
    DRM_MODE_CONNECTOR_HDMIA = 11
    DRM_MODE_CONNECTOR_HDMIB = 12
    DRM_MODE_CONNECTOR_TV = 13
    DRM_MODE_CONNECTOR_eDP = 14
    DRM_MODE_CONNECTOR_VIRTUAL = 15
    DRM_MODE_CONNECTOR_DSI = 16
    DRM_MODE_CONNECTOR_DPI = 17
    DRM_MODE_CONNECTOR_WRITEBACK = 18
    DRM_MODE_CONNECTOR_SPI = 19

    _fields_ = [
        ("connector_id", ctypes.c_uint32),
        ("encoder_id", ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection", ctypes.c_int),
        ("mmWidth", ctypes.c_uint32),
        ("mmHeight", ctypes.c_uint32),
        ("subpixel", ctypes.c_int),
        ("count_modes", ctypes.c_int),
        ("modes", ctypes.POINTER(drmModeModeInfo)),
        ("count_props", ctypes.c_int),
        ("props", ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders", ctypes.c_int),
        ("encoders", ctypes.POINTER(ctypes.c_uint32)),
    ]

class drmModeRes(ctypes.Structure):
    _fields_ = [
        ("count_fbs", ctypes.c_int),
        ("fbs", ctypes.POINTER(ctypes.c_uint32)),
        ("count_crtcs", ctypes.c_int),
        ("crtcs", ctypes.POINTER(ctypes.c_uint32)),
        ("count_connectors", ctypes.c_int),
        ("connectors", ctypes.POINTER(ctypes.c_uint32)),
        ("count_encoders", ctypes.c_int),
        ("encoders", ctypes.POINTER(ctypes.c_uint32)),
        ("min_width", ctypes.c_int),
        ("max_width", ctypes.c_int),
        ("min_height", ctypes.c_int),
        ("max_height", ctypes.c_int),
    ]

class drmModeEncoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id", ctypes.c_uint32),
        ("encoder_type", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]

class drmModeCrtc(ctypes.Structure):
    _fields_ = [
        ("crtc_id", ctypes.c_uint32),
        ("buffer_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("mode_valid", ctypes.c_int),
        ("mode", drmModeModeInfo),
        ("gamma_size", ctypes.c_int),
    ]


class Display(AsyncService):
    """Display monitor and control for X11 and Wayland display devices"""

    SUPPORTED_PLATFORMS = {"linux"}

    @classmethod
    def is_supported(cls):
        return super().is_supported() and EVDEV_INSTALLED

    def __init__(self, config):
        super().__init__()
        self._config = config

        self._running = False

        self.resolution     = '{}x{}'.format(
            self._config.projectm.get('window.fullscreen.width', 1280),
            self._config.projectm.get('window.fullscreen.height', 720)
            )

        self.libdrm = load_library('drm')

        self.libdrm.drmModeGetResources.argtypes = [ctypes.c_int]
        self.libdrm.drmModeGetResources.restype = ctypes.POINTER(drmModeRes)

        self.libdrm.drmModeFreeResources.argtypes = [ctypes.POINTER(drmModeRes)]
        self.libdrm.drmModeFreeResources.restype = None

        self.libdrm.drmModeGetConnector.argtypes = [ctypes.c_int, ctypes.c_uint32]
        self.libdrm.drmModeGetConnector.restype = ctypes.POINTER(drmModeConnector)

        self.libdrm.drmModeFreeConnector.argtypes = [ctypes.POINTER(drmModeConnector)]
        self.libdrm.drmModeFreeConnector.restype = None

        self.libdrm.drmModeGetEncoder.argtypes = [ctypes.c_int, ctypes.c_uint32]
        self.libdrm.drmModeGetEncoder.restype = ctypes.POINTER(drmModeEncoder)

        self.libdrm.drmModeFreeEncoder.argtypes = [ctypes.POINTER(drmModeEncoder)]
        self.libdrm.drmModeFreeEncoder.restype = None

        self.libdrm.drmModeGetCrtc.argtypes = [ctypes.c_int, ctypes.c_uint32]
        self.libdrm.drmModeGetCrtc.restype = ctypes.POINTER(drmModeCrtc)

        self.libdrm.drmModeFreeCrtc.argtypes = [ctypes.POINTER(drmModeCrtc)]
        self.libdrm.drmModeFreeCrtc.restype = None

        self.display_type = self._get_display_type()
        self.compositor = self._get_compositor() if self.display_type == 'wayland' else None
        self.environment = get_environment()

        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='drm')

        if self.environment == 'desktop':
            self.enforce_resolution()

    """Determine the broad session type (x11/wayland). Uses XDG_SESSION_TYPE, which is set by
    every apt-based distro's display manager (lightdm, gdm3, sddm, etc.), so this works regardless
    of the desktop environment/compositor in use rather than only recognizing specific ones.
    """
    def _get_display_type(self):
        session_desktop = os.getenv('XDG_SESSION_DESKTOP') or ''
        current_desktop = os.getenv('XDG_CURRENT_DESKTOP') or ''
        session_type = (os.getenv('XDG_SESSION_TYPE') or '').lower()

        if session_type == 'x11':
            return 'x11'
        elif session_type == 'wayland':
            return 'wayland'

        # Fallback for setups that don't populate XDG_SESSION_TYPE (some minimal/legacy greeters)
        combined = f'{session_desktop} {current_desktop}'.lower()
        wayland_hints = ('wayland', 'labwc', 'wayfire', 'sway', 'hyprland', 'weston')
        if any(hint in combined for hint in wayland_hints):
            return 'wayland'
        elif combined.strip():
            return 'x11'

        log.error(f'Unable to determine display type from XDG_SESSION_DESKTOP="{session_desktop}", '
                  f'XDG_CURRENT_DESKTOP="{current_desktop}" and XDG_SESSION_TYPE="{session_type}"')

        return None

    """Identify the specific Wayland compositor/desktop so the correct resize tool can be chosen.
    Recognizes wlroots-based compositors (which share wlr-randr) as well as KDE Plasma/GNOME, which
    need their own tooling.
    """
    def _get_compositor(self):
        session_desktop = (os.getenv('XDG_SESSION_DESKTOP') or '').lower()
        current_desktop = (os.getenv('XDG_CURRENT_DESKTOP') or '').lower()
        combined = f'{session_desktop} {current_desktop}'

        if 'kde' in combined or 'plasma' in combined:
            return 'kde'
        elif 'gnome' in combined:
            return 'gnome'
        elif any(name in combined for name in ('labwc', 'wayfire', 'sway', 'hyprland', 'weston')):
            return 'wlroots'

        # Unknown wlroots-based compositors still generally support wlr-randr, so try it as a default
        return 'wlroots'

    def get_refresh_rate(self, mode):
        if mode.htotal == 0 or mode.vtotal == 0:
            return 0.0
        return float(mode.clock) * 1000.0 / (mode.htotal * mode.vtotal)

    def get_connector_name(self, connector: "drmModeConnector") -> str:
        try:
            prefix = {
                drmModeConnector.DRM_MODE_CONNECTOR_Unknown: "Unknown",
                drmModeConnector.DRM_MODE_CONNECTOR_VGA: "VGA",
                drmModeConnector.DRM_MODE_CONNECTOR_DVII: "DVI-I",
                drmModeConnector.DRM_MODE_CONNECTOR_DVID: "DVI-D",
                drmModeConnector.DRM_MODE_CONNECTOR_DVIA: "DVI-A",
                drmModeConnector.DRM_MODE_CONNECTOR_Composite: "Composite",
                drmModeConnector.DRM_MODE_CONNECTOR_SVIDEO: "SVIDEO",
                drmModeConnector.DRM_MODE_CONNECTOR_LVDS: "LVDS",
                drmModeConnector.DRM_MODE_CONNECTOR_Component: "Component",
                drmModeConnector.DRM_MODE_CONNECTOR_9PinDIN: "DIN",
                drmModeConnector.DRM_MODE_CONNECTOR_DisplayPort: "DP",
                drmModeConnector.DRM_MODE_CONNECTOR_HDMIA: "HDMI-A",
                drmModeConnector.DRM_MODE_CONNECTOR_HDMIB: "HDMI-B",
                drmModeConnector.DRM_MODE_CONNECTOR_TV: "TV",
                drmModeConnector.DRM_MODE_CONNECTOR_eDP: "eDP",
                drmModeConnector.DRM_MODE_CONNECTOR_VIRTUAL: "Virtual",
                drmModeConnector.DRM_MODE_CONNECTOR_DSI: "DSI",
                drmModeConnector.DRM_MODE_CONNECTOR_DPI: "DPI",
                drmModeConnector.DRM_MODE_CONNECTOR_WRITEBACK: "Writeback",
                drmModeConnector.DRM_MODE_CONNECTOR_SPI: "SPI",
            }[connector.connector_type]
        except KeyError:
            prefix = "Unknown"
        return f"{prefix}-{connector.connector_type_id}"

    """Get the supported and current display configuration."""
    def get_display_config(self):
        configs = []

        for card_idx in range(2):
            card_name = f"/dev/dri/card{card_idx}"

            try:
                log.debug(f'Attempting to open card {card_name}')
                fd = os.open(card_name, os.O_RDONLY)
            except OSError:
                continue
            if fd < 0:
                continue

            try:
                resources = self.libdrm.drmModeGetResources(fd)
                if not resources:
                    continue

                for i in range(resources.contents.count_connectors):
                    conn_id = resources.contents.connectors[i]
                    conn_ptr = self.libdrm.drmModeGetConnector(fd, conn_id)
                    if not conn_ptr:
                        continue

                    conn = conn_ptr.contents

                    log.debug(
                        f'Connector {self.get_connector_name(conn)} '
                        f'connection={conn.connection} '
                        f'modes={conn.count_modes}'
                    )

                    if conn.connection == drmModeConnector.DRM_MODE_CONNECTED:

                        config = {
                            'device': self.get_connector_name(conn),
                            'current_resolution': dict(),
                            'resolutions': dict()
                            }

                        enc_ptr = self.libdrm.drmModeGetEncoder(fd, conn.encoder_id)
                        if enc_ptr:
                            encoder = enc_ptr.contents

                            crtc_ptr = self.libdrm.drmModeGetCrtc(fd, encoder.crtc_id)
                            if crtc_ptr:
                                crtc = crtc_ptr.contents
                                if crtc.mode_valid:
                                    mode = crtc.mode
                                    is_interlaced = bool(mode.flags & drmModeConnector.DRM_MODE_FLAG_INTERLACE)
                                    scan_type = "i" if is_interlaced else ""

                                    resolution = f'{mode.hdisplay}x{mode.vdisplay}{scan_type}'
                                    refresh_rate = mode.vrefresh
                                    config['current_resolution'][resolution] = refresh_rate

                                self.libdrm.drmModeFreeCrtc(crtc_ptr)

                            self.libdrm.drmModeFreeEncoder(enc_ptr)

                        for j in range(conn.count_modes):
                            mode = conn.modes[j]
                            is_interlaced = bool(mode.flags & drmModeConnector.DRM_MODE_FLAG_INTERLACE)
                            scan_type = "i" if is_interlaced else ""

                            resolution = f'{mode.hdisplay}x{mode.vdisplay}{scan_type}'
                            refresh_rate = mode.vrefresh

                            if not config['resolutions'].get(resolution):
                                config['resolutions'][resolution] = [refresh_rate]
                            else:
                                config['resolutions'][resolution].append(refresh_rate)

                        configs.append(config)

                    self.libdrm.drmModeFreeConnector(conn_ptr)
            finally:
                os.close(fd)

        if len(configs) == 0:
            #raise RuntimeError('No connected display devices found')
            log.warning("No connected display devices found")
            return []

        return configs

    """Enforce the desired resolution on an X11 display.
    @param display_config: the display configuration dictionary obtained from get_display_config
    """
    def _enforce_x_resolution(self, configs):
        if not shutil.which('xrandr'):
            log.error('xrandr not found; install the x11-xserver-utils package to enforce resolution on X11')
            return

        for config in configs:
            if config['current_resolution'].get(self.resolution):
                log.debug(f'{config["device"]} already set to {self.resolution}')
                continue

            elif config['resolutions'].get(self.resolution):
                device, connector, output = config['device'].split('-')
                x11_device = f'{device}-{output}'

                log.info(f'Setting {x11_device} to {self.resolution}')
                success = execute_managed([
                    'xrandr', '--output', x11_device,
                    '--mode', self.resolution
                ])

                if not success:
                    log.error(f'Failed to set resolution on {config["device"]}')

            else:
                log.error(f'Unable to find {self.resolution} in {config["resolutions"].keys()}')
    
    """Enforce the desired resolution on a Wayland display, choosing the tool appropriate for the
    active compositor since there is no single universal Wayland resize command.
    @param display_config: the display configuration dictionary obtained from get_display_config
    """
    def _enforce_wayland_resolution(self, configs):
        if self.compositor == 'gnome':
            log.error('Resolution enforcement is not supported on GNOME/mutter (no CLI resize tool available)')
            return

        if self.compositor == 'kde':
            tool, build_args = 'kscreen-doctor', lambda device, resolution: [
                'kscreen-doctor', f'output.{device}.mode.{resolution}'
            ]
        else:
            tool, build_args = 'wlr-randr', lambda device, resolution: [
                'wlr-randr', '--output', device, '--mode', resolution
            ]

        if not shutil.which(tool):
            log.error(f'{tool} not found; unable to enforce resolution for compositor "{self.compositor}"')
            return

        for config in configs:
            if config['current_resolution'].get(self.resolution):
                log.debug(f'{config["device"]} already set to {self.resolution}')
                continue

            elif config['resolutions'].get(self.resolution):
                log.info(f'Setting {config["device"]} to {self.resolution}')
                success = execute_managed(build_args(config['device'], self.resolution))

                if not success:
                    log.error(f'Failed to set {self.resolution} on {config["device"]}')

            else:
                log.error(f'Unable to find {self.resolution} in {config["resolutions"].keys()}')

    """Enforce the desired resolution based on the current display type"""
    def enforce_resolution(self):
        try:
            configs = self.get_display_config()

            if not configs:
                log.debug('No displays available yet')
                return

            if self.display_type == 'x11':
                self._enforce_x_resolution(configs)

            elif self.display_type == 'wayland':
                self._enforce_wayland_resolution(configs)

            else:
                log.error(f'Unsupported display type: {self.display_type}')

        except Exception as e:
            log.error(f'Failed to enforce resolution: {e}')

    """Get diagnostics information about the current display configuration"""
    def get_diagnostics(self):
        return self.get_display_config()

    #region Async Main Loop

    async def run(self):

        if self.environment != 'desktop':
            return

        log.info("Listening for display changes...")

        #
        # Initial retry loop.
        # Handles booting with no display attached.
        #
        for _ in range(30):
            try:
                configs = self.get_display_config()

                if configs:
                    log.info('Display detected during startup')
                    self.enforce_resolution()
                    break

            except Exception:
                pass

            await asyncio.sleep(2)

        while self._running:
            try:
                device = await asyncio.to_thread(self.monitor.poll, 1)

                if device is None:
                    continue

                log.info(
                    f'DRM event: action={device.action} '
                    f'name={device.sys_name}'
                )

                if device.action in ('change', 'add', 'remove'):

                    #
                    # Give DRM/compositor time to settle.
                    #
                    await asyncio.sleep(2)

                    self.enforce_resolution()

            except Exception as e:
                log.error(f'Display monitor error: {e}')

            await asyncio.sleep(1)

    #endregion