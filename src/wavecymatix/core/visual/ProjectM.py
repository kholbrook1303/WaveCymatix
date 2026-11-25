import ctypes
import logging
import os
import random
import time
import shutil

import numpy as np

from configparser import ConfigParser

from wavecymatix.lib.common import load_library
from wavecymatix.lib.config import APP_ROOT
from wavecymatix.core.MediaLibraryStore import MediaLibraryStore

log = logging.getLogger()

# projectM playlist sorting predicates
SORT_PREDICATE_FULL_PATH        = 0 # Sort by full path name
SORT_PREDICATE_FILENAME_ONLY    = 1 # Sort only by preset filename

# projectM playlist sorting order
SORT_ORDER_ASCENDING            = 0 # Sort in alphabetically ascending order.
SORT_ORDER_DESCENDING           = 1 # Sort in alphabetically descending order.

PresetSwitchedCallback = ctypes.CFUNCTYPE(None, ctypes.c_bool, ctypes.c_uint, ctypes.c_void_p)
PresetSwitchFailedCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p
)

@PresetSwitchedCallback
def on_preset_switched(is_hard_cut, index, context):
    instance = ctypes.cast(context, ctypes.POINTER(ctypes.py_object)).contents.value
    instance._on_preset_switched(is_hard_cut, index)

@PresetSwitchFailedCallback
def on_preset_switch_failed(preset_filename, error_msg, context):
    instance = ctypes.cast(context, ctypes.POINTER(ctypes.py_object)).contents.value
    instance._on_preset_switch_failed(preset_filename, error_msg)

