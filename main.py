"""Entry point: `python main.py`.

Runs the Telegram bot alongside a lightweight aiohttp healthcheck server
so hosting platforms (e.g. Render) can probe the service.
"""

import os
import asyncio
import signal
from aiohttp import web

from calorie_bot.bot.app import build_application, register_handlers


async def handle_healthcheck(request: web.Request) -> web.Response:
    return web.Response(text="OK", status=200)


async def main() -> None:
    port = int(os.getenv("PORT", "10000"))

    # 1. Build application and register handlers
    application = build_application()
    register_handlers(application)

    # 2. Set up aiohttp healthcheck server
    web_app = web.Application()
    web_app.router.add_get("/", handle_healthcheck)
    web_app.router.add_get("/health", handle_healthcheck)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Healthcheck HTTP server running on port {port}")

    # Event used to signal shutdown
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Signal handlers aren't implemented on some platforms (e.g. Windows)
            pass

    # 3. Lifecycle management for PTB and aiohttp with graceful cleanup
    try:
        # `async with application` calls initialize() and shutdown() automatically
        async with application:
            await application.start()
            await application.updater.start_polling()

            # Wait until SIGINT or SIGTERM is received
            await stop_event.wait()

            # Gracefully stop polling updates and stop the application
            await application.updater.stop()
            await application.stop()
    finally:
        # Gracefully shut down the aiohttp healthcheck server
        await runner.cleanup()
        print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
