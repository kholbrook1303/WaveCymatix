import ctypes.util
import logging
import os
import platform
import subprocess
import shutil
import sys

from subprocess import Popen

log = logging.getLogger()

def configure_linux_graphics_environment():
    if sys.platform == 'linux':
        os.environ.setdefault("MESA_GL_VERSION_OVERRIDE", "3.3")

"""Determine the current running environment based on the contents of /boot/issue.txt"""
def get_environment():
    if sys.platform == 'win32':
        return 'desktop'
    elif sys.platform == 'darwin':
        return 'desktop'
    elif sys.platform == 'linux':
        if shutil.which("systemctl"):
            # Check if the default target is graphical
            res = subprocess.run(["systemctl", "get-default"], capture_output=True, text=True)
            if res.stdout.strip() == "graphical.target":
                return 'desktop'
                
            # Check if the display manager service is enabled
            res = subprocess.run(["systemctl", "is-enabled", "display-manager.service"], capture_output=True)
            if res.returncode == 0:
                return 'desktop'

        # Fallback scan for common display managers
        display_managers = ["gdm", "gdm3", "lightdm", "sddm", "greetd", "lxdm", "xdm"]
        return 'desktop' if any(shutil.which(dm) for dm in display_managers) else 'lite'
    else:
        raise Exception("Unsupported platform: %s" % sys.platform)

    return 'desktop'

"""Execute a managed process.
@param args: an array of arguments including the executable
@param shell: specifies whether or not to run the command as shell
@returns a boolean indicating whether the process execution failed
"""
def execute_managed(args, shell=False):
    process = Popen(args, universal_newlines=True, shell=shell)
    stdout,stderr = process.communicate()
        
    if stdout:
        log.debug('stdout: {}'.format(stdout))
    if stderr:
        log.error(stderr)
        return False
    if process.returncode != 0:
        log.error('command {} return code: {}'.format(args, process.returncode))
        return False
        
    return True

"""Load a shared library using ctypes.
@param name: the name of the library to load
@returns the loaded library
"""
def load_library(name: str, path: str = None, global_symbols: bool = False):
    candidates = [path] if path else []

    if not path:
        discovered_path = ctypes.util.find_library(name)
        if discovered_path:
            candidates.append(discovered_path)

        if sys.platform == 'darwin':
            library_filename = f"lib{name}.dylib"
            candidates.extend(
                os.path.join(library_dir, library_filename)
                for library_dir in (
                    '/usr/local/lib',
                    '/opt/local/lib',
                    '/opt/homebrew/lib',
                )
            )

    errors = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if global_symbols:
                return ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
            return ctypes.CDLL(candidate)
        except OSError as exc:
            errors.append(f'{candidate}: {exc}')

    detail = '; '.join(errors) if errors else 'no library path was found'
    raise OSError(f'Unable to load {name}: {detail}')