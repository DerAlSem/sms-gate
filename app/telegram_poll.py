"""Telegram long-poll loop: turns an operator's reply (to a notification post in the
configured channel) into an outbound SMS to the number that notification was about.

Long polling (getUpdates) is an outbound connection, so it works behind CGNAT where a
webhook could not. The bot must be an admin of the channel; channel posts are
admin-only, so updates from the configured chat are inherently operator-only.
"""

import asyncio
import logging

import httpx

from app.db import queries

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


async def _get_updates(token: str, offset: int, timeout: int):
    """One getUpdates call. Returns the list of update dicts (possibly empty)."""
    url = _API.format(token=token, method="getUpdates")
    params = {"offset": offset, "timeout": timeout,
              "allowed_updates": '["channel_post","message"]'}
    async with httpx.AsyncClient(timeout=timeout + 10) as client:
        resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("result", [])


async def _delete_webhook(token: str) -> None:
    url = _API.format(token=token, method="deleteWebhook")
    async with httpx.AsyncClient(timeout=10) as client:
        await client.get(url)


async def _drain_backlog(token: str) -> int:
    """Skip updates that arrived before startup: return last_update_id + 1 (0 if none)."""
    updates = await _get_updates(token, 0, 0)
    if not updates:
        return 0
    return updates[-1]["update_id"] + 1


async def _handle_update(update: dict, chat_id, modem) -> None:
    post = update.get("channel_post") or update.get("message")
    if not post:
        return
    if str(post.get("chat", {}).get("id")) != str(chat_id):
        return
    reply = post.get("reply_to_message")
    if not reply:
        return
    phone = await queries.find_notify_ref(reply.get("message_id"))
    if phone is None:
        logger.info("Telegram reply to unknown/expired notification, ignored")
        return
    text = post.get("text")
    if not text:
        return
    message_id = await queries.create_message("telegram", phone, text)
    await modem.enqueue(message_id, phone, text, "telegram")
    logger.info("Telegram reply -> SMS id=%d to=%s", message_id, phone)


async def telegram_poll_loop(token: str, chat_id, modem, *, timeout: int = 30) -> None:
    """Poll Telegram for replies and turn them into SMS. Never returns."""
    logger.info("Telegram poll loop started")
    try:
        await _delete_webhook(token)
    except Exception:
        logger.warning("deleteWebhook failed (continuing)", exc_info=True)
    offset = 0
    try:
        offset = await _drain_backlog(token)
    except Exception:
        logger.warning("Backlog drain failed (continuing)", exc_info=True)
    while True:
        try:
            updates = await _get_updates(token, offset, timeout)
            for update in updates:
                offset = update["update_id"] + 1
                await _handle_update(update, chat_id, modem)
        except Exception:
            logger.exception("Telegram poll error; backing off")
            await asyncio.sleep(5)
