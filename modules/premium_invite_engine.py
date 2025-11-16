
import asyncio, json, time, random, os
from telethon import events
from telethon.tl.functions.channels import InviteToChannelRequest, GetFullChannelRequest
from telethon.errors import (
    FloodWaitError,
    UserPrivacyRestrictedError,
    UserAlreadyParticipantError,
    ChatAdminRequiredError,
    UserBannedInChannelError,
    ChannelPrivateError,
    UserNotMutualContactError,
    ChatWriteForbiddenError,
    PeerIdInvalidError,
    ValueError as TeleValueError
)
from telethon.tl.types import ChannelParticipantsAdmins

DB = 'database.json'
LOG = 'premium.log'

# ----------------- Database helpers -----------------
def load_db():
    try:
        with open(DB, 'r') as f:
            return json.load(f)
    except Exception:
        return {
            'invited': [],     # list of user ids successfully invited/added
            'fails': {},       # map userid -> reason
            'processed': [],   # all processed ids (mode C)
            'cooldown': {},    # map userid -> unix timestamp until skip
            'meta': {}
        }

def save_db(data):
    with open(DB, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def log(msg):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}\n'
    try:
        with open(LOG, 'a', encoding='utf8') as f:
            f.write(line)
    except:
        pass
    print(line, end='')

# ----------------- Utility -----------------
def chunked_iterable(iterable, size):
    it = iter(iterable)
    while True:
        chunk = []
        for _ in range(size):
            try:
                chunk.append(next(it))
            except StopIteration:
                break
        if not chunk:
            break
        yield chunk

# ----------------- Register premium handlers -----------------
def register_premium(client, owner_id=0):
    """Register premium invite commands on given telethon client."""

    @client.on(events.NewMessage(pattern=r'^\.status$'))
    async def status(event):
        db = load_db()
        text = ('🔥 BmCodex Premium Status\n\n'
                f'Total invited: {len(db.get("invited", []))}\n'
                f'Total processed: {len(db.get("processed", []))}\n'
                f'Total failed entries: {len(db.get("fails", {}))}\n')
        await event.reply(text)

    @client.on(events.NewMessage(pattern=r'^\.ping$'))
    async def ping(event):
        await event.reply('pong')

    @client.on(events.NewMessage(pattern=r'^\.premiuminvite(?:\s+(\S+))?$'))
    async def premium_invite(event):
        """Premium invite command.

        Usage:
          .premiuminvite @target
        Optional: supply @target or channel id. If not provided, uses last target in DB meta.
        """
        args = event.text.split()
        if len(args) < 2:
            target = None
        else:
            target = args[1].strip()

        db = load_db()
        last_target = db.get('meta', {}).get('last_target')

        if not target:
            if last_target:
                target = last_target
            else:
                return await event.reply('❌ Target required. Format: .premiuminvite @target')

        # save last target
        db.setdefault('meta', {})['last_target'] = target
        save_db(db)

        source = event.chat_id
        # gather queue from participants (supergroup allowed)
        queue = []
        async for user in client.iter_participants(source, aggressive=True):
            if getattr(user, 'bot', False):
                continue
            if user.deleted:
                # mark processed deleted accounts
                db.setdefault('processed', []).append(user.id)
                db.setdefault('fails', {})[str(user.id)] = 'deleted'
                save_db(db)
                continue
            if user.id in db.get('processed', []):
                continue
            queue.append({'id': user.id, 'username': getattr(user, 'username', None)})

        total = len(queue)
        await event.reply(f'🚀 Premium invite starting — queue {total} users (source: {source})')
        log(f'Premium invite started. source={source} target={target} total={total}')

        # Parameters — adaptive
        base_delay = 1.5  # initial safe delay (seconds)
        min_delay = 0.8
        max_delay = 25
        warmup_count = 20
        batch_size = 5      # use small batches for InviteToChannelRequest where supported
        cooldown_every = 25 # after these many invites, perform longer sleep
        cooldown_seconds = 10

        invited_count = 0
        consecutive_errors = 0

        # rotate queue in chunks to avoid heavy bursts
        for chunk in chunked_iterable(queue, batch_size):
            ids = [u['id'] for u in chunk]
            # skip ids that became processed while building queue
            ids = [i for i in ids if i not in db.get('processed', [])]
            if not ids:
                continue
            try:
                # attempt to invite chunk (some APIs accept list)
                await client(InviteToChannelRequest(target, ids))
                for uid in ids:
                    db.setdefault('invited', []).append(uid)
                    db.setdefault('processed', []).append(uid)
                save_db(db)

                invited_count += len(ids)
                consecutive_errors = 0
                log(f'Invited batch {ids}')

                # warmup behavior
                if invited_count < warmup_count:
                    await asyncio.sleep(base_delay + random.random())  # slightly randomized
                else:
                    # gradually speed up but remain safe
                    delay = max(min_delay, base_delay * (0.7 if invited_count > warmup_count else 1.0))
                    delay = min(delay, max_delay)
                    # small jitter to avoid patterns
                    await asyncio.sleep(delay + random.random()*0.5)

            except FloodWaitError as e:
                # adaptive sleep
                wait = min(e.seconds, 3600)  # cap 1 hour
                log(f'FloodWaitError detected: sleeping {wait}s')
                await event.reply(f'⏳ Flood wait {wait}s — pausing...')
                await asyncio.sleep(wait + 5)
                consecutive_errors = 0  # reset

            except UserPrivacyRestrictedError as e:
                # individual privacy — mark each id as private
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'privacy'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                consecutive_errors += 1
                log(f'Privacy blocked for ids: {ids}')

            except UserAlreadyParticipantError:
                # some were already participants — mark processed
                for uid in ids:
                    if uid not in db.get('processed', []):
                        db.setdefault('processed', []).append(uid)
                save_db(db)
                log(f'Already participants: {ids}')

            except ChatAdminRequiredError:
                await event.reply('❌ Bot/account needs admin privileges in target! Aborting.')
                log('ChatAdminRequiredError — aborting')
                return

            except UserBannedInChannelError:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'banned'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                log(f'UserBannedInChannel for ids {ids} — flagged')

            except ChannelPrivateError:
                await event.reply('❌ Source or target is private/unavailable. Aborting.')
                log('ChannelPrivateError — abort')
                return

            except UserNotMutualContactError:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'not_mutual'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                consecutive_errors += 1
                log(f'Not mutual contacts: {ids}')

            except PeerIdInvalidError:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'invalid_peer'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                consecutive_errors += 1
                log(f'PeerIdInvalid for {ids}')

            except Exception as e:
                # catch-all — record and move on
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = f'error:{type(e).__name__}'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                consecutive_errors += 1
                log(f'General exception for ids {ids}: {e}')

            # smart cooldown after some invites
            if invited_count and invited_count % cooldown_every == 0:
                log(f'Cooling down for {cooldown_seconds}s after {invited_count} invites')
                await asyncio.sleep(cooldown_seconds + random.random()*3)

            # if many consecutive errors, do a longer sleep and rotate
            if consecutive_errors >= 3:
                s = min(300, 20 * consecutive_errors)
                log(f'Consecutive errors detected ({consecutive_errors}), sleeping {s}s')
                await asyncio.sleep(s)

        await event.reply(f'🎉 Premium invite finished. Invited: {invited_count} — Failed entries: {len(db.get("fails", {}))}')
        log(f'Premium invite finished. invited={invited_count} fails={len(db.get("fails", {}))}')

        # optional notify owner
        try:
            if owner_id:
                await client.send_message(owner_id, f'Premium invite finished. Invited: {invited_count}, failed: {len(db.get("fails", {}))}')
        except Exception:
            pass

    # status of db and logs
    @client.on(events.NewMessage(pattern=r'^\.dblog$'))
    async def dblog(event):
        db = load_db()
        await event.reply(f'JSON DB saved entries: invited={len(db.get("invited", []))} processed={len(db.get("processed", []))} failed={len(db.get("fails", {}))}')