class ProjectM:
    def __init__(self, config, sdl_rendering):
        self.config = config
        self.sdl_rendering = sdl_rendering

        log.debug('The projectM settings are as follows:')
        for key, val in self.config.projectm.items():
            log.debug(f'{key}: {val}')

        self.visible = False
            
        self.projectm = None
        if not os.name == 'nt':
            self.projectm_lib = load_library('projectM-4', global_symbols=True)
        else:
            self.projectm_lib = load_library('projectM-4', os.path.join(APP_ROOT, 'runtime', 'artifacts', 'projectM-4.dll'))
        
        self.projectm_playlist = None
        if not os.name == 'nt':
            self.projectm_playlist_lib = load_library('projectM-4-playlist', global_symbols=True)
        else:
            self.projectm_playlist_lib = load_library('projectM-4-playlist', os.path.join(APP_ROOT, 'runtime', 'artifacts', 'projectM-4-playlist.dll'))

        self.preset_paths = list()
        self.texture_paths = list()
        self.sprites = dict()
        self.runtime_presets = []
        self.active_playlist = "all"

        self.supported_extensions = (".milk",)
        self.playlist_store = MediaLibraryStore(
            media_type="projectm",
            section_config=self.config.projectm,
            supported_extensions=self.supported_extensions,
            key_prefix="projectm",
            general_config=self.config.general,
        )

        self.texture_burn_in = False

        self.current_preset = None
        self.current_preset_start = None
        self.real_fps = 0.0
        self._pending_transition_event = None

        # Set up projectm function signatures
        self.projectm_lib.projectm_create.restype = ctypes.c_void_p
        self.projectm_lib.projectm_destroy.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_set_window_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.projectm_lib.projectm_set_fps.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.projectm_lib.projectm_set_mesh_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.projectm_lib.projectm_set_aspect_correction.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.projectm_lib.projectm_set_preset_locked.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.projectm_lib.projectm_set_preset_duration.argtypes = [ctypes.c_void_p, ctypes.c_double]
        self.projectm_lib.projectm_set_soft_cut_duration.argtypes = [ctypes.c_void_p, ctypes.c_double]
        self.projectm_lib.projectm_set_hard_cut_enabled.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.projectm_lib.projectm_set_hard_cut_duration.argtypes = [ctypes.c_void_p, ctypes.c_double]
        self.projectm_lib.projectm_get_hard_cut_duration.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_hard_cut_duration.restype = ctypes.c_double
        self.projectm_lib.projectm_get_hard_cut_enabled.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_hard_cut_enabled.restype = ctypes.c_bool
        self.projectm_lib.projectm_set_hard_cut_sensitivity.argtypes = [ctypes.c_void_p, ctypes.c_float]
        self.projectm_lib.projectm_get_hard_cut_sensitivity.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_hard_cut_sensitivity.restype = ctypes.c_float
        self.projectm_lib.projectm_get_preset_duration.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_preset_duration.restype = ctypes.c_double
        self.projectm_lib.projectm_get_soft_cut_duration.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_soft_cut_duration.restype = ctypes.c_double
        self.projectm_lib.projectm_get_aspect_correction.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_aspect_correction.restype = ctypes.c_bool
        self.projectm_lib.projectm_get_window_size.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.projectm_lib.projectm_set_beat_sensitivity.argtypes = [ctypes.c_void_p, ctypes.c_float]
        self.projectm_lib.projectm_get_beat_sensitivity.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_beat_sensitivity.restype = ctypes.c_float
        self.projectm_lib.projectm_opengl_render_frame.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_mesh_size.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        self.projectm_lib.projectm_get_preset_locked.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_get_preset_locked.restype = ctypes.c_bool
        self.projectm_lib.projectm_pcm_get_max_samples.argtypes = [ctypes.c_void_p]
        self.projectm_lib.projectm_pcm_get_max_samples.restype = ctypes.c_uint
        self.projectm_lib.projectm_pcm_add_float.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_uint, ctypes.c_int]
        self.projectm_lib.projectm_pcm_add_float.restype = None
        self.projectm_lib.projectm_set_texture_search_paths.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p)), ctypes.c_int]
        self.projectm_lib.projectm_set_texture_search_paths.restype = None
        
        # Future user sprites feature (This feature is currently available in the main branch and slated for 4.2 release)
        try:
            self.projectm_lib.projectm_sprite_create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            self.projectm_lib.projectm_sprite_create.restype = ctypes.c_uint
            self.projectm_lib.projectm_sprite_get_sprite_count.argtypes = [ctypes.c_void_p]
            self.projectm_lib.projectm_sprite_get_sprite_count.restype = ctypes.c_uint32
            self.projectm_lib.projectm_sprite_get_sprite_ids.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            self.projectm_lib.projectm_sprite_get_sprite_ids.restype = None
            self.projectm_lib.projectm_sprite_get_max_sprites.argtypes = [ctypes.c_void_p]
            self.projectm_lib.projectm_sprite_get_max_sprites.restype = ctypes.c_uint
            self.projectm_lib.projectm_sprite_destroy.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self.projectm_lib.projectm_sprite_destroy.restype = None
            self.projectm_lib.projectm_sprite_destroy_all.argtypes = [ctypes.c_void_p]
            self.projectm_lib.projectm_sprite_destroy_all.restype = None

            sprites_config = ConfigParser(
                allow_no_value=True,
                comment_prefixes=("#", ";", "//"),
            )
            config_path = os.path.join(APP_ROOT, 'conf', 'sprites.ini')
            sprites_config.read(config_path)
            for section in sprites_config.sections():
                sprite_index = section[-2:]
                self.sprites[sprite_index] = {
                    'id': 0,
                    'img': '',
                    'code': ''
                }

                for name, str_value in sprites_config.items(section):
                    if name =='img':
                        self.sprites[sprite_index]['img'] = str_value
                    self.sprites[sprite_index]['code'] += f'{name}={str_value}\n'

        except AttributeError as e:
            log.warning(f'The loaded libprojectM does not support sprites. This feature requires libprojectM (4.2+): {e}')

        try:
            self.projectm_lib.projectm_opengl_burn_texture.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
            self.projectm_lib.projectm_opengl_burn_texture.restype = None

            self.texture_burn_in = True
        except AttributeError as e:
            log.warning(f'The loaded libprojectM does not support texture burn-in. This feature requires libprojectM (4.2+): {e}')

        # Set up projectm playlist function signatures
        self.projectm_playlist_lib.projectm_playlist_create.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_create.restype = ctypes.c_void_p
        self.projectm_playlist_lib.projectm_playlist_destroy.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_set_shuffle.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.projectm_playlist_lib.projectm_playlist_clear.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_add_preset.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool]
        self.projectm_playlist_lib.projectm_playlist_add_path.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool, ctypes.c_bool]
        self.projectm_playlist_lib.projectm_playlist_remove_preset.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.projectm_playlist_lib.projectm_playlist_remove_preset.restype = ctypes.c_bool
        self.projectm_playlist_lib.projectm_playlist_sort.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int, ctypes.c_int]
        self.projectm_playlist_lib.projectm_playlist_size.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_size.restype = ctypes.c_size_t
        self.projectm_playlist_lib.projectm_playlist_play_next.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.projectm_playlist_lib.projectm_playlist_play_previous.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.projectm_playlist_lib.projectm_playlist_get_position.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_get_position.restype = ctypes.c_uint
        self.projectm_playlist_lib.projectm_playlist_size.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_size.restype = ctypes.c_size_t
        self.projectm_playlist_lib.projectm_playlist_set_position.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_bool]
        self.projectm_playlist_lib.projectm_playlist_get_shuffle.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_get_shuffle.restype = ctypes.c_bool
        self.projectm_playlist_lib.projectm_playlist_item.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.projectm_playlist_lib.projectm_playlist_item.restype = ctypes.c_void_p
        self.projectm_playlist_lib.projectm_playlist_free_string.argtypes = [ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_free_string.restype = None
        self.projectm_playlist_lib.projectm_playlist_set_preset_switched_event_callback.argtypes = [ctypes.c_void_p, PresetSwitchedCallback, ctypes.c_void_p]
        self.projectm_playlist_lib.projectm_playlist_set_preset_switch_failed_event_callback.argtypes = [ctypes.c_void_p, PresetSwitchFailedCallback, ctypes.c_void_p]

        log.info(f'Initializing projectM...')
        if not self.projectm:
            canvas_width, canvas_height = self.sdl_rendering.get_drawable_size()

            self.projectm = self.projectm_lib.projectm_create()
            if not self.projectm:
                log.error("Failed to initialize projectM. Possible reasons are a lack of required OpenGL features or GPU resources.")
                raise RuntimeError("projectM initialization failed")

            fps = self.config.projectm.get("projectm.fps", 60)
            if fps <= 0:
                fps = 60

            self.set_window_size(canvas_width, canvas_height)

            self.projectm_lib.projectm_set_fps(self.projectm, fps)
            self.projectm_lib.projectm_set_mesh_size(self.projectm, self.config.projectm.get("projectm.meshx", 64), self.config.projectm.get("projectm.meshy", 32))
            self.projectm_lib.projectm_set_aspect_correction(self.projectm, self.config.projectm.get("projectm.aspectcorrectionenabled", True))
            self.projectm_lib.projectm_set_preset_locked(self.projectm, self.config.projectm.get("projectm.presetlocked", False))
            self.projectm_lib.projectm_set_preset_duration(self.projectm, self.config.projectm.get("projectm.displayduration", 60))
            self.projectm_lib.projectm_set_soft_cut_duration(self.projectm, self.config.projectm.get("projectm.transitionduration", 0))
            self.projectm_lib.projectm_set_hard_cut_enabled(self.projectm, self.config.projectm.get("projectm.hardcutsenabled", True))
            self.projectm_lib.projectm_set_hard_cut_duration(self.projectm, self.config.projectm.get("projectm.hardcutduration", 30))
            self.projectm_lib.projectm_set_hard_cut_sensitivity(self.projectm, float(self.config.projectm.get("projectm.hardcutsensitivity", 1)))
            self.projectm_lib.projectm_set_beat_sensitivity(self.projectm, float(self.config.projectm.get("projectm.beatsensitivity", 1)))

            self.projectm_playlist = self.projectm_playlist_lib.projectm_playlist_create(self.projectm)
            if not self.projectm_playlist:
                log.error("Failed to create the projectM preset playlist manager instance.")
                raise RuntimeError("Playlist initialization failed")

            texture_path_index = 0
            while True:
                config_key = 'projectm.texturepath'
                if texture_path_index > 0:
                    config_key += '.{}'.format(texture_path_index)

                if self.config.projectm.get(config_key, None):
                    log.info('Adding texture path {} {}'.format(config_key, self.config.projectm.get(config_key)))
                    self.texture_paths.append(self.config.projectm.get(config_key))

                else:
                    break

                texture_path_index += 1

            if self.texture_paths:
                texture_path_list = [ctypes.create_string_buffer(path.encode('utf-8')) for path in self.texture_paths]
                texture_path_array = (ctypes.POINTER(ctypes.c_char_p) * len(texture_path_list))()

                for i, path in enumerate(texture_path_list):
                    texture_path_array[i] = ctypes.cast(ctypes.pointer(path), ctypes.POINTER(ctypes.c_char_p))

                self.projectm_lib.projectm_set_texture_search_paths(self.projectm, texture_path_array, len(self.texture_paths))

            self.shuffle_enabled = self.config.projectm.get("projectm.shuffleenabled", False)
            self.projectm_playlist_lib.projectm_playlist_set_shuffle(self.projectm_playlist, False)

            self.reload_playlist_library()

            # Setup callback and userdata
            self._preset_switched_event_callback = on_preset_switched
            self._preset_switch_failed_event_callback = on_preset_switch_failed
        
            self._user_data = ctypes.py_object(self)
            self._user_data_ptr = ctypes.cast(ctypes.pointer(self._user_data), ctypes.c_void_p)

            # Register the preset event callbacks
            self.projectm_playlist_lib.projectm_playlist_set_preset_switched_event_callback(
                self.projectm_playlist,
                self._preset_switched_event_callback,
                self._user_data_ptr
            )

            self.projectm_playlist_lib.projectm_playlist_set_preset_switch_failed_event_callback(
                self.projectm_playlist,
                self._preset_switch_failed_event_callback,
                self._user_data_ptr
            )
        else:
            log.info('projectM instance already initialized')

    def close(self):
        self.playlist_store.close()
        if self.projectm_playlist:
            self.projectm_playlist_lib.projectm_playlist_destroy(self.projectm_playlist)
            self.projectm_playlist = None
        if self.projectm:
            self.projectm_lib.projectm_destroy(self.projectm)
            self.projectm = None
        self._user_data_ptr = None
        self._user_data = None

    def _show_sprite(self, sprite_index):
        start_time = time.time()
        sprite_code = self.sprites[sprite_index]['code']
        sprite_id = self.projectm_lib.projectm_sprite_create(self.projectm, 'milkdrop'.encode(), sprite_code.encode())
        self.sprites[sprite_index]['id'] = sprite_id
        elapsed = (time.time() - start_time) * 1000
        log.info(f'Sprite {sprite_index} created with ID {sprite_id} in {elapsed:.2f}ms')
    
        current_count = self.projectm_lib.projectm_sprite_get_sprite_count(self.projectm)
        log.debug(f'Current sprite count: {current_count}')
        return sprite_id

    def _kill_sprite(self, sprite_index):
        start_time = time.time()
        sprite_id = self.sprites[sprite_index]['id']
        log.info(f'Destroying sprite {sprite_index} with ID {sprite_id}...')
        self.projectm_lib.projectm_sprite_destroy(self.projectm, sprite_id)
        self.sprites[sprite_index]['id'] = 0
        elapsed = (time.time() - start_time) * 1000
        log.info(f'Sprite {sprite_index} destroyed in {elapsed:.2f}ms')

        current_count = self.projectm_lib.projectm_sprite_get_sprite_count(self.projectm)
        log.debug(f'Current sprite count: {current_count}')

    def _load_preset_paths(self):
        self.preset_paths = []

        preset_path_index = 0
        while True:
            config_key = 'projectm.presetpath'
            if preset_path_index > 0:
                config_key += '.{}'.format(preset_path_index)

            preset_path = self.config.projectm.get(config_key, None)
            if not preset_path:
                break

            log.info('Adding preset path {} {}'.format(config_key, preset_path))
            self.preset_paths.append(preset_path)
            preset_path_index += 1

    def _discover_presets(self):
        discovered = []
        for preset_path in self.preset_paths:
            if os.path.isfile(preset_path):
                if os.path.splitext(preset_path)[1].lower() in self.supported_extensions:
                    discovered.append(os.path.normpath(preset_path))
                continue

            if not os.path.isdir(preset_path):
                continue

            for root, _, files in os.walk(preset_path):
                for name in files:
                    full_path = os.path.join(root, name)
                    if os.path.splitext(full_path)[1].lower() in self.supported_extensions:
                        discovered.append(os.path.normpath(full_path))

        return discovered

    def _load_runtime_playlist(self, playlist_name, allow_shuffle=True):
        presets = self.playlist_store.get_playlist_items(playlist_name)
        if allow_shuffle and self.get_preset_shuffle():
            random.shuffle(presets)
        self._set_runtime_presets(presets)
        self.active_playlist = playlist_name

    def _set_runtime_presets(self, presets):
        self.projectm_playlist_lib.projectm_playlist_clear(self.projectm_playlist)

        for preset_path in presets:
            self.projectm_playlist_lib.projectm_playlist_add_preset(
                self.projectm_playlist,
                preset_path.encode(),
                False,
            )

        # playlist_size = self.projectm_playlist_lib.projectm_playlist_size(self.projectm_playlist)
        # self.projectm_playlist_lib.projectm_playlist_sort(self.projectm_playlist, 0, playlist_size, SORT_PREDICATE_FULL_PATH, SORT_ORDER_ASCENDING)

        self.runtime_presets = list(presets)
        if self.runtime_presets:
            self.set_preset_index(0, False)
        else:
            self.current_preset = None

    def reload_playlist_library(self):
        self._load_preset_paths()
        discovered = self._discover_presets()
        self.playlist_store.sync_library(discovered)
        selected = self.playlist_store.resolve_startup_playlist()
        self._load_runtime_playlist(selected)

    def _on_preset_switched(self, is_hard_cut: bool, index: int):
        self.current_preset = self._get_preset_item(index)
        self.current_preset_start = time.time()
        log.info(f"[{is_hard_cut=}] Preset switched to: {self.current_preset}")

        if self.config.projectm.get("window.displaypresetnameintitle", True):
            seperator = '/' if os.name != 'nt' else '\\'
            self.sdl_rendering.set_sdl_window_title(self.current_preset.rsplit(seperator, 1)[1].encode())

        if not self.visible:
            return

        self._pending_transition_event = {
            "is_hard": bool(is_hard_cut),
            "preset": self.current_preset,
            "at": time.time(),
        }

    def _on_preset_switch_failed(self, preset_filename: bytes, error_msg: bytes):
        preset_name = (
            preset_filename.decode("utf-8", errors="replace")
            if preset_filename
            else "<unknown preset>"
        )
        error_string = (
            error_msg.decode("utf-8", errors="replace")
            if error_msg
            else "Unknown preset loading error"
        )
        log.error(f'Failed to switch preset {preset_name} with error {error_string}')

    def _get_preset_item(self, index):
        item_ptr = self.projectm_playlist_lib.projectm_playlist_item(
            self.projectm_playlist, index
        )
        if not item_ptr:
            raise IndexError(f"Item at index {index} does not exist in the playlist")

        try:
            return ctypes.string_at(item_ptr).decode("utf-8")
        finally:
            self.projectm_playlist_lib.projectm_playlist_free_string(item_ptr)

    def _get_active_preset_index(self):
        return self.projectm_playlist_lib.projectm_playlist_get_position(self.projectm_playlist)

    def _get_mesh_size(self):
        mesh_x = ctypes.c_size_t()
        mesh_y = ctypes.c_size_t()
        self.projectm_lib.projectm_get_mesh_size(self.projectm, ctypes.byref(mesh_x), ctypes.byref(mesh_y))
        return mesh_x.value, mesh_y.value

    def burn_in_texture(self, texture_id, x, y, width, height):
        if not self.texture_burn_in:
            log.warning('Texture burn-in is not supported in the loaded libprojectM, cannot burn texture')
            return
        log.info(f'Burning texture ID {texture_id} into projectM at ({x}, {y}) with size ({width}x{height})')
        self.projectm_lib.projectm_opengl_burn_texture(self.projectm, texture_id, x, y, width, height)

    def handle_sprite(self, sprite_index):
        start_time = time.time()

        if len(self.sprites) == 0:
            log.warning(f'Sprites not enabled, cannot toggle {sprite_index}')
            return

        if sprite_index not in self.sprites:
            log.warning(f'No sprite found with index {sprite_index}')
            return

        sprite_count = self.projectm_lib.projectm_sprite_get_sprite_count(self.projectm)
        max_sprites = self.projectm_lib.projectm_sprite_get_max_sprites(self.projectm)
        log.debug(f'Sprite {sprite_index} toggle requested. Count={sprite_count}, Max={max_sprites}')

        if sprite_count >= max_sprites and self.sprites[sprite_index]['id'] == 0:
            log.warning(f'Max sprites reached ({max_sprites}). Cannot create {sprite_index}')
            return

        if self.sprites[sprite_index]['id'] == 0:
            self._show_sprite(sprite_index)
        else:
            self._kill_sprite(sprite_index)

        elapsed = (time.time() - start_time) * 1000
        log.info(f'Completed toggle for {sprite_index} in {elapsed:.2f}ms. Total sprites now: {self.projectm_lib.projectm_sprite_get_sprite_count(self.projectm)}')

    def kill_sprites(self):
        if len(self.sprites) == 0:
            log.warning('Sprites are not enabled in the loaded libprojectM, cannot destroy sprites')
            return

        log.info('Destroying all sprites...')
        self.projectm_lib.projectm_sprite_destroy_all(self.projectm)
        for name, info in self.sprites.items():
            info['id'] = 0

    def display_initial_preset(self):
        if self.projectm_playlist_lib.projectm_playlist_size(self.projectm_playlist) == 0:
            return

        if not self.config.projectm.get("projectm.enablesplash", False):
            self.projectm_playlist_lib.projectm_playlist_set_position(self.projectm_playlist, 0, True)

            # Currently it is best to handle shuffling by creating an index for each preset and randomizing it
            # libprojectM uses a random preset for shuffle so you cannot go to previous/next and get expected results
            # if self.config.projectm.get("projectm.shuffleenabled", False):
            #     self.projectm_playlist_lib.projectm_playlist_play_next(self.projectm_playlist, True)
            # else:
            #     self.projectm_playlist_lib.projectm_playlist_set_position(self.projectm_playlist, 0, True)

    def delete_visual(self, physical=False):
        preset_index = self._get_active_preset_index()
        if preset_index is not None and self.projectm_playlist_lib.projectm_playlist_size(self.projectm_playlist) > 0:
            preset_name = self._get_preset_item(preset_index)

            log.info(f'User has requested to delete preset {preset_name} with index {preset_index}')
            self.projectm_playlist_lib.projectm_playlist_remove_preset(self.projectm_playlist, preset_index)
            self.playlist_store.remove_items_from_playlist(self.active_playlist, [preset_name])
            self.runtime_presets = [path for path in self.runtime_presets if path != preset_name]
            
            try:
                if physical and self.config.projectm.get("projectm.presetdeletebackupenabled", True):
                    backup_path = self.config.projectm.get('projectm.presetdeletebackuppath', '/opt/WaveCymatix/preset_backup')

                    match_path = None
                    for preset_path in self.preset_paths:
                        if preset_name.startswith(preset_path):
                            match_path = preset_path
                            break

                    if match_path:
                        backup_path = preset_name.replace(match_path, backup_path)
                        backup_dir = os.path.dirname(backup_path)
                        os.makedirs(backup_dir, exist_ok=True)

                        shutil.move(preset_name, backup_path)

                elif physical:
                    os.remove(preset_name)
                    self.reload_playlist_library()

            except Exception as e:
                log.error(f'Failed to delete/backup preset {preset_name} with error: {e}')

            self.next_visual()
            0
        else:
            log.warning('No active preset to delete')

    def get_visual_playlist_names(self):
        return self.playlist_store.list_playlists()

    def get_active_visual_playlist_name(self):
        return self.active_playlist

    def get_visual_playlist_items(self, playlist_name):
        return self.playlist_store.get_playlist_items(playlist_name)

    def get_runtime_playlist_items(self):
        return list(self.runtime_presets)

    def set_active_visual_playlist(self, playlist_name):
        self._load_runtime_playlist(playlist_name)

    def create_visual_playlist(self, playlist_name):
        return self.playlist_store.create_playlist(playlist_name)

    def delete_visual_playlist(self, playlist_name):
        if self.playlist_store.delete_playlist(playlist_name):
            if self.active_playlist == playlist_name:
                fallback = self.playlist_store.resolve_startup_playlist()
                self._load_runtime_playlist(fallback)
            return True
        return False

    def add_items_to_visual_playlist(self, playlist_name, items, insert_at=None):
        added = self.playlist_store.add_items_to_playlist(playlist_name, items, insert_at=insert_at)
        if playlist_name == self.active_playlist and added:
            self._load_runtime_playlist(self.active_playlist, allow_shuffle=False)
        return added

    def remove_items_from_visual_playlist(self, playlist_name, items):
        removed = self.playlist_store.remove_items_from_playlist(playlist_name, items)
        if playlist_name == self.active_playlist and removed:
            self._load_runtime_playlist(self.active_playlist, allow_shuffle=False)
        return removed

    def move_item_in_visual_playlist(self, playlist_name, src_index, dst_index):
        moved = self.playlist_store.move_item_in_playlist(playlist_name, src_index, dst_index)
        if moved and playlist_name == self.active_playlist:
            self._load_runtime_playlist(self.active_playlist, allow_shuffle=False)
        return moved

    def add_items_to_favorites(self, items):
        return self.playlist_store.add_items_to_favorites(items)

    def remove_items_from_favorites(self, items):
        return self.playlist_store.remove_items_from_favorites(items)

    def is_item_favorite(self, item):
        return self.playlist_store.is_favorite(item)

    def get_current_visual_item(self):
        return self.current_preset

    def next_visual(self, hard_cut=False):
        self.projectm_playlist_lib.projectm_playlist_play_next(self.projectm_playlist, hard_cut)

    def previous_visual(self, hard_cut=False):
        self.projectm_playlist_lib.projectm_playlist_play_previous(self.projectm_playlist, hard_cut)

    def set_preset_index(self, index, hard_cut=False):
        self.projectm_playlist_lib.projectm_playlist_set_position(self.projectm_playlist, index, hard_cut)

    def set_visual_runtime_index(self, index):
        self.set_preset_index(index, False)

    def shift_runtime_from_index(self, index):
        if not self.runtime_presets:
            return False

        if index < 0 or index >= len(self.runtime_presets):
            return False

        self._set_runtime_presets(self.runtime_presets[index:])
        return True

    def move_runtime_item(self, src_index, dst_index):
        if not self.runtime_presets:
            return False
        if src_index < 0 or src_index >= len(self.runtime_presets):
            return False

        dst_index = max(0, min(int(dst_index), len(self.runtime_presets) - 1))
        if src_index == dst_index:
            return True

        updated = list(self.runtime_presets)
        item = updated.pop(src_index)
        updated.insert(dst_index, item)

        self._set_runtime_presets(updated)
        if self.active_playlist:
            self.playlist_store.replace_playlist_items(self.active_playlist, updated)
        return True

    def clear_runtime_playlist(self):
        self._set_runtime_presets([])
        return True

    def get_preset_shuffle(self):
        return getattr(self, "shuffle_enabled", False)

    def shuffle_playlist(self, shuffle):
        self.shuffle_enabled = bool(shuffle)
        self.projectm_playlist_lib.projectm_playlist_set_shuffle(self.projectm_playlist, False)
        if getattr(self, "active_playlist", None):
            self._load_runtime_playlist(self.active_playlist)

    def get_visual_locked(self):
        return self.projectm_lib.projectm_get_preset_locked(self.projectm)

    def toggle_visual_lock(self):
        locked = self.get_visual_locked()
        if locked:
            log.debug(f'User has requested to unlock the presets')
            self.projectm_lib.projectm_set_preset_locked(self.projectm, False)
        else:
            log.debug(f'User has requested to lock the presets')
            self.projectm_lib.projectm_set_preset_locked(self.projectm, True)

    def change_beat_sensitivity(self, value):
        current = self.projectm_lib.projectm_get_beat_sensitivity(self.projectm)
        self.projectm_lib.projectm_set_beat_sensitivity(self.projectm, current + value)
        log.debug(f"User has changed the Beat Sensitivity to: {self.projectm_lib.projectm_get_beat_sensitivity(self.projectm):.2f}")

    def set_window_size(self, canvas_width, canvas_height):
        self.projectm_lib.projectm_set_window_size(
            self.projectm, 
            ctypes.c_int(canvas_width), 
            ctypes.c_int(canvas_height)
            )

    def add_pcm(self, samples: np.ndarray, frame_count: int, channels: int):
        if not self.projectm:
            raise RuntimeError("projectM instance not initialized")

        samples = np.ascontiguousarray(samples, dtype=np.float32)
        ptr = samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

        self.projectm_lib.projectm_pcm_add_float(
            self.projectm, ptr, frame_count, channels
        )

    def render_frame(self):
        current_mesh_x = ctypes.c_size_t()
        current_mesh_y = ctypes.c_size_t()
        self.projectm_lib.projectm_get_mesh_size(
            self.projectm,
            ctypes.byref(current_mesh_x),
            ctypes.byref(current_mesh_y)
        )

        desired_mesh_x = self.config.projectm.get("projectm.meshx", 64)
        desired_mesh_y = self.config.projectm.get("projectm.meshy", 32)

        if (current_mesh_x.value != desired_mesh_x) or (current_mesh_y.value != desired_mesh_y):
            log.info(f'Updating mesh size from {current_mesh_x.value}x{current_mesh_y.value} to {desired_mesh_x}x{desired_mesh_y}')
            self.projectm_lib.projectm_set_mesh_size(
                self.projectm,
                int(desired_mesh_x),
                int(desired_mesh_y)
            )

        self.projectm_lib.projectm_opengl_render_frame(self.projectm)

    def target_fps(self):
        return self.config.projectm.get("projectm.fps", 60)

    def update_real_fps(self, fps):
        self.real_fps = float(fps)
        self.projectm_lib.projectm_set_fps(self.projectm, int(round(fps)))

    def get_real_fps(self):
        return self.real_fps

    def get_diagnostics_snapshot(self):
        if not self.projectm:
            return {}

        mesh_x, mesh_y = self._get_mesh_size()
        viewport_width = ctypes.c_size_t()
        viewport_height = ctypes.c_size_t()
        self.projectm_lib.projectm_get_window_size(
            self.projectm,
            ctypes.byref(viewport_width),
            ctypes.byref(viewport_height),
        )

        snapshot = {
            "beat_sensitivity": self.projectm_lib.projectm_get_beat_sensitivity(self.projectm),
            "hard_cut_enabled": self.projectm_lib.projectm_get_hard_cut_enabled(self.projectm),
            "hard_cut_duration": self.projectm_lib.projectm_get_hard_cut_duration(self.projectm),
            "hard_cut_sensitivity": self.projectm_lib.projectm_get_hard_cut_sensitivity(self.projectm),
            "preset_duration": self.projectm_lib.projectm_get_preset_duration(self.projectm),
            "soft_cut_duration": self.projectm_lib.projectm_get_soft_cut_duration(self.projectm),
            "aspect_correction": self.projectm_lib.projectm_get_aspect_correction(self.projectm),
            "mesh_size": (mesh_x, mesh_y),
            "viewport_size": (viewport_width.value, viewport_height.value),
            "render_fps": self.real_fps,
            "target_fps": self.target_fps(),
            "shuffle": self.get_preset_shuffle(),
            "playlist_index": self._get_active_preset_index(),
            "playlist_count": self.projectm_playlist_lib.projectm_playlist_size(
                self.projectm_playlist
            ),
            "sprite_count": None,
            "sprite_limit": None,
            "preset_elapsed": (
                max(0.0, time.time() - self.current_preset_start)
                if self.current_preset_start is not None
                else None
            ),
        }

        if hasattr(self.projectm_lib, "projectm_sprite_get_sprite_count"):
            snapshot["sprite_count"] = self.projectm_lib.projectm_sprite_get_sprite_count(
                self.projectm
            )
        if hasattr(self.projectm_lib, "projectm_sprite_get_max_sprites"):
            snapshot["sprite_limit"] = self.projectm_lib.projectm_sprite_get_max_sprites(
                self.projectm
            )

        return snapshot

    def get_current_preset(self):
        return self.current_preset

    def consume_transition_event(self):
        event = self._pending_transition_event
        self._pending_transition_event = None
        return event

    def get_presets_shuffle(self):
        return self.get_preset_shuffle()

    def toggle_presets_shuffle(self):
        self.shuffle_playlist(not self.get_preset_shuffle())