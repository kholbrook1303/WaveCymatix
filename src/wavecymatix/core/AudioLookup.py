import asyncio
import logging
import os
import threading
import requests
import tempfile
import time
import wave

import numpy as np

from io import BytesIO
from PIL import Image
from shazamio import Shazam

log = logging.getLogger()

class AudioLookup(threading.Thread):
    """Audio lookup thread using Shazam for music recognition.
    @param thread_event: threading.Event to signal thread exit
    @param config: Config instance
    @param now_playing: NowPlayingUI instance to update track info
    """
    def __init__(self, thread_event, config, audio_capture, now_playing, lookup_gate=None):
        super().__init__(daemon=True)
        self.lookup_gate = lookup_gate
        self.thread_event = thread_event
        self.config = config
        self.now_playing = now_playing
        self.audio_capture = audio_capture

        # PCM cache setup
        self.sample_rate = config.audio_lookup.get('audio_sample_rate', 44100)
        self.channels = config.audio_lookup.get('audio_channels', 2)

        # Minimum audio for recognition (compare against interleaved sample count)
        self.min_seconds = config.audio_lookup.get('min_audio_seconds', 5)
        self.min_samples = self.sample_rate * self.min_seconds * self.channels

        # Minimum RMS level (0.0-1.0 of full scale) to treat audio as real signal vs. background noise
        self.min_rms = config.audio_lookup.get('min_audio_rms', 0.02)

        # Continuous lookup settings
        self.continuous_lookup = config.audio_lookup.get('continuous_lookup', False)
        self.continuous_lookup_interval = config.audio_lookup.get('continuous_lookup_interval', 10)

        # Persistent temp WAV file
        self.tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self.tmp_wav_path = self.tmp_wav.name
        self.tmp_wav.close()

        # Lookup control
        self.lookup_lock = threading.Lock()
        self.lookup_in_progress = False

        # Shazam client
        self.shazam = Shazam()
        
    def _pcm_float_to_int16_mono(self, pcm):
        pcm = pcm.reshape(-1, self.channels)
        mono = pcm.mean(axis=1)

        mono = np.clip(mono, -1.0, 1.0)
        mono16 = (mono * 32767).astype(np.int16)
        log.info(f"Converted mono16: samples={len(mono16)}, min={mono16.min()}, max={mono16.max()}, mean={mono16.mean():.2f}")
        return mono16

    def _write_wav(self, mono16):
        try:
            with wave.open(self.tmp_wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(mono16.tobytes())
            log.debug(f"WAV written: {self.tmp_wav_path}, {len(mono16)} samples")
        except Exception:
            log.exception("Failed to write WAV")

    async def _shazam_lookup(self):
        with open(self.tmp_wav_path, 'rb') as file:
            result = await self.shazam.recognize(file.read())

            if not result or "track" not in result:
                log.info("Shazam was unable to find a match")
                return None

            track = result["track"]
            log.info(f"Results from Shazam: {result}")
            
            album_art = self._download_album_art(track.get("images", {}).get("coverart"))
            return {
                "Title": track.get("title"),
                "Artist": track.get("subtitle"),
                "Album": track.get("sections", [{}])[0].get("metadata", [{}])[0].get("text", ""),
                "Artwork": album_art
            }

    def _download_album_art(self, url):
        if not url:
            return None

        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()

            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            log.info(f"Downloaded album art: {img.size}, mode={img.mode}")
            return img

        except Exception as e:
            log.error(f"Failed to download album art '{url}': {e}")
            return None

    def _perform_lookup(self):
        try:
            pcm = self.audio_capture.snapshot_pcm()
            if pcm is None or len(pcm) < self.min_samples:
                log.warning("Not enough audio for lookup")
                return

            mono16 = self._pcm_float_to_int16_mono(pcm)

            rms = float(np.sqrt(np.mean((mono16.astype(np.float64) / 32768.0) ** 2)))
            if rms < self.min_rms:
                log.info(f"Audio too quiet for lookup (rms={rms:.4f} < {self.min_rms}); skipping")
                return
            log.info(f"Audio level rms={rms:.4f}")

            self._write_wav(mono16)

            track_info = None

            if not track_info:
                log.info("Starting Shazam lookup")
                track_info = asyncio.run(self._shazam_lookup())

            if not track_info:
                return

            if self.now_playing.artist == track_info.get("Artist") and \
                self.now_playing.text == track_info.get("Title") and \
                self.now_playing.album == track_info.get("Album"):
                log.debug("Track info matches currently displayed; skipping update")
                return

            self.now_playing.set_track_info(
                track_info.get("Title"),
                artist=track_info.get("Artist"),
                album=track_info.get("Album"),
                album_art=track_info.get("Artwork"),
            )

        except Exception:
            log.exception("Track lookup failed")
        finally:
            with self.lookup_lock:
                self.lookup_in_progress = False

    def request_lookup(self):
        """
        Trigger a track lookup using the current rolling cache.
        Safe to call from UI / input thread.
        """
        with self.lookup_lock:
            if self.lookup_in_progress:
                log.info("Lookup already in progress; ignoring request")
                return
            self.lookup_in_progress = True

        log.info("Starting track lookup thread")
    
        # Start a separate thread for lookup
        threading.Thread(target=self._perform_lookup, daemon=True).start()

    def run(self):
        next_lookup = time.monotonic() + self.continuous_lookup_interval
        while not self.thread_event.wait(0.5):
            if not self.continuous_lookup:
                continue

            now = time.monotonic()
            if now < next_lookup:
                continue
            next_lookup = now + self.continuous_lookup_interval

            # Only look up when no other audio handler is supplying track info
            if self.lookup_gate is not None and not self.lookup_gate():
                continue
            self.request_lookup()

    def close(self):
        if os.path.exists(self.tmp_wav_path):
            log.info(f"Persistent WAV file remains at: {self.tmp_wav_path}")
            #os.remove(self.tmp_wav_path)