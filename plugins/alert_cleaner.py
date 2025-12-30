import asyncio
from pyrogram import Client
from database.users_chats_db import db
from info import BUTTON_DELETE_TIME
import logging

logger = logging.getLogger(__name__)

# 3 hours in seconds
ALERT_DELETE_TIME = 10800

async def clean_alert_messages(client: Client):
    # Check every 1 minute
    while True:
        try:
            old_messages = await db.get_old_alert_messages(ALERT_DELETE_TIME)

            for msg in old_messages:
                chat_id = msg.get('chat_id')
                message_id = msg.get('message_id')
                _id = msg.get('_id')

                try:
                    await client.delete_messages(chat_id, message_id)
                except Exception as e:
                    # Message might already be deleted or other error
                    # logger.error(f"Error deleting alert message {chat_id}:{message_id} - {e}")
                    pass

                # Remove from DB regardless of whether deletion from Telegram was successful
                # (if it failed, it likely doesn't exist anymore or we can't delete it anyway)
                await db.delete_alert_message(_id)

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Error in clean_alert_messages loop: {e}")
            await asyncio.sleep(60)
