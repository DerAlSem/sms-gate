import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.config import settings
from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.api.router import router
from app.admin.router import router as admin_router
from app.modem.manager import ModemManager
from app.alerting import setup_telegram_alerts
from app.settings_store import store, seed_from_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

modem_manager = ModemManager(
    send_port=settings.serial_send_port,
    read_port=settings.serial_read_port,
    baudrate=settings.serial_baudrate,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db(settings.db_path)
    await run_migrations()
    logger.info("Database ready")

    await seed_from_env()
    await store.load()
    setup_telegram_alerts(store)
    from app.alerting import reconfigure as _alert_reconfigure
    store.on_change("Alerting", lambda: _alert_reconfigure(store))
    logger.info("Settings loaded")

    await modem_manager.connect()
    app.state.modem = modem_manager
    logger.info("Modem connected")

    await modem_manager.scan_inbox()

    tasks = [
        asyncio.create_task(modem_manager.sender_loop()),
        asyncio.create_task(modem_manager.reader_loop()),
        asyncio.create_task(modem_manager.inbound_loop()),
        asyncio.create_task(modem_manager.expire_loop()),
        asyncio.create_task(modem_manager.keepalive_loop()),
        asyncio.create_task(modem_manager.parts_flush_loop()),
    ]

    if store.telegram_replies_enabled and store.alert_bot_token and store.alert_chat_id:
        from app.telegram_poll import telegram_poll_loop
        tasks.append(asyncio.create_task(
            telegram_poll_loop(store.alert_bot_token, store.alert_chat_id, modem_manager)
        ))
        logger.info("Telegram reply polling enabled")

    yield

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await modem_manager.disconnect()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(title="SMS Gate", lifespan=lifespan)
app.include_router(router)
app.include_router(admin_router)
