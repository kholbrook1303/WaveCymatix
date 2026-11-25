import os
import sys
import tomllib
from pathlib import Path

if os.environ.get("WAVECYMATIX_HOME"):
    APP_ROOT = Path(os.environ["WAVECYMATIX_HOME"]).expanduser().resolve()
elif sys.prefix != sys.base_prefix:
    APP_ROOT = Path(sys.prefix).parent
else:
    package_root = Path(__file__).resolve().parents[1]
    if package_root.parent.name != "src":
        raise RuntimeError(
            "Cannot locate WaveCymatix configuration and data files. "
            "Set WAVECYMATIX_HOME to the application data directory."
        )
    APP_ROOT = package_root.parents[1]

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"


class Config:
    """Load TOML configuration tables as section dictionaries."""

    def __init__(self, config_path):
        try:
            with open(config_path, "rb") as config_file:
                config = tomllib.load(config_file)

            for section, values in config.items():
                if not isinstance(values, dict):
                    raise ValueError(f"Expected a TOML table for section {section!r}")
                setattr(
                    self,
                    section.lower(),
                    {name.lower(): value for name, value in values.items()},
                )
        except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
            raise RuntimeError(
                f"Error loading configuration file {config_path}: {error}"
            ) from error
