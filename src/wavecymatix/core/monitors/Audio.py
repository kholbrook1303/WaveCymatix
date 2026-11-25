import asyncio
import logging
import os
import time

PULSECTL_INSTALLED = False
try:
    from pulsectl import Pulse
    PULSECTL_INSTALLED = True
except Exception:
    # pulsectl raises OSError/FileNotFoundError (not ImportError) when libpulse isn't found, e.g. on Windows/macOS
    Pulse = None
    PULSECTL_INSTALLED = False

from wavecymatix.lib.abstracts import AsyncService
from wavecymatix.lib.config import APP_ROOT, Config

log = logging.getLogger()


class DeviceCatalog:
    """Catalog for managing devices and their attributes"""
    def __init__(self):
        self.card                   = dict()
        self.module                 = dict()
        self.sink                   = dict()
        self.source                 = dict()
        self.sink_cards             = dict()
        self.bluetooth_devices      = dict()
        self.plugin_devices         = dict()
        self.unsupported_sinks      = dict()
        self.unsupported_sources    = dict()


class Audio(AsyncService):
    """PulseAudio device monitor and controller
    @param thread_event: Event to signal when the thread should stop.
    @param config: Configuration object containing audio settings.
    """

    SUPPORTED_PLATFORMS = {"linux"}

    @classmethod
    def is_supported(cls):
        return super().is_supported() and PULSECTL_INSTALLED

    def __init__(self, config):
        super().__init__()
        self._config = config

        self._loop = None
        self._main_task = None
        self._running = False
        
        self.audio_mode             = self._config.audio_ctrl.get('audio_mode', 'automatic')
        self.io_device_mode         = self._config.audio_ctrl.get('io_device_mode', 'aux')

        # Mic suppression: mutes the mic loopback whenever non-mic audio (aux or plugin) is
        # actually audible on the real output path, so the mic doesn't need to be unplugged
        # when switching from records (mic pickup) to a digital source like Bluetooth/Plexamp.
        self.mic_auto_suppress          = self._config.audio_ctrl.get('mic_auto_suppress', False)
        self.mic_suppress_threshold     = self._config.audio_ctrl.get('mic_suppress_threshold', 0.02)
        self.mic_suppress_release_secs  = self._config.audio_ctrl.get('mic_suppress_release_seconds', 1.5)
        self.mic_suppress_poll_interval = self._config.audio_ctrl.get('mic_suppress_poll_interval', 0.25)

        self._mic_routed             = False
        self._mic_muted              = False
        self._last_loud_time         = 0.0

        self.sink_device            = None
        self.source_device          = None
        self.sink_devices           = list()
        
        self.devices                = DeviceCatalog()

        self.ar_sink_name           = 'platform-wave_cymatix.stereo'
        self.ar_sink_desc           = 'WaveCymatix-NULL-Sink'

        config_path = os.path.join(APP_ROOT, 'conf')
        self.supported_cards = self.load_audio_config(config_path, 'audio_cards.toml')
        self.supported_sinks = self.load_audio_config(config_path, 'audio_sinks.toml')
        self.supported_sources = self.load_audio_config(config_path, 'audio_sources.toml')

    """Load audio configuration from a specified path and file.
    @param config_path: The path to the configuration directory.
    @param config_file: The name of the configuration file to load.
    """
    def load_audio_config(self, config_path, config_file):
        supported_dict = dict()
        config = Config(os.path.join(config_path, config_file))
        for item_id in config.general.get(config_file.split('.')[0], list()):
            try:
                item_meta = getattr(config, item_id)
                item_name = item_meta['name']
                if not item_name:
                    continue

                supported_dict[item_name] = item_meta
            except:
                pass

        return supported_dict

    """Execute a PulseAudio method with optional arguments.
    @param func: The PulseAudio method to call.
    @param args: Optional arguments to pass to the method.
    """
    def pulse_audio_callback(self, func, args=None):
        with Pulse('WaveCymatix PulseAudio Callback') as pulse:
            method = getattr(pulse, func)
            if isinstance(args, (list, tuple)):
                return method(*args)
            elif args is not None:
                return method(args)
            else:
                return method()
        
    """Get raw diagnostic information from PulseAudio"""
    def get_raw_diagnostics(self):
        """Yield diagnostic information for sinks, sources, modules, etc"""

        log.info('Getting sinks: sink_list()')
        for sinkInfo in self.pulse_audio_callback('sink_list'):
            log.info('Found sink {}'.format(sinkInfo.name))
            yield 'sinks', sinkInfo.__dict__
            
        log.info('Getting sources: source_list()')
        for sourceInfo in self.pulse_audio_callback('source_list'):
            log.info('Found sink {}'.format(sourceInfo.name))
            yield 'sources', sourceInfo.__dict__
            
        log.info('Getting sink inputs: sink_input_list()')
        for sinkInputInfo in self.pulse_audio_callback('sink_input_list'):
            log.info('Found sink input {}'.format(sinkInputInfo.name))
            yield 'sink_inputs', sinkInputInfo.__dict__
    
        log.info('Getting source outputs: source_output_list()')
        for sourceOutputInfo in self.pulse_audio_callback('source_output_list'):
            log.info('Found sink input {}'.format(sourceOutputInfo.name))
            yield 'source_outputs', sourceOutputInfo.__dict__
            
        log.info('Getting modules: module_list()')
        for moduleInfo in self.pulse_audio_callback('module_list'):
            log.info('Found module {}'.format(moduleInfo.name))
            yield 'modules', moduleInfo.__dict__
            
        log.info('Getting cards: card_list()')
        for cardInfo in self.pulse_audio_callback('card_list'):
            log.info('Found card {}'.format(cardInfo.name))
            yield 'cards', cardInfo.__dict__
            
        log.info('Getting clients: client_list()')
        for clientInfo in self.pulse_audio_callback('client_list'):
            log.info('Found client {}'.format(clientInfo.name))
            yield 'clients', clientInfo.__dict__

    """Set the volume for a device.
    @param device_type: The PulseAudio device type
    @param device: The PulseAudio device to set the volume for.
    @param device_volume: The volume level to set for the device.
    """
    def set_volume(self, device_type, device, device_volume):
        try:
            channels = len(device.volume.values)
            
            log.info('Setting sink {} volume to {}'.format(device.name, device_volume))
            self.pulse_audio_callback('volume_set_all_chans', [device, device_volume])

        except Exception as e:
            log.exception('Failed to set sink {} volume'.format(e))

    """Set the default device
    @param device_type: The PulseAudio device type
    @param device: The PulseAudio device
    """
    def set_default(self, device_type, device_name):
        self.pulse_audio_callback(f'{device_type}_default_set', device_name)

    """Get module arguments from PulseAudio modules.
    @param module: The PulseAudio module object to extract arguments from.
    """
    def get_module_arguments(self, module):
        module.args = dict()
        if hasattr(module, 'argument'):
            if module.argument:
                args = module.argument.split(' ')
                for arg in args:
                    if '=' in arg:
                        key, val = arg.split('=', 1)
                        module.args[key] = val

    """Get modules by name from PulseAudio.
    @param module_name: The name of the module to search for.
    """
    def get_modules(self, module_name=None):
        modules = list()
        
        for module in self.pulse_audio_callback('module_list'):
            try:
                self.get_module_arguments(module)
                if module.name == module_name:
                    modules.append(module)
            except Exception as e:
                log.exception('Failed to process argument %s: %s', getattr(module, 'argument', None), e)

        return modules

    """Check if a module is loaded by name.
    @param module_name: The name of the module to check.
    """
    def module_loaded(self, module_name):
        modules = self.get_modules(module_name)
        if len(modules) > 0:
            return True

        return False
           
    """Unload loopback modules based on sink and source names.
    @param sink_name: The name of the sink to unload loopback modules for.
    @param source_name: The name of the source to unload loopback modules for.
    """
    def unload_loopback_modules(self, sink_name=None, source_name=None):
        for module in self.get_modules('module-loopback'):            
            unload = False
            if not source_name and not sink_name:
                unload = True
            elif sink_name and module.args.get('sink', None) == sink_name:
                unload = True
            elif source_name and module.args.get('source', None) == source_name:
                unload = True

            if unload:
                log.info('Unloading loopback module {}'.format(module.name))
                self.pulse_audio_callback('module_unload', module.index)

    """Load a loopback module for a specific source and sink.
    @param source_name: The name of the source to load the loopback module for.
    @param sink_name: The name of the sink to load the loopback module for.
    """
    def load_loopback_module(self, source_name, sink_name):
        log.info('Loading module-loopback for source {} sink {}'.format(source_name, sink_name))
        self.pulse_audio_callback('module_load', [
            'module-loopback',
            f'source={source_name} sink={sink_name} latency_msec=20 source_dont_move=true sink_dont_move=true'
        ])

    """Unload null sink modules"""
    def unload_null_sink_modules(self):
        for module in self.get_modules('module-null-sink'):
            log.info('Unloading null sink {}'.format(module.name))
            self.pulse_audio_callback('module_unload', module.index)

    """Unload combined sink modules"""
    def unload_combined_sink_modules(self):
        for module in self.get_modules('module-combine-sink'):
            log.info('Unloading combined sink {}'.format(module.name))
            self.pulse_audio_callback('module_unload', module.index)

    """Unload suspend on idle modules"""
    def unload_suspend_on_idle(self):
        for module in self.get_modules('module-suspend-on-idle'):
            log.info('Unloading suspend on idle module {}'.format(module.name))
            self.pulse_audio_callback('module_unload', module.index)

    """Load a combined sink module with specified sinks.
    @param combined_sinks: A list of sink names to combine.
    """
    def load_combined_sinks(self, combined_sinks):
        log.info('Loading combined sink for {}'.format(combined_sinks))
        self.pulse_audio_callback('module_load', [
            'module-combine-sink',
            'slaves=' + ','.join(combined_sinks)
            ])

    """Update sink devices from PulseAudio"""
    def setup_combined_sink(self):
        log.info('Setting up combined sink for PulseAudio')
        sinks = [sink.name for sink in self.devices.sink.values()]
        
        load_sink = False
        combined_sinks = self.get_modules('module-combine-sink')
        if len(combined_sinks) > 0:
            combined_sink_slaves = combined_sinks[0].args["slaves"].split(',')

            log.info('Found an active module-combine-sink module loaded!')
            log.info('Found {} combined sinks with {} slaves'.format(len(combined_sinks), len(combined_sink_slaves)))
            if any(sink not in combined_sink_slaves for sink in sinks):
                self.unload_combined_sink_modules()
                load_sink = True
                time.sleep(0.5)
        else:
            load_sink = True

        log.info(f'Found {len(sinks)} sinks: {sinks} reload combined sink: {load_sink}')
        if len(sinks) > 1 and load_sink:
            self.load_combined_sinks(sinks)
            self.sink_device = 'combined'

            self.pulse_audio_callback('sink_default_set', 'combined')

    """Add a new card device to the catalog and set its profile.
    @param card: The PulseAudio card object to add.
    """
    def add_card_device(self, card):
        if card.name.startswith('bluez_source'):
            return

        log.info('Found a new card device: {}'.format(card.name))

        card_profile = None
        if self.audio_mode == 'automatic':
            card_profile_types = self._config.automatic.get('card_profile_types', list())
            card_profile_modes = self._config.automatic.get('card_profile_modes', list())

            if len(card_profile_types) == 0 or len(card_profile_modes) == 0:
                log.warning('Skipping card control as there are missing configurations in settings.toml')
                return

            # Traverse backwards to prioritize input/output devices
            for profile in reversed(card.profile_list):
                if profile.name == 'off':
                    continue
                
                identified = False
                profile_defs = profile.name.split('+')
                for profile_def in profile_defs:
                    if not ':' in profile_def:
                        log.warning(f'Undefined profile type {profile_def}')
                        continue

                    profile_type, profile_mode = profile_def.split(':')

                    if profile_type in card_profile_types and profile_mode in card_profile_modes:
                        card_profile = profile.name
                        identified = True

                if identified:
                    break

        elif self.audio_mode == 'manual':
            if self.supported_cards.get(card.name):
                for card_profile in card.profile_list:
                    card_meta = self.supported_cards[card.name]
                    if card_profile.name == card_meta['profile']:
                        card_profile = card_meta['profile']
            
        if not card_profile:
            return

        if card.profile_active.name == card_profile:
            log.info('Profile {} is already set for card {} '.format(card_profile, card.name))
        else:
            log.info('Setting {} profile for card {} '.format(card_profile, card.name))
            self.pulse_audio_callback('card_profile_set', [card, card_profile])

        card.device = 'pa'
        self.devices.card[card.index] = card

        return

    """Add a new sink device to the catalog and set its properties.
    @param sink: The PulseAudio sink object to add.
    """
    def add_sink_device(self, sink):
        # if sink.name == self.ar_sink_name:
        #     return

        if sink.name == 'combined':
            return

        log.info('Found a new sink device: {}'.format(sink.name))

        sink_type = None
        if 'Built-in Audio' in sink.description:
            sink_type = 'internal'
        else:
            sink_type = 'external'

        sink_volume = None

        if self.audio_mode == 'automatic':
            sink_device_type = self._config.automatic.get('sink_device_type', None)
            if sink_device_type and sink_type != sink_device_type:
                log.debug('Skipping sink {} as it is not {}'.format(sink.name, sink_device_type))
                return

            sink_volume = self._config.automatic.get('sink_device_volume', 1.0)
            if not isinstance(sink_volume, float):
                log.warning('Sink {} does not have a float value for volume'.format(sink.name))
                sink_volume = 1.0

        if self.audio_mode == 'manual':
            if self.supported_sinks.get(sink.name):
                sink_meta = self.supported_sinks[sink.name]
                if sink_meta['type'] and sink_type != sink_meta['type']:
                    log.debug('Skipping sink {} as it is not {}'.format(sink_type, sink_meta['type']))
                    return
                    
                sink_volume = sink_meta.get('volume', 1.0)
                if not isinstance(sink_volume, float):
                    log.warning('Sink {} does not have a float value for volume'.format(sink.name))
                    sink_volume = 1.0

        if sink.proplist.get('alsa.card') and sink.proplist.get('alsa.long_card_name'):
            alsa_card = sink.proplist['alsa.card']
            alsa_name = sink.proplist['alsa.long_card_name']
            log.debug('Found sink ALSA card {} {}'.format(alsa_name, alsa_card))

            if not self.devices.sink_cards.get(alsa_card):
                self.devices.sink_cards[alsa_card] = alsa_name
        
        self.set_default('sink', sink.name)
        self.set_volume('sink', sink, sink_volume)
        self.sink_device = sink.name

        sink.type = sink_type
        sink.device = 'pa'
        self.devices.sink[sink.index] = sink

        return

    """Add a new source device to the catalog and manage the audio routing.
    @param source: The PulseAudio source object to add.
    """
    def add_source_device(self, source):
        if source.name.startswith('bluez_source'):
            return

        log.info('Found source device: {} {}'.format(source.name, source))

        if source.name.startswith('alsa_output'):
            loopback_modules = self.get_modules('module-loopback')
            if not any(lm.args['source'] == source.name and lm.args['sink'] == self.ar_sink_name for lm in loopback_modules):
                self.load_loopback_module(source.name, self.ar_sink_name)

            log.warning('Source device: {} is not supported'.format(source.name))
            self.devices.unsupported_sources[source.name] = source
            return

        if source.name.endswith('.monitor'):
            log.warning('Source device: {} is not supported'.format(source.name))
            self.devices.unsupported_sources[source.name] = source
            return

        if source.description and 'USB3.0 Capture' in source.description:
            log.warning('Source device: {} is not supported'.format(source.name))
            self.devices.unsupported_sources[source.name] = source
            return

        source_type = None
        if any('mic' in port.name or 'Microphone' in port.description for port in source.port_list):
            source_type = 'mic'
        else:
            source_type = 'aux'

        if source.proplist.get('alsa.card') and source.proplist.get('alsa.long_card_name'):
            alsa_card = source.proplist['alsa.card']
            alsa_name = source.proplist['alsa.long_card_name']
            log.debug('Found Source ALSA card {} {}'.format(alsa_name, alsa_card))

            if self.devices.sink_cards.get(alsa_card):
                if self.devices.sink_cards[alsa_card] == alsa_name:
                    if self.io_device_mode:
                        source_type = self.io_device_mode

        if self.audio_mode == 'automatic':
            source_device_type = self._config.automatic.get('source_device_type', None)
            if source_device_type and source_type != source_device_type:
                log.debug('Skipping source {} as it is not {}'.format(source.name, source_device_type))
                return

            source_volume = self._config.automatic.get('source_device_volume', .85)
            if not isinstance(source_volume, float):
                log.warning('Source {} does not have a float value for volume'.format(source.name))
                source_volume = .85

        if self.audio_mode == 'manual':
            if self.supported_sources.get(source.name):
                source_meta = self.supported_sources[source.name]

                source_device_type = source_meta['type']
                if source_device_type and source_type != source_device_type:
                    log.debug('Skipping source {} as it is not {}'.format(source_meta['name'], source_device_type))
                    return

                source_volume = source_meta.get('volume', .85)
                if not isinstance(source_volume, float):
                    log.warning('Source {} does not have a float value for volume'.format(source.name))
                    source_volume = .85

        self.set_volume('source', source, source_volume)

        self.unload_loopback_modules(source_name=source.name)

        if self.sink_device and source_type == 'aux':
            for sink in self.devices.sink.values():
                self.load_loopback_module(source.name, sink.name)

        elif self.sink_device and source_type == 'mic':
            self.load_loopback_module(source.name, self.ar_sink_name)

        source.type = source_type
        source.device = 'pa'
        self.devices.source[source.index] = source

        self._refresh_mic_routed_state()

        return 

    """Remove a card device from the catalog.
    @param card: The PulseAudio card object to remove.
    """
    def remove_card_device(self, card):
        log.warning('Card {} has been disconnected'.format(card.name))
        self.devices.card.pop(card.index, None)

    def remove_sink_device(self, sink):
        log.warning('Sink device {} has been disconnected'.format(sink.name))

        self.devices.sink.pop(sink.index, None)

        if self.sink_device == sink.name:
            self.sink_device = None
        
        if sink.proplist.get('alsa.card') and sink.proplist.get('alsa.long_card_name'):
            alsa_card = sink.proplist['alsa.card']
            alsa_name = sink.proplist['alsa.long_card_name']

            if self.devices.sink_cards.get(alsa_card):
                self.devices.sink_cards.pop(alsa_card)

    """Remove a source device from the catalog and unload its loopback modules.
    @param source: The PulseAudio source object to remove.
    """
    def remove_source_device(self, source):
        if source.name.startswith('bluez_source'):
            return

        log.warning('Source device {} has been disconnected'.format(source.name))
        self.unload_loopback_modules(source_name=source.name)
        self.devices.source.pop(source.index, None)

        self._refresh_mic_routed_state()

    """Setup PulseAudio devices and load the null sink."""
    def setup_devices(self):
        self.unload_suspend_on_idle()

        self._reset_mic_mute_state()

        # Load null sink
        self.pulse_audio_callback('module_load', [
            'module-null-sink',
            f'sink_name={self.ar_sink_name} sink_properties=device.description={self.ar_sink_desc}'
            ])

        # Set null sink monitor as default
        self.pulse_audio_callback('source_default_set', f'{self.ar_sink_name}.monitor')

        for card in self.pulse_audio_callback('card_list'):
            self.add_card_device(card)

        for sink in self.pulse_audio_callback('sink_list'):
            self.add_sink_device(sink)

        self.setup_combined_sink()

        for source in self.pulse_audio_callback('source_list'):
            self.add_source_device(source)

    """Handle PulseAudio events for device changes.
    @param event: The PulseAudio event object containing information about the device change.
    """
    def pulse_event_handler(self, event):
        device      = None
        device_type = event.facility._value
        try:
            match event.t:
                case 'new':
                    log.info(f'PulseAudio new event for device type: {device_type} index: {event.index}')

                    for pulse_item in self.pulse_audio_callback(f'{device_type}_list'):
                        if event.index == pulse_item.index:
                            device = pulse_item
                            break

                    if not device:
                        log.warning(f'Unable to find PulseAudio {device_type} with index {event.index} for event {event.t}')

                    elif device.name == 'combined':
                        pass

                    elif device.name.startswith('bluez_source'):
                        pass

                    else:
                        getattr(self, f'add_{device_type}_device')(device)

                        if device_type == 'sink':
                            self.setup_combined_sink()

                case 'remove':
                    log.info(f'PulseAudio remove event for device type: {device_type} index: {event.index}')

                    devices = getattr(self.devices, device_type)
                    if devices.get(event.index):
                        device = devices[event.index]

                    if not device:
                        log.warning(f'Unable to find PulseAudio {device_type} with index {event.index} for event {event.t}')

                    elif device.name == 'combined':
                        pass

                    else:
                        getattr(self, f'remove_{device_type}_device')(device)

        except Exception as e:
            log.error(f'Failed to handle PulseAudio event: {e}')

    #region Async Main Loop

    async def run(self):

        self.setup_devices()

        pulse_listener_task = asyncio.create_task(
            asyncio.to_thread(self._pulse_listener)
        )

        mic_suppression_task = asyncio.create_task(
            asyncio.to_thread(self._mic_suppression_listener)
        )

        try:
            await asyncio.gather(
                pulse_listener_task,
                mic_suppression_task
            )

        except asyncio.CancelledError:
            # AsyncService._shutdown() cancels this run() task.
            # Do not modify _running here; AsyncService.stop() owns it.
            raise

        except Exception:
            log.exception('Unhandled exception in PulseAudio listeners')
            raise

        log.info("PulseAudio monitor stopped")

    #endregion

    #region PulseAudio Event Listener

    def _pulse_listener(self):
        log.info('Starting PulseAudio event listener')
        with Pulse('WaveCymatix Event Listener') as pulse:

            pulse.event_mask_set('sink', 'source', 'card')
            pulse.event_callback_set(self.pulse_event_handler)

            while self._running:
                pulse.event_listen(timeout=0.1)

    #endregion

    #region Mic Suppression

    def _mic_suppression_listener(self):
        log.info('Starting Mic Suppression listener')
        with Pulse('WaveCymatix Mic Suppression') as pulse:
            while self._running:
                if self.mic_auto_suppress and self._mic_routed:
                    try:
                        self._evaluate_mic_suppression(pulse)
                    except Exception:
                        log.exception('Mic suppression peak check failed')

                time.sleep(0.01)

    def _is_mic_source(self, source):
        port = getattr(source, 'port_active', None)
        if not port:
            return False

        port_name = getattr(port, 'name', None) or ''
        if port_name == 'analog-input-mic' or port_name.endswith(('-mic', '_mic')):
            return True

        port_desc = getattr(port, 'description', None) or ''
        return 'mic' in port_desc.lower()

    def _get_mic_source(self, pulse=None):
        sources = pulse.source_list() if pulse else self.pulse_audio_callback('source_list')

        mic_sources = list()
        for source in sources:
            props = getattr(source, 'proplist', None) or {}
            name = getattr(source, 'name', '') or ''

            if props.get('device.class') == 'monitor' or name.endswith('.monitor'):
                continue

            if props.get('device.api') != 'alsa' or props.get('device.class') != 'sound':
                continue

            if self._is_mic_source(source):
                mic_sources.append(source)

        if len(mic_sources) != 1:
            if len(mic_sources) > 1:
                log.warning('Found {} physical microphone sources, cannot resolve a unique one'.format(len(mic_sources)))
            return None

        return mic_sources[0]

    def _reset_mic_mute_state(self):
        mic_source = self._get_mic_source()
        if mic_source is not None and mic_source.mute:
            log.info('Resetting microphone source {} to unmuted'.format(mic_source.name))
            self.pulse_audio_callback('source_mute', [mic_source.index, False])

        self._mic_muted = False

    def _refresh_mic_routed_state(self, pulse=None):
        self._mic_routed = self._get_mic_source(pulse) is not None

        if not self._mic_routed:
            self._set_mic_muted(False, pulse=pulse)

    def _set_mic_muted(self, muted, pulse=None):
        if self._mic_muted == muted:
            return

        mic_source = self._get_mic_source(pulse)
        if mic_source is None:
            return

        log.info('{} microphone source {}'.format('Muting' if muted else 'Unmuting', mic_source.name))
        if pulse:
            pulse.source_mute(mic_source.index, muted)
        else:
            self.pulse_audio_callback('source_mute', [mic_source.index, muted])

        self._mic_muted = muted

    def _get_monitor_source_index(self, pulse):
        if not self.sink_device:
            return None

        for sink in pulse.sink_list():
            if sink.name == self.sink_device:
                return sink.monitor_source

        return None

    def _evaluate_mic_suppression(self, pulse):
        monitor_source = self._get_monitor_source_index(pulse)
        if monitor_source is None:
            return

        # Blocks for mic_suppress_poll_interval seconds; doubles as this loop's poll cadence.
        peak = pulse.get_peak_sample(monitor_source, self.mic_suppress_poll_interval)
        now = time.monotonic()

        if peak >= self.mic_suppress_threshold:
            self._last_loud_time = now
            self._set_mic_muted(True, pulse=pulse)
        elif self._mic_muted and (now - self._last_loud_time) >= self.mic_suppress_release_secs:
            self._set_mic_muted(False, pulse=pulse)

    #endregion

    #region Cleanup

    def close(self):

        self._reset_mic_mute_state()

        for source_index, source_device in self.devices.source.items():
            if not source_device.name.startswith('bluez_source'):
                self.unload_loopback_modules(source_name=source_device.name)

        self.unload_null_sink_modules()
        self.unload_combined_sink_modules()

    #endregion