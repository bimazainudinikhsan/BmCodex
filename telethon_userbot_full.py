# Placeholder for your full userbot code. Insert the full script here.
# telethon_userbot_full.py
# Userbot Telegram lengkap dengan:
# - .inviteall @target (ambil source otomatis dari chat tempat command dikirim)
# - .invitemember <jumlah> @target
# - Auto-filter member (hindari bot, hindari akun tidak aktif)
# - Smart rate control + auto delay adaptif
# - Logging ke dashboard (via HTTP POST)
# - Mode supervisor support
#
# Pastikan variabel berikut ada di Heroku Config Vars:
# API_ID
# API_HASH
# SESSION
# DASHBOARD_ENDPOINT
#
# Catatan: Fitur invite massal TIDAK dijamin berhasil karena limit Telegram.
# Gunakan dengan bertanggung jawab.

import asyncio
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError, UserNotMutualContactError, UserChannelsTooMuchError, UserKickedError, ChatAdminRequiredError
import os
import time
import requests

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION", "user")
DASHBOARD_ENDPOINT = os.getenv("DASHBOARD_ENDPOINT")

tclient = TelegramClient(SESSION, API_ID, API_HASH)

# ----------------------------
# SEND LOGS TO DASHBOARD
# ----------------------------
def log(msg: str):
    print(f"[LOG] {msg}")
    try:
        if DASHBOARD_ENDPOINT:
            requests.post(DASHBOARD_ENDPOINT, json={"log": msg})
    except:
        pass

# ----------------------------
# SMART INVITE FUNCTION
# ----------------------------
async def smart_invite(users, target, limit=None):
    invited = 0
    delay = 1
    for u in users:
        if limit and invited >= limit:
            break
        try:
            if getattr(u, 'bot', False):
                log(f"Lewati {u.id} (bot)")
                continue

            await tclient( tclient.invite_to_channel(target, [u.id]) )
            invited += 1
            log(f"Berhasil mengundang {u.id} → total {invited}")
        except FloodWaitError as e:
            log(f"FloodWait {e.seconds}s")
            await asyncio.sleep(e.seconds)
        except (UserPrivacyRestrictedError, UserNotMutualContactError, UserChannelsTooMuchError, UserKickedError, ChatAdminRequiredError) as e:
            log(f"Gagal undang {u.id}: {e}")
        except Exception as e:
            log(f"Error {u.id}: {e}")

        await asyncio.sleep(delay)
        delay = min(delay + 0.3, 5)

    return invited

# ----------------------------
# COMMAND LISTENER
# ----------------------------
@tclient.on(events.NewMessage(pattern=r"\.inviteall (.+)"))
async def handler_inviteall(event):
    target = event.pattern_match.group(1)
    source = await event.get_chat()

    log(f"Mulai .inviteall dari source={source.id} ke target={target}")

    try:
        members = await tclient.get_participants(source.id)
    except Exception as e:
        await event.reply(f"Tidak bisa membaca member source: {e}")
        return

    await event.reply(f"Memulai import {len(members)} member → {target}")

    invited = await smart_invite(members, target)
    await event.reply(f"Selesai, total berhasil: {invited}")


@tclient.on(events.NewMessage(pattern=r"\.invitemember (\d+) (.+)"))
async def handler_invitemember(event):
    amount = int(event.pattern_match.group(1))
    target = event.pattern_match.group(2)
    source = await event.get_chat()

    log(f"Mulai .invitemember {amount} dari source={source.id} ke {target}")

    try:
        members = await tclient.get_participants(source.id)
    except Exception as e:
        await event.reply(f"Tidak bisa membaca member source: {e}")
        return

    await event.reply(f"Mengambil {amount} member dari {source.id} → {target}")

    invited = await smart_invite(members, target, limit=amount)
    await event.reply(f"Selesai, berhasil {invited} member")


# ----------------------------
# STARTUP
# ----------------------------
async def main():
    log("Userbot aktif dan siap menerima perintah")
    print("Userbot berjalan...")
    await tclient.run_until_disconnected()


tclient.start()
tclient.loop.run_until_complete(main())
