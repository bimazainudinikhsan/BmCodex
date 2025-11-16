
import asyncio, json, time, random, os, shutil
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
    RPCError
)
from telethon.tl.types import ChannelParticipantsAdmins

DB = os.getenv('DB_FILE', 'database.json')
LOG = os.getenv('LOG_FILE', 'premium.log')
BACKUP_DIR = os.getenv('BACKUP_DIR', 'db_backups')
OWNER_ID = int(os.getenv('OWNER_ID') or 0)

# ----------------- Database helpers -----------------
def load_db():
    try:
        with open(DB, 'r', encoding='utf8') as f:
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
    tmp = DB + '.tmp'
    with open(tmp, 'w', encoding='utf8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DB)

def backup_db_if_needed(data):
    # Backup every 100 successful invites
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        count = len(data.get('invited', []))
        last = data.get('meta', {}).get('last_backup_count', 0)
        if count - last >= 100:
            ts = time.strftime('%Y%m%d_%H%M%S')
            path = os.path.join(BACKUP_DIR, f'db_backup_{ts}.json')
            shutil.copy2(DB, path)
            data.setdefault('meta', {})['last_backup_count'] = count
            save_db(data)
            log(f'Backup created: {path} (invited={count})')
    except Exception as e:
        log(f'Backup failed: {e}')

def log(msg):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}\\n'
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

def classify_exception(exc):
    name = type(exc).__name__
    if isinstance(exc, FloodWaitError):
        return 'flood'
    if isinstance(exc, UserPrivacyRestrictedError):
        return 'privacy'
    if isinstance(exc, UserAlreadyParticipantError):
        return 'already'
    if isinstance(exc, UserBannedInChannelError):
        return 'banned'
    if isinstance(exc, ChannelPrivateError):
        return 'channel_private'
    if isinstance(exc, UserNotMutualContactError):
        return 'not_mutual'
    if isinstance(exc, PeerIdInvalidError):
        return 'invalid_peer'
    return name.lower()

# ----------------- Adaptive delay engine -----------------
class AdaptiveDelay:
    def __init__(self, base=1.2, min_delay=0.6, max_delay=30.0):
        self.base = base
        self.min = min_delay
        self.max = max_delay
        self.history = []  # store recent tuples (success:bool, duration, exc_type)
        self.window = 50

    def record(self, success, duration=0.0, exc_type=None):
        self.history.append((success, duration, exc_type))
        if len(self.history) > self.window:
            self.history.pop(0)

    def get_delay(self):
        # heuristic: more recent errors => increase delay
        if not self.history:
            return self.base
        errors = sum(1 for s,d,e in self.history if not s)
        error_ratio = errors / len(self.history)
        # map error_ratio to delay factor
        factor = 1.0 + error_ratio*4.0
        delay = min(max(self.base * factor, self.min), self.max)
        # jitter
        return delay + random.random()*0.6

