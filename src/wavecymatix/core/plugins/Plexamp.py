import asyncio
import threading
import logging
import time
import requests
import io
import websocket
import json

from plexapi.server import PlexServer
from PIL import Image

from wavecymatix.lib.abstracts import AsyncService

log = logging.getLogger(__name__)


class Plexamp(AsyncService):

    # Dependencies (requests/websocket/plexapi) are OS-agnostic; scoped to linux for now to match prior behavior.
    SUPPORTED_PLATFORMS = {"linux", "win32", "darwin"}

    MAX_TEXTURE_SIZE = 2048
    POLL_INTERVAL = 1.0  # seconds

    """Plexamp integration using Plex API sessions and websocket notifications."""
    def __init__(self, config, now_playing):
        super().__init__()
        self.config = config
        self.now_playing = now_playing

        # Public state properties for UI binding
        self.handler_active = False
        self.handler_playlist = False
        
        # Plex connection
        self._plex = None

        # Plex configuration
        self._plex_url = self.config.plexamp.get("plex_url")
        self._plex_token = self.config.plexamp.get("plex_token")
        self._plex_client = self.config.plexamp.get("plex_client", "Plexamp")

        # Component Objects
        self._plex_client_id = None
        self._last_rating_key = None
        self._track_initialized = False

        self._running = False

    #region Private Helper Functions

    def _get_client(self):
        try:
            if not self._plex:
                return None

            return self._plex.client(self._plex_client)
        except Exception as e:
            log.warning(f"Unable to fetch Plex client: {e}")
            return None

    def _check_current_session(self):
        try:
            sessions = self._plex.sessions()

            active_session = None
            for session in sessions:
                log.debug(f"Checking session: player={getattr(session.player, 'title', None)} state={getattr(session.player, 'state', None)}")
                if session.player.title == self._plex_client:
                    active_session = session
                    break

            if not active_session:
                # log.warning(f"No active Plexamp session detected across session list: {[session.name for session in sessions]}")
                return

            player = getattr(active_session, "player", None)

            if not player:
                return

            if "plexamp" in player.product.lower():

                item = active_session

                artist = getattr(item, "grandparentTitle", "")
                title = getattr(item, "title", "")
                album = getattr(item, "parentTitle", "")
                art = item.thumb

                self._commit_track(active_session)

                log.info(f"Detected active Plexamp session: {artist} - {title}")
                return

        except Exception:
            log.exception("Session check failed")

    def _handle_playing_event(self, container):
            notifications = container.get("PlaySessionStateNotification", [])

            for entry in notifications:

                rating_key = entry.get("ratingKey")
                state = entry.get("state")
                client_id = entry.get("clientIdentifier")

                log.debug(f"Plexamp WS event: state={state} ratingKey={rating_key} client={client_id}")

                # Resolve clientIdentifier → Plex client
                try:
                    if not self._plex_client_id:
                        try:
                            client = self._plex.client(self._plex_client)
                            self._plex_client_id = client.machineIdentifier
                        except Exception:
                            return

                    if client_id != self._plex_client_id:
                        continue
                except Exception:
                    continue

                if state == "stopped":
                    if self.handler_active:
                        self.handler_active = False
                        self._last_rating_key = None
                        self.now_playing.clear_track_info()
                    return

                if state in ("playing", "paused"):
                    self.handler_active = True

                if state != "playing":
                    return

                if not rating_key or rating_key == self._last_rating_key:
                    return

                self._last_rating_key = rating_key

                item = self._plex.fetchItem(f"/library/metadata/{rating_key}")

                class FakeSession:
                    pass

                session = FakeSession()
                session.title = item.title
                session.type = item.type
                session.thumb = item.thumb
                session.parentTitle = getattr(item, "parentTitle", None)
                session.grandparentTitle = getattr(item, "grandparentTitle", None)
                session.studio = getattr(item, "studio", None)

                self._commit_track(session)

    def _on_ws_message(self, ws, message):
        try:
            data = json.loads(message)

            container = data.get("NotificationContainer")
            if not container:
                log.debug("Received non-notification websocket message")
                return

            log.debug(f"WS event type: {container.get('type')} message {message}")
            msg_type = container.get("type")

            if msg_type == "playing":
                self._handle_playing_event(container)

            elif msg_type == "activity" and not self._track_initialized:
                log.debug("Activity event before track initialized — checking sessions")
                threading.Timer(3, self._check_current_session).start()

        except Exception:
            log.exception("Websocket event handling failed")

    def _run_websocket(self, ws_url):
        while self._running:
            log.info("[WS] Starting websocket connection...")

            try:
                self._ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self._on_ws_message,
                    on_close=self._on_ws_close,
                    on_error=self._on_ws_error,
                )

                self._ws.run_forever(ping_interval=30, ping_timeout=10)

            except Exception as e:
                log.warning(f"[WS] Websocket crashed: {e}")

            if not self._running:
                break

            log.info("[WS] Websocket disconnected — retrying in 3 seconds...")
            time.sleep(3)

    def _on_ws_error(self, ws, error):
        log.warning(f"Plex websocket error: {error}")


    def _on_ws_close(self, ws, *args):
        log.warning("Plex websocket closed")

    def _commit_track(self, session):
        self._track_initialized = True
        media_type = session.type

        title = session.title
        artist = None
        album = None

        if media_type == "track":
            artist = session.grandparentTitle
            album = session.parentTitle
        else:
            artist = session.studio

        cover_art = self._fetch_artwork(session.thumb)

        if cover_art:
            cover_art = self._resize_album_art(cover_art)

        log.info(f"Now Playing (Plexamp): {artist} - {title}")

        self.now_playing.set_track_info(
            title,
            artist=artist,
            album=album,
            album_art=cover_art,
        )

    def _fetch_artwork(self, thumb_path):
        if not thumb_path:
            return None

        try:
            url = f"{self._plex_url}{thumb_path}?X-Plex-Token={self._plex_token}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()

            img = Image.open(io.BytesIO(response.content))
            img.load()
            return img.convert("RGBA")

        except Exception as e:
            log.warning(f"Failed to fetch artwork: {e}")
            return None

    def _resize_album_art(self, img: Image.Image) -> Image.Image:
        w, h = img.size

        if w > self.MAX_TEXTURE_SIZE or h > self.MAX_TEXTURE_SIZE:
            ratio = min(
                self.MAX_TEXTURE_SIZE / w,
                self.MAX_TEXTURE_SIZE / h
            )
            new_size = (int(w * ratio), int(h * ratio))
            log.debug(f"Resizing artwork {w}x{h} -> {new_size}")
            img = img.resize(new_size, Image.LANCZOS)

        return img

    #endregion

    #region Public Playback Functions

    def is_playing(self):
        if not self._plex:
            return False

        try:
            sessions = self._plex.sessions()

            for session in sessions:
                if session.player.title == self._plex_client:
                    return session.player.state == "playing"

            return False

        except Exception:
            log.exception("is_playing() failed")
            return False

    def play(self):
        client = self._get_client()
        if client:
            client.play()

    def pause(self):
        client = self._get_client()
        if client:
            client.pause()

    def stop(self):
        client = self._get_client()
        if client:
            client.stop(mtype='music')

        super().stop()

    def next(self):
        client = self._get_client()
        if client:
            client.skipNext()

    def previous(self):
        client = self._get_client()
        if client:
            client.skipPrevious()

    def volume_up(self):
        client = self._get_client()
        if client:
            client.setVolume(min(100, client.volume + 5))

    def volume_down(self):
        client = self._get_client()
        if client:
            client.setVolume(max(0, client.volume - 5))

    def toggle_mute(self):
        client = self._get_client()
        if client:
            client.mute(not client.isMuted)

    def get_playlist(self, addr=None):
        return []

    #endregion

    #region Main Component Functions

    async def run(self):
        try:
            log.info("Connecting to Plex server...")
            self._plex = PlexServer(self._plex_url, self._plex_token)

            ws_url = self._plex_url.replace("http", "ws")
            ws_url += f"/:/websockets/notifications?X-Plex-Token={self._plex_token}"

            log.info("Starting Plex websocket thread...")
            self._ws_thread = threading.Thread(target=self._run_websocket, args=(ws_url,))
            self._ws_thread.start()

            while self._running:
                await asyncio.sleep(0.5)

        except Exception:
            log.exception("Plexamp runtime error")
        finally:
            log.info("Plexamp thread exiting")

    async def close(self):
        self.stop()
        self.now_playing.clear_track_info()
        self.handler_active = False
    
        if hasattr(self, "_ws") and self._ws:
            self._ws.close()
    
        if hasattr(self, "_ws_thread") and self._ws_thread.is_alive():
            log.info("Waiting for websocket thread to exit...")
            self._ws_thread.join(timeout=5)

    #endregion