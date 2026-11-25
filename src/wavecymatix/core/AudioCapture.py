import logging
import os
import threading
from collections import deque

import numpy as np

if os.name == 'nt':
    from wavecymatix.core.AudioCaptureImpl_WASAPI import AudioCaptureImpl
else:
    from wavecymatix.core.AudioCaptureImpl_SDL import AudioCaptureImpl
    
log = logging.getLogger()

class AudioCapture:
    def __init__(self, config, projectm):
        self.config = config
        self.projectm = projectm

        # Rolling PCM cache shared by both capture backends, used by AudioLookup (Shazam)
        self.sample_rate        = 44100
        self.channels           = 2
        self._pcm_cache_seconds = self.config.general.get('pcm_cache_seconds', 10)
        self._pcm_cache         = deque()
        self._pcm_cache_samples = 0
        self._pcm_cache_lock    = threading.Lock()
        self._pcm_max_samples   = self.sample_rate * self.channels * self._pcm_cache_seconds

        self.audio_capture_impl = AudioCaptureImpl(self.config, self.projectm, self.push_pcm, self.set_audio_format)
        deviceList = self.audio_capture_impl.audio_device_list()
        audioDeviceIndex = self.get_initial_audio_device_index(deviceList)

        self.output_device_list(deviceList)
        self.audio_capture_impl.start_recording(audioDeviceIndex)

    def close(self):
        if self.audio_capture_impl:
            self.audio_capture_impl.close()

    def fill_buffer(self):
        self.audio_capture_impl.fill_buffer()

    def set_audio_format(self, sample_rate, channels):
        """Called by the active capture impl once the actual device format is known."""
        with self._pcm_cache_lock:
            self.sample_rate = sample_rate
            self.channels = channels
            self._pcm_max_samples = self.sample_rate * self.channels * self._pcm_cache_seconds

    def push_pcm(self, samples):
        with self._pcm_cache_lock:
            self._pcm_cache.append(samples)
            self._pcm_cache_samples += len(samples)

            while self._pcm_cache_samples > self._pcm_max_samples:
                dropped = self._pcm_cache.popleft()
                self._pcm_cache_samples -= len(dropped)

    def snapshot_pcm(self):
        with self._pcm_cache_lock:
            if self._pcm_cache_samples == 0:
                return None
            return np.concatenate(self._pcm_cache)

    def snapshot_pcm_seconds(self, seconds):
        needed = int(self.sample_rate * self.channels * seconds)

        with self._pcm_cache_lock:
            if self._pcm_cache_samples < needed:
                return None

            pcm = np.concatenate(self._pcm_cache)
            return pcm[-needed:]

    def output_device_list(self, deviceList):
        log.info(f'Available audio capturing devices:')

        for device in deviceList:
            log.info(f' - {device}: {deviceList[device]}')

    def get_initial_audio_device_index(self, deviceList):
        audioDeviceIndex = -1

        try:
            for device in deviceList:
                if deviceList[device] == b'Monitor of WaveCymatix-NULL-Sink':
                    audioDeviceIndex = device
                    break

            if not deviceList.get(audioDeviceIndex):
                audioDeviceIndex = -1
        except Exception as ex:
            log.error(f'audioDeviceIndex "{audioDeviceIndex}" does not exist')

        log.info(f'Using initial audio device index: {audioDeviceIndex}')

        return audioDeviceIndex

    def next_audio_device(self):
        log.info('Switching to next audio capture device')
        self.audio_capture_impl.next_audio_device()