import asyncio
import logging
import sys
import threading

log = logging.getLogger()

class AsyncService:

    # None means supported on all platforms; otherwise a set of sys.platform values (e.g. {"linux"}, {"win32"}, {"darwin"})
    SUPPORTED_PLATFORMS = None

    def __init__(self):
        self._loop = None
        self._thread = None
        self._main_task = None
        self._running = False

    @classmethod
    def is_supported(cls):
        return cls.SUPPORTED_PLATFORMS is None or sys.platform in cls.SUPPORTED_PLATFORMS

    #region Lifecycle

    def start(self):
        if self._running:
            return

        self._running = True

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._main_task = self._loop.create_task(self._run_wrapper())

        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name=self.__class__.__name__,
            daemon=True
        )
        self._thread.start()

        log.info(f"{self.__class__.__name__} started")

    def stop(self):
        if not self._running:
            return

        self._running = False

        if self._loop:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

    def is_running(self):
        return self._running

    #endregion

    #region Shutdown

    async def _run_wrapper(self):
        try:
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(f"{self.__class__.__name__} run() failed unexpectedly")

    async def _shutdown(self):

        if self._main_task:
            self._main_task.cancel()

            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        await self.close()

        if self._loop:
            self._loop.stop()

    #endregion

    #region Methods to Override

    async def run(self):
        raise NotImplementedError

    async def close(self):
        pass

    #endregion