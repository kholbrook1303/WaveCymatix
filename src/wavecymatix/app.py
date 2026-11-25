import argparse
import json
import logging
import os
import sys
import threading
from pathlib import Path

from wavecymatix.lib.common import configure_linux_graphics_environment, get_environment
from wavecymatix.lib.config import APP_ROOT, Config
from wavecymatix.lib.log import log_init

log = logging.getLogger()


def get_diagnostics(config: Config) -> None:
    from wavecymatix.core.monitors.Audio import Audio
    from wavecymatix.core.monitors.Display import Display

    diag_path = APP_ROOT / "diag"
    diag_path.mkdir(parents=True, exist_ok=True)

    audio = Audio(None, config)
    audio_data = {}
    for category, data in audio.get_raw_diagnostics():
        audio_data.setdefault(category, []).append(data)

    audio_json = diag_path / "raw_audio.json"
    audio_json.write_text(json.dumps(audio_data, indent=2, default=str), encoding="utf-8")
    audio.close()

    display = Display(None, config)
    if get_environment() == "desktop":
        display_data = display.get_diagnostics()
        (diag_path / "display.json").write_text(
            json.dumps(display_data, indent=2, default=str),
            encoding="utf-8",
        )
    display.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--diagnostics",
        action="store_true",
        dest="diag",
        help="Output diagnostics report for issue debugging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.environ["SDL_VIDEO_DEBUG"] = "1"
    configure_linux_graphics_environment()

    if (
        sys.platform == "linux"
        and get_environment() == "lite"
        and not os.environ.get("PYOPENGL_PLATFORM")
    ):
        os.environ["PYOPENGL_PLATFORM"] = "egl"

    from wavecymatix.core.RenderingLoop import RenderingLoop

    config_path = APP_ROOT / "conf" / "settings.toml"
    config = Config(config_path)
    log_level = config.general.get("log_level", logging.DEBUG)
    log_init(str(APP_ROOT / "WaveCymatix.log"), log_level)
    log_init("console", log_level)

    log.info(
        f"Startup environment: env={get_environment()} "
        f"MESA_GL_VERSION_OVERRIDE={os.environ.get('MESA_GL_VERSION_OVERRIDE', '<unset>')} "
        f"PYOPENGL_PLATFORM={os.environ.get('PYOPENGL_PLATFORM', '<unset>')} "
        f"SDL_VIDEODRIVER={os.environ.get('SDL_VIDEODRIVER', '<unset>')}"
    )

    if parse_args(argv).diag:
        get_diagnostics(config)
        return 0

    app = None
    try:
        app = RenderingLoop(config, threading.Event())
        app.run()
    except Exception as error:
        log.exception(f"Fatal error running WaveCymatix: {error}")
        raise
    finally:
        if app:
            app.close()

    return 0