# ----------------- Register premium handlers -----------------
def register_premium(client, owner_id=0):
    owner = owner_id or OWNER_ID

    @client.on(events.NewMessage(pattern=r'^\\.status$'))
    async def status(event):
        db = load_db()
        text = ('🔥 BmCodex Premium Status\\n\\n'
                f'Total invited: {len(db.get(\"invited\", []))}\\n'
                f'Total processed: {len(db.get(\"processed\", []))}\\n'
                f'Total failed entries: {len(db.get(\"fails\", {}))}\\n')
        await event.reply(text)

    @client.on(events.NewMessage(pattern=r'^\\.ping$'))
    async def ping(event):
        await event.reply('pong')

    # ----------------- inviteall (replaces premiuminvite) -----------------
    @client.on(events.NewMessage(pattern=r'^\\.inviteall(?:\\s+(\\S+))?$'))
    async def invite_all(event):
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
                return await event.reply('❌ Target required. Format: .inviteall @target')

        db.setdefault('meta', {})['last_target'] = target
        save_db(db)

        source = event.chat_id
        queue = []
        async for user in client.iter_participants(source, aggressive=True):
            if getattr(user, 'bot', False):
                continue
            if user.deleted:
                db.setdefault('processed', []).append(user.id)
                db.setdefault('fails', {})[str(user.id)] = 'deleted'
                save_db(db)
                continue
            if user.id in db.get('processed', []):
                continue
            queue.append({'id': user.id, 'username': getattr(user, 'username', None)})

        total = len(queue)
        await event.reply(f'🚀 InviteAll starting — queue {total} users (source: {source})')
        log(f'InviteAll started. source={source} target={target} total={total}')

        # adaptive and batching params
        delay_engine = AdaptiveDelay(base=1.2, min_delay=0.6, max_delay=30.0)
        batch_size = 6
        warmup = True
        invited_count = 0
        consecutive_errors = 0

        for chunk in chunked_iterable(queue, batch_size):
            ids = [u['id'] for u in chunk if u['id'] not in db.get('processed', [])]
            if not ids:
                continue
            start_ts = time.time()
            try:
                await client(InviteToChannelRequest(target, ids))
                duration = time.time() - start_ts
                for uid in ids:
                    db.setdefault('invited', []).append(uid)
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                invited_count += len(ids)
                delay_engine.record(True, duration)
                consecutive_errors = 0
                log(f'Invited batch: {ids}')

                # backup if needed
                backup_db_if_needed(db)

                # warmup behavior -> slower initially
                if invited_count < 20 and warmup:
                    await asyncio.sleep(delay_engine.get_delay())
                else:
                    await asyncio.sleep(max(0.6, delay_engine.get_delay()/1.5))

            except FloodWaitError as e:
                wait = min(e.seconds, 3600)
                log(f'FloodWaitError: sleeping {wait}s')
                await event.reply(f'⏳ Flood wait {wait}s — pausing...')
                delay_engine.record(False, 0.0, 'flood')
                await asyncio.sleep(wait + 5)
                consecutive_errors = 0

            except UserPrivacyRestrictedError:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'privacy'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                delay_engine.record(False, 0.0, 'privacy')
                consecutive_errors += 1
                log(f'Privacy blocked for ids: {ids}')

            except UserAlreadyParticipantError:
                for uid in ids:
                    if uid not in db.get('processed', []):
                        db.setdefault('processed', []).append(uid)
                save_db(db)
                delay_engine.record(False, 0.0, 'already')
                log(f'Already participants in batch: {ids}')

            except ChatAdminRequiredError:
                await event.reply('❌ Bot/account needs admin privileges in target! Aborting.')
                log('ChatAdminRequiredError — aborting')
                return

            except UserBannedInChannelError:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'banned'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                delay_engine.record(False, 0.0, 'banned')
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
                delay_engine.record(False, 0.0, 'not_mutual')
                consecutive_errors += 1
                log(f'Not mutual contacts: {ids}')

            except PeerIdInvalidError:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = 'invalid_peer'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                delay_engine.record(False, 0.0, 'invalid_peer')
                consecutive_errors += 1
                log(f'PeerIdInvalid for {ids}')

            except Exception as e:
                for uid in ids:
                    db.setdefault('fails', {})[str(uid)] = f'error:{type(e).__name__}'
                    db.setdefault('processed', []).append(uid)
                save_db(db)
                delay_engine.record(False, 0.0, type(e).__name__)
                consecutive_errors += 1
                log(f'General exception for ids {ids}: {e}')

            # smart cooldown after some invites
            if invited_count and invited_count % 25 == 0:
                log(f'Cooling down for 10s after {invited_count} invites')
                await asyncio.sleep(10 + random.random()*3)

            # if many consecutive errors, do a longer sleep and rotate
            if consecutive_errors >= 3:
                s = min(300, 20 * consecutive_errors)
                log(f'Consecutive errors detected ({consecutive_errors}), sleeping {s}s')
                await asyncio.sleep(s)

        await event.reply(f'🎉 InviteAll finished. Invited: {invited_count} — Failed entries: {len(db.get(\"fails\", {}))}')
        log(f'InviteAll finished. invited={invited_count} fails={len(db.get(\"fails\", {}))}')

        # notify owner if set
        try:
            if owner:
                await client.send_message(owner, f'InviteAll finished. Invited: {invited_count}, failed: {len(db.get(\"fails\", {}))}')
        except Exception:
            pass

    # ----------------- invitemember limited -----------------
    @client.on(events.NewMessage(pattern=r'^\\.invitemember(?:\\s+(\\d+)\\s+(\\S+))?$'))
    async def invitemember(event):
        args = event.text.split()
        if len(args) < 3:
            return await event.reply('Format: .invitemember 10 @target')
        try:
            limit = int(args[1])
        except:
            return await event.reply('Jumlah tidak valid. Contoh: .invitemember 10 @target')
        target = args[2].strip()

        db = load_db()
        source = event.chat_id
        invited_count = 0
        queue = []
        async for user in client.iter_participants(source, aggressive=True):
            if getattr(user, 'bot', False): continue
            if user.id in db.get('processed', []): continue
            queue.append(user.id)
            if len(queue) >= limit:
                break

        if not queue:
            return await event.reply('Tidak ada user yang bisa di-invite.')

        log(f'Invitemember starting: limit={limit} target={target}')
        delay_engine = AdaptiveDelay()
        for uid in queue:
            try:
                await client(InviteToChannelRequest(target, [uid]))
                db.setdefault('invited', []).append(uid)
                db.setdefault('processed', []).append(uid)
                save_db(db)
                invited_count += 1
                delay_engine.record(True)
                backup_db_if_needed(db)
                await asyncio.sleep(delay_engine.get_delay())

            except FloodWaitError as e:
                wait = min(e.seconds, 3600)
                log(f'FloodWait in invitemember: sleeping {wait}s')
                await asyncio.sleep(wait + 5)
            except UserPrivacyRestrictedError:
                db.setdefault('fails', {})[str(uid)] = 'privacy'
                db.setdefault('processed', []).append(uid)
                save_db(db)
            except UserAlreadyParticipantError:
                db.setdefault('processed', []).append(uid)
                save_db(db)
            except Exception as e:
                db.setdefault('fails', {})[str(uid)] = f'error:{type(e).__name__}'
                db.setdefault('processed', []).append(uid)
                save_db(db)
                log(f'Invitemember error for {uid}: {e}')

        await event.reply(f'✅ Invited {invited_count}/{limit} users.')
        try:
            if owner:
                await client.send_message(owner, f'Invitemember finished: invited {invited_count}/{limit} to {target}')
        except:
            pass

    # ----------------- misc commands -----------------
    @client.on(events.NewMessage(pattern=r'^\\.dblog$'))
    async def dblog(event):
        db = load_db()
        await event.reply(f'JSON DB entries: invited={len(db.get(\"invited\", []))} processed={len(db.get(\"processed\", []))} failed={len(db.get(\"fails\", {}))}')

