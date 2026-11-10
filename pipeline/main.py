"""Standard workflow entrypoint; historical lifecycle helpers remain testable."""
import asyncio
from workflow_main import main

async def cleanup_workers(pending):
    while pending:
        await pending[-1].stop()
        pending.pop()


async def start_core_workers(candidates, pending):
    pending.extend(candidates)
    try:
        for worker in candidates:
            await worker.start()
    except BaseException:
        await cleanup_workers(pending)
        raise
    pending.clear()
    return candidates


async def stop_optional(optional, name):
    await optional[name].stop()
    del optional[name]


if __name__ == "__main__":
    asyncio.run(main())
