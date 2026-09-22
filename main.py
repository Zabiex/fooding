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
            pass

    # 3. Explicit PTB Lifecycle Execution
    try:
        # Step A: Initialize the application internals
        await application.initialize()

        # Step B: Explicitly await post_init hook (populates bot_data['services'] and DB pool)
        if application.post_init:
            await application.post_init(application)

        # Step C: Start application & start polling for updates
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        print("Telegram bot started successfully and listening for messages.")

        # Block until SIGINT or SIGTERM is received
        await stop_event.wait()

    finally:
        print("Shutting down bot...")
        # Step D: Graceful stop sequence
        if application.updater and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()

        # Step E: Gracefully shut down aiohttp healthcheck server
        await runner.cleanup()
        print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())