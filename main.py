
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from modules.premium_invite_engine import register_premium
import os

API_ID=int(os.getenv("API_ID"))
API_HASH=os.getenv("API_HASH")
SESSION=os.getenv("SESSION_STRING")

client=TelegramClient(StringSession(SESSION),API_ID,API_HASH)

@client.on(events.NewMessage(pattern=r"^\.start$"))
async def start(event):
    await event.reply("🔥 BmCodex Premium Userbot aktif")

register_premium(client)
client.start()
client.run_until_disconnected()
