"""Separate experimental worker; no Kafka consumers or public ports."""

import asyncio
import logging
import signal
from app.workflows.engine import Engine

logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":

    async def main():
        engine = Engine()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, lambda: setattr(engine, "stopping", True))
        await engine.run()

    asyncio.run(main())
