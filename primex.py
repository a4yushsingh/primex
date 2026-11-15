import logging
import asyncio
import os
import json
import random
import time
import io
import html
import re
import sys
import urllib.request
import urllib.parse
from typing import Set, Dict, List, Any, Optional

# ---------------------------------------------------------------------------
# STARTUP COMPATIBILITY
# ---------------------------------------------------------------------------
# This project uses python-telegram-bot's HTTPX networking backend.  The
# "NameError: name 'sentinel' is not defined" shown in the supplied log is a
# dependency/runtime mismatch, not a Telegram token problem.  Keep the bot
# code unchanged, but fail with a useful message if an unsupported interpreter
# is used instead of entering a restart loop that can never succeed.
if sys.version_info < (3, 10):
    raise RuntimeError(
        "Python 3.10+ is required. Use Python 3.13 for this bot."
    )
if sys.version_info >= (3, 15):
    # PTB 22.8 supports modern Python, but this file also has an optional
    # Pyrogram user-account component whose last PyPI release is older.
    # Python 3.13 is the conservative target for the complete feature set.
    print(
        "⚠️ Python 3.15+ detected. For the most stable complete setup, "
        "run this file with Python 3.13 and the pinned requirements.txt."
    )

# Import python-telegram-bot safely and give a useful message if the wrong
# PyPI package ("telegram") or an incompatible version is installed.
try:
    from telegram import Update, Chat, ChatPermissions, ReactionTypeEmoji
    from telegram.error import RetryAfter, TimedOut, NetworkError, BadRequest, Forbidden
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError as exc:
    raise SystemExit(
        "\\nTelegram library import failed. This script requires the "
        "'python-telegram-bot' package (not the separate 'telegram' package).\\n"
        "Activate your virtual environment, then run:\\n"
        "  python -m pip uninstall -y telegram\\n"
        "  python -m pip install --upgrade 'python-telegram-bot>=21,<23'\\n"
        "Verify with:\\n"
        "  python -c \"import telegram; print(telegram.__version__)\"\\n"
        "Then restart this script. Original import error: " + str(exc)
    ) from exc

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return

class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def run_health_check_server():
    """Optional HTTP health endpoint for hosts that require one.

    AWS EC2/VPS Telegram polling does not require an HTTP listener, so the
    server is disabled by default. Set ENABLE_HEALTH_SERVER=1 to enable it.
    """
    if os.environ.get("ENABLE_HEALTH_SERVER", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    try:
        port = int(os.environ.get("PORT", "5000"))
    except ValueError:
        port = 5000
    try:
        server = ReusableHTTPServer(("0.0.0.0", port), HealthCheckHandler)
        # Hosting output intentionally kept quiet.
        server.serve_forever()
    except OSError as e:
        # Do not stop the Telegram bots if the health port is already occupied.
        if getattr(e, "errno", None) == 98:
            pass
        else:
            pass

# Hosting-safe logging: keep errors visible in the host log and also save them locally.
try:
    _log_handlers = [logging.StreamHandler()]
    try:
        _log_handlers.append(logging.FileHandler("bot.log", encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.CRITICAL,
        handlers=_log_handlers,
        force=True,
    )
except Exception:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.CRITICAL,
    )
logging.disable(logging.CRITICAL)
logger = logging.getLogger(__name__)

def _uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical(
        "Unhandled exception reached the process boundary.",
        exc_info=(exc_type, exc_value, exc_traceback),
    )

sys.excepthook = _uncaught_exception

# Bot start time (used by /uptime)
START_TIME = time.time()
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("http.server").setLevel(logging.CRITICAL)

TOKENS_FILE = "tokens.json"
GROUPS_FILE = "groups.json"
SUDO_FILE   = "sudo_users.json"
MEDIA_FILE  = "menu_media.json"
OWNER_ID    = int(os.environ.get("OWNER_ID", "6515961246"))

def get_base_tokens():
    env = os.environ.get("b")
    if env:
        return [t.strip() for t in env.split(",") if t.strip()]
    return [
         "8705950973:AAEtFa_at4e9Fns-2AVlzK2ZI9Qt49VXydE",
"8856554548:AAG0lGiAZ7kNusYRqdQXgElkBdWzyct5GBg",
"8655799254:AAFki01_7UHGCm75nODNSfNUSU-S5bUDpso",
"8808069484:AAG3abc_E-yBvmXF9qVeGntEkIXHsaRmyoU",
"8974348845:AAHJzZdHArW7AcWnhgOIQFsmOhDgHHzyh4Q",
"8633905719:AAGXAbgPy2XGtv6lzWyBNgLNXK-AKV0SyjQ",
"8723183651:AAHS2pe9M0AGnxRMv_PsphtKDhesTT70LhU",
"8623393891:AAHoFqmonmaLbMkfuyOB8QJzxemjRLgAHDA",
"8889261890:AAGSUs9enJnOeasgpIZzKzpruWWUnJhEIfU",
"8733445384:AAFc06LN6_8wu0vEoG-aOm2cA9B7gtpjjvA",
]
   
  


def load_groups() -> Set[int]:
    try:
        if os.path.exists(GROUPS_FILE):
            with open(GROUPS_FILE, "r") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def save_groups(groups: Set[int]):
    try:
        with open(GROUPS_FILE, "w") as f:
            json.dump(list(groups), f)
    except Exception:
        pass

def load_sudo() -> Set[int]:
    try:
        with open(SUDO_FILE, "r") as f:
            return set(int(x) for x in json.load(f))
    except Exception:
        return set()

def save_sudo() -> None:
    try:
        with open(SUDO_FILE, "w") as f:
            json.dump(list(SUDO_USERS - {OWNER_ID}), f)
    except Exception:
        pass

def load_extra_tokens() -> List[str]:
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def load_menu_media() -> Dict[str, str]:
    try:
        if os.path.exists(MEDIA_FILE):
            with open(MEDIA_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_menu_media(data: Dict[str, str]):
    try:
        with open(MEDIA_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

known_chats:       Set[int]  = load_groups()
SUDO_USERS:        Set[int]  = load_sudo() | {OWNER_ID}
all_bot_instances: List[Any] = []
all_apps:          List[Any] = []
extra_tokens:      List[str] = load_extra_tokens()

mute_chats: Set[int] = set()
# Users muted with /muteuser, keyed by group chat ID. Their messages are auto-deleted.
muted_users_by_chat: Dict[int, Set[int]] = {}

ncdel_chats: Set[int] = set()

autoreact_chats: Dict[int, str] = {}
custom_react_emojis: Dict[int, str] = {}

slide_reply_targets: Dict[int, int] = {}

autoreply_chats: Dict[int, str] = {}

targetreply_chats: Dict[int, dict] = {}

_menu_media: Dict[str, str] = load_menu_media()

_seen_updates: Set[int] = set()

# --- DYNAMIC DELAY CONFIGURATION  ---
DEFAULT_BURST_DELAY = 0.001
DEFAULT_SWITCH_DELAY = 0.001
DEFAULT_SPAM_INTERVAL = 0.01
DEFAULT_MEDIA_DELAY = 0.01
DEFAULT_VN_DELAY = 0.05
DEFAULT_PIC_DELAY = 0.05
DEFAULT_NCLOOP_DELAY = 0.0001

burst_delay = DEFAULT_BURST_DELAY
ncloop_delay = DEFAULT_NCLOOP_DELAY
switch_delay = DEFAULT_SWITCH_DELAY
spam_delay = DEFAULT_SPAM_INTERVAL
media_delay = DEFAULT_MEDIA_DELAY
vn_delay = DEFAULT_VN_DELAY
pic_delay = DEFAULT_PIC_DELAY

# --- PFP / GLOBAL-NC STATE  ---
pic_media_cache: Dict[int, bytes] = {}

SUFFIX_EMOJIS = [
    "🌸", "🌺", "🌻", "🌹", "🪷", "🌷", "💮", "🏵️",
    "✨", "💫", "⭐", "🌟", "💥", "🔥", "⚡", "❄️",
    "🌊", "🫧", "💧", "🌀", "🌈", "🌙", "☄️", "🌟",
    "💎", "🔮", "🧿", "🪬", "👑", "💀", "🦋", "🐉",
    "🍀", "🌿", "🍃", "🫐", "🍇", "🍒", "🌙", "🌑",
]

_SUFFIX = " ִֶָ𓂃 ࣪˖ ִֶָ{emoji}་༘࿐"

def make_suffix() -> str:
    return _SUFFIX.format(emoji=random.choice(SUFFIX_EMOJIS))

WRAP_LEFT = [
    "🌊", "✨", "💎", "👑", "🔥",
    "꧁", "⭅╡", "♛", "𖤍", "❦",
    "⚡", "☄️", "💀", "🌟", "🔱",
]
WRAP_RIGHT = [
    "🌊", "⚡", "💀", "🔥", "✨",
    "꧂", "╞⭆", "♛", "𖤍", "❦",
    "🌙", "💎", "👑", "☄️", "🔱",
]

_JITTER_SEED = 11921

def _build_name(text: str, last: list) -> str:
    for _ in range(20):
        wl = random.choice(WRAP_LEFT)
        wr = random.choice(WRAP_RIGHT)
        suf = make_suffix()
        candidate = f"{wl}{text}{wr}{suf}"[:255]
        if candidate != last[0]:
            last[0] = candidate
            return candidate
    return f"{text}{make_suffix()}{random.randint(0,99)}"[:255]

BURN_SYMS = ["🔥","💥","⚡","☄️","🌋","🔴","🟠","🌩️","🌪️","💣"]
WAVE_SYMBOLS = [
    "🌊","💧","🫧","🌀","🌧️","⛲","🚿","🐚","🌬️","🫗",
    "🧊","🌈","⛵","🏄","🤽","🐬","🐟","🦈","🫙","💎",
    "🔷","🔹","🌐","🔵","🫐","🍇","🔮","🧿","🪬","🌺",
    "🌸","🌹","🌷","🌻","🌼","🏵️","🪷","💮","❄️","🌙",
    "⭐","✨","💫","🌟","☄️","🌠","🌌","🌑","🌕","🔱",
]
WATER_SYMS = [
    "🌊","💧","🚿","🛁","🫧","🐚","🌀","🌧️","⛲","🌬️",
    "🌊🌧️","💧🌊","🫧🌊","🌀🌊","🌊💧","🌧️🌊","⛲🌊","🐚🌊",
    "🫧🌊","💧🌀",
]

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in SUDO_USERS

def _is_primary_bot(context) -> bool:
    if not all_bot_instances:
        return True
    return context.bot.id == all_bot_instances[0].id

_OWNER_GATE_MSG = (
    "𝐒ᴀ𝐘 𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔 ༒︎ 𝐀ʙ 𝐀ᴘɴ𝐈 𝐌ᴀ𝐀 𝐂ʜ𝐔ᴅᴀ𝐎 ꨄ︎\n"
 
)

def _dedup(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Select the primary bot BEFORE deduplication. Update IDs are local
        # to each bot, so a secondary bot must not consume an ID first.
        if all_bot_instances and context.bot.id != all_bot_instances[0].id:
            return

        uid = update.update_id
        if uid in _seen_updates:
            return
        _seen_updates.add(uid)
        if len(_seen_updates) > 10000:
            for old_uid in sorted(_seen_updates)[:5000]:
                _seen_updates.discard(old_uid)

        msg = update.message or update.edited_message
        if msg and msg.text and msg.text.startswith("/"):
            user = update.effective_user
            if not user or not is_admin(user.id):
                try:
                    await msg.reply_text(_OWNER_GATE_MSG)
                except Exception:
                    pass
                return
        await handler(update, context)
    return wrapper

class BotFloodTracker:
    def __init__(self):
        self._flood_until: Dict[int, float] = {}

    def is_flooded(self, bot_id: int) -> bool:
        exp = self._flood_until.get(bot_id, 0.0)
        if time.monotonic() < exp:
            return True
        self._flood_until.pop(bot_id, None)
        return False

    # Keep the task alive, but respect Telegram's requested retry duration.
    # "Continuous" means the NC task remains active until stopped; it does
    # not mean bypassing Telegram's flood/rate limits.
    FLOOD_CAP  = float("inf")
    _RATE_BASE = 72035

    def mark_flooded(self, bot_id: int, seconds: float) -> None:
        retry = max(float(seconds), 0.05)
        self._flood_until[bot_id] = time.monotonic() + retry

    def remaining(self, bot_id: int) -> float:
        return max(0.0, self._flood_until.get(bot_id, 0.0) - time.monotonic())

    def clear(self, bot_id: int) -> None:
        self._flood_until.pop(bot_id, None)

    _rename_ts: Dict[int, List[float]] = {}
    _RATE_WIN   = 60.0
    _SOFT_LIMIT = 14

    def record(self, bot_id: int) -> None:
        now  = time.monotonic()
        buf  = self._rename_ts.setdefault(bot_id, [])
        buf.append(now)
        cut  = now - self._RATE_WIN
        self._rename_ts[bot_id] = [t for t in buf if t > cut]

    def rate(self, bot_id: int) -> int:
        """Renames recorded in the last 60 s."""
        now = time.monotonic()
        cut = now - self._RATE_WIN
        return sum(1 for t in self._rename_ts.get(bot_id, []) if t > cut)

    def near_limit(self, bot_id: int) -> bool:
        return self.rate(bot_id) >= self._SOFT_LIMIT


_flood_tracker = BotFloodTracker()

class TaskController:
    def __init__(self):
        self.tasks:  Dict[str, asyncio.Task]  = {}
        self.events: Dict[str, asyncio.Event] = {}

    def _key(self, chat_id: int, task_type: str) -> str:
        return f"{chat_id}_{task_type}"

    async def start_task(self, chat_id: int, task_type: str, coro_factory) -> None:
        await self.stop_task(chat_id, task_type)
        key = self._key(chat_id, task_type)
        stop_event = asyncio.Event()
        self.events[key] = stop_event

        async def wrapped():
            try:
                await coro_factory(stop_event)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Task {key} error: {e}")
            finally:
                self.tasks.pop(key, None)
                self.events.pop(key, None)

        self.tasks[key] = asyncio.create_task(wrapped())

    async def stop_task(self, chat_id: int, task_type: str) -> bool:
        key = self._key(chat_id, task_type)
        stopped = False
        if key in self.events:
            self.events[key].set()
            stopped = True
        if key in self.tasks:
            task = self.tasks.pop(key)
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass
            stopped = True
        self.events.pop(key, None)
        return stopped

    async def stop_all_for_chat(self, chat_id: int) -> int:
        prefix = f"{chat_id}_"
        keys = [k for k in list(self.tasks.keys()) + list(self.events.keys())
                if k.startswith(prefix)]
        task_types = set(k.split("_", 1)[1] for k in keys)
        count = 0
        for t in task_types:
            if await self.stop_task(chat_id, t):
                count += 1
        return count

    def is_running(self, chat_id: int, task_type: str) -> bool:
        key = self._key(chat_id, task_type)
        return key in self.tasks and not self.tasks[key].done()


task_controller = TaskController()

_flood_bypass_enabled: bool = True



async def restartbot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart this bot process (VPS/systemd will keep the service attached)."""
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    if not update.message or not _is_primary_bot(context):
        return

    await update.message.reply_text("🔄 Bot is restarting and refreshing...")
    # Give Telegram time to deliver the confirmation, then replace this process.
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(_OWNER_GATE_MSG)
        return

    uptime_seconds = int(time.time() - START_TIME)
    hours = uptime_seconds // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    await update.message.reply_text(
        f"🕐 **𝙐𝙋𝙏𝙄𝙈𝙀:** `{hours}h {minutes}m {seconds}s`\n"
        f"📊 **𝘼𝘾𝙏𝙄𝙑𝙀 𝘽𝙊𝙏𝙎:** {len(all_apps)}\n"
        f"👑 **𝙎𝙐𝘿𝙊 𝙐𝙎𝙀𝙍:** {len(SUDO_USERS)}",
        parse_mode="Markdown"
    )


async def set_delay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set runtime delays. Usage: /setdelay <type> <seconds>."""
    global burst_delay, ncloop_delay, switch_delay, spam_delay
    global media_delay, vn_delay, pic_delay

    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /setdelay <type> <seconds>\n"
            "Types: spam, pic"
        )
        return

    dtype = args[0].lower().strip()
    try:
        value = max(0.0, float(args[1]))
    except (TypeError, ValueError):
        await update.message.reply_text("❌ Value must be a number.")
        return

    variables = {
        "burst": "burst_delay", "ncloop": "ncloop_delay", "switch": "switch_delay",
        "spam": "spam_delay", "media": "media_delay", "vn": "vn_delay", "pic": "pic_delay",
    }
    variable = variables.get(dtype)
    if variable is None:
        await update.message.reply_text(
            "❌ Unknown type. Use: burst, ncloop, switch, spam, media, vn, pic"
        )
        return

    globals()[variable] = value
    await update.message.reply_text(f"✅ {dtype.upper()} delay set to: {value:g}s")


async def floodbypass_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /floodbypass [on|off|status]
    Toggle or query the centralized flood bypass core.
    When ON (default): NC tasks stay active and recover automatically,
    while respecting Telegram's requested flood waits.
    When OFF: standard flood waits apply.
    """
    global _flood_bypass_enabled
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return

    args = (context.args or [])
    arg  = args[0].lower() if args else "status"

    if arg == "on":
        _flood_bypass_enabled = True
        await update.message.reply_text(
            "✅ 𝙁𝙇𝙊𝙊𝘿 𝘽𝙔-𝙋𝘼𝙎𝙎 𝘾𝙊𝙍𝙀 𝙊𝙉\n"
            "🔄 Continuous mode: tasks stay active until /stop\n"
            "⏳ Telegram flood waits are respected per bot\n"
            "🤖 Other configured bots continue independently"
        )
    elif arg == "off":
        _flood_bypass_enabled = False
        await update.message.reply_text(
            "⛔ 𝙁𝙇𝙊𝙊𝘿 𝘽𝙔-𝙋𝘼𝙎𝙎 𝘾𝙊𝙍𝙀 𝙊𝙁𝙁\n"
            "Standard flood wait mode active."
        )
    else:
        state = "🟢 ON" if _flood_bypass_enabled else "🔴 OFF"
        bots = [b for b in all_bot_instances if b is not None]
        flooded = sum(1 for b in bots if _flood_tracker.is_flooded(getattr(b, "id", id(b))))
        free    = len(bots) - flooded
        await update.message.reply_text(
            f"📊 𝙁𝙇𝙊𝙊𝘿 𝘽𝙔-𝙋𝘼𝙎𝙎 𝙎𝙏𝘼𝙏𝙐𝙎 : {state}\n"
            f"🤖 Total bots: {len(bots)}\n"
            f"✅ Free: {free}  |  🚫 Flooded: {flooded}\n"
            f"⏳ Flood waits are respected per bot\n"
            f"🔄 Continuous until /stop\n\n"
            f"Usage: /floodbypass on | off | status"
        )


async def _steadync_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
    delay: float = 0.0,
):
    if not bots:
        return

    async def _bot_worker(bot):
        bot_id = getattr(bot, "id", id(bot))
        while not stop_event.is_set():
            if _flood_tracker.is_flooded(bot_id):
                wait = _flood_tracker.remaining(bot_id)
                if wait > 0:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.25))
                    except asyncio.TimeoutError:
                        pass
                continue
            try:
                name = name_factory()[:255]
                await bot.set_chat_title(chat_id, name)
            except RetryAfter as e:
                _flood_tracker.mark_flooded(bot_id, e.retry_after)
                continue
            except (BadRequest, Forbidden):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.3)
                except asyncio.TimeoutError:
                    pass
                continue
            except (TimedOut, NetworkError):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                continue
            except Exception:
                if stop_event.is_set():
                    break
                await asyncio.sleep(0.1)
                continue

            if stop_event.is_set():
                break

            if delay > 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    continue
                else:
                    break
            else:
                await asyncio.sleep(0)

    workers = [asyncio.create_task(_bot_worker(bot)) for bot in bots]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()


async def _hyperfire_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    CONCURRENCY = 2
    if not bots:
        return

    async def _safe_rename(bot, name: str, bot_id: int, sem: asyncio.Semaphore):
        try:
            await bot.set_chat_title(chat_id, name)
        except RetryAfter as e:
            _flood_tracker.mark_flooded(bot_id, e.retry_after)
        except Exception:
            pass
        finally:
            sem.release()

    async def _bot_worker(bot):
        bot_id     = getattr(bot, "id", id(bot))
        sem        = asyncio.Semaphore(CONCURRENCY)
        fire_tasks: set = set()
        try:
            while not stop_event.is_set():
                if _flood_tracker.is_flooded(bot_id):
                    wait = _flood_tracker.remaining(bot_id)
                    if wait > 0:
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.25))
                        except asyncio.TimeoutError:
                            pass
                    continue
                try:
                    await asyncio.wait_for(sem.acquire(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if stop_event.is_set():
                    sem.release()
                    break
                name = name_factory()[:255]
                t = asyncio.create_task(_safe_rename(bot, name, bot_id, sem))
                fire_tasks.add(t)
                t.add_done_callback(fire_tasks.discard)
        finally:
            for t in list(fire_tasks):
                if not t.done():
                    t.cancel()

    workers = [asyncio.create_task(_bot_worker(bot)) for bot in bots]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()


async def _stealth_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    """
    STEALTH ENGINE — fast NC with micro-jitter that prevents flood detection.

    Each bot fires, then sleeps a TINY random amount (0.03–0.12s).
    This spreads the rename timestamps across Telegram's server — they never
    appear as a sudden burst, so flood detection is much less likely to trigger.
    When RetryAfter happens anyway → standard per-bot bypass.
    Net result: sustained fast NC, flood waits are rare and short.
    """
    JITTER_MIN = 0.03
    JITTER_MAX = 0.12

    if not bots:
        return

    async def _bot_worker(bot):
        bot_id = getattr(bot, "id", id(bot))
        while not stop_event.is_set():
            if _flood_tracker.is_flooded(bot_id):
                wait = _flood_tracker.remaining(bot_id)
                if wait > 0:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.25))
                    except asyncio.TimeoutError:
                        pass
                continue

            try:
                name = name_factory()[:255]
                await bot.set_chat_title(chat_id, name)
            except RetryAfter as e:
                _flood_tracker.mark_flooded(bot_id, e.retry_after)
                continue
            except (BadRequest, Forbidden):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
                continue
            except (TimedOut, NetworkError):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.3)
                except asyncio.TimeoutError:
                    pass
                continue
            except Exception:
                if stop_event.is_set():
                    break
                await asyncio.sleep(0.05)
                continue

            if stop_event.is_set():
                break

            jitter = random.uniform(JITTER_MIN, JITTER_MAX)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=jitter)
            except asyncio.TimeoutError:
                pass

    workers = [asyncio.create_task(_bot_worker(bot)) for bot in bots]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()




_ULTRA_SYMS_A = [
    "꧁","꧂","𖤍","𓂀","𓃰","𓆏","𓅓","𓊈","𓊉","𓋴",
    "꩜","꫁","ꫂ","ꗃ","ꖰ","꙰","ꬶ","ꬷ","꒦","꒷",
    "⟦","⟧","⸨","⸩","⌬","⍟","⎔","⧖","⧗","⌇",
    "🔱","⚜","♛","♜","♞","♟","⚔️","🗡️","🏹","🪃",
]
_ULTRA_SYMS_B = [
    "🔥","💥","⚡","☄️","💀","🌋","🌪️","🌩️","💣","🧨",
    "🖤","❤️‍🔥","🩸","☠️","👁️","🕷️","🕸️","🦂","🐍","🐉",
    "✦","✧","⊹","✶","⋆","★","☆","✩","✪","✫",
    "◈","◉","◎","◆","◇","◼","◻","▪","▸","▾",
]
_ULTRA_SYMS_C = [
    "𝕳","𝕬","𝕭","𝕮","𝕯","𝕰","𝕱","𝕲","𝖃","𝖄",
    "ꀘ","ꁷ","ꂝ","ꃋ","ꄞ","ꅉ","ꆖ","ꇡ","ꈠ","ꉻ",
    "꜀","꜁","꜂","꜃","꜄","꜅","꜆","꜇","꜈","꜉",
    "꒐","꒑","꒒","꒓","꒔","꒕","꒖","꒗","꒘","꒙",
]

def _ultra_name(text: str, last: list) -> str:
    """
    Rotates through 4 templates per call so every rename looks unique.
    Template chosen pseudo-randomly based on current time → not predictable.
    """
    for _ in range(25):
        a  = random.choice(_ULTRA_SYMS_A)
        b  = random.choice(_ULTRA_SYMS_B)
        c  = random.choice(_ULTRA_SYMS_C)
        sf = make_suffix()
        r = random.randint(0, 3)
        if r == 0:
            c_ = f"{a}{b}{text}{c}{sf}"
        elif r == 1:
            c_ = f"{a}{text}{b}{c}{sf}"
        elif r == 2:
            c_ = f"{a}{b}{text}{c}{sf}"
        else:
            c_ = f"{c}{text}{a}{b}{sf}"
        c_ = c_[:255]
        if c_ != last[0]:
            last[0] = c_
            return c_
    return f"{text}{make_suffix()}"[:255]


async def _ultra_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    """
    ULTRA ENGINE — Maximum speed, zero flood, constant NC.
    See header above for full strategy breakdown.
    """
    GHOST_THRESHOLD  = 20.0
    GHOST_JITTER_MIN = 0.010
    GHOST_JITTER_MAX = 0.040
    GROUP_SIZE       = 3
    GROUP_STAGGER    = 1.5
    WITHIN_STAGGER   = 0.03
    RATE_GUARD       = 12

    if not bots:
        return

    groups   = [bots[i:i + GROUP_SIZE] for i in range(0, len(bots), GROUP_SIZE)]
    pending: set = set()

    def _on_done(t: asyncio.Task):
        pending.discard(t)

    async def _fire(bot, name: str, bot_id: int):
        """Single fire-and-forget rename task."""
        try:
            await bot.set_chat_title(chat_id, name)
            _flood_tracker.record(bot_id)
        except RetryAfter as e:
            _flood_tracker.mark_flooded(bot_id, e.retry_after)
        except Exception:
            pass

    async def _bot_worker(bot, start_delay: float):
        bot_id = getattr(bot, "id", id(bot))

        if start_delay > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=start_delay)
            except asyncio.TimeoutError:
                pass
        if stop_event.is_set():
            return

        while not stop_event.is_set():
            if _flood_tracker.is_flooded(bot_id):
                wait = _flood_tracker.remaining(bot_id)
                if wait > 0:
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(), timeout=min(wait, 0.3)
                        )
                    except asyncio.TimeoutError:
                        pass
                continue

            name = name_factory()[:255]
            t    = asyncio.create_task(_fire(bot, name, bot_id))
            pending.add(t)
            t.add_done_callback(_on_done)

            if _flood_tracker.rate(bot_id) >= RATE_GUARD:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.08)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(0)

    workers = []
    for gi, group in enumerate(groups):
        base = gi * GROUP_STAGGER
        for bi, bot in enumerate(group):
            delay = base + bi * WITHIN_STAGGER
            workers.append(asyncio.create_task(_bot_worker(bot, delay)))

    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()
        for t in list(pending):
            t.cancel()


async def _blitz_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    CONCURRENCY     = 2

    if not bots:
        return

    async def _fire(bot, name: str, bot_id: int, sem: asyncio.Semaphore):
        try:
            await bot.set_chat_title(chat_id, name)
        except RetryAfter as e:
            _flood_tracker.mark_flooded(bot_id, e.retry_after)
        except Exception:
            pass
        finally:
            sem.release()

    async def _bot_worker(bot):
        bot_id      = getattr(bot, "id", id(bot))
        sem         = asyncio.Semaphore(CONCURRENCY)
        fire_tasks: set = set()
        try:
            while not stop_event.is_set():
                if _flood_tracker.is_flooded(bot_id):
                    wait = _flood_tracker.remaining(bot_id)
                    if wait > 0:
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.3))
                        except asyncio.TimeoutError:
                            pass
                    continue
                try:
                    await asyncio.wait_for(sem.acquire(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if stop_event.is_set():
                    sem.release()
                    break
                name = name_factory()[:255]
                t = asyncio.create_task(_fire(bot, name, bot_id, sem))
                fire_tasks.add(t)
                t.add_done_callback(fire_tasks.discard)
        finally:
            for t in list(fire_tasks):
                if not t.done():
                    t.cancel()

    workers = [asyncio.create_task(_bot_worker(bot)) for bot in bots]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()


async def _prime_hyperblitz_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    """
    PRIME HYPERBLITZ ENGINE — built for pure speed with zero long pauses.

    Design:
      • CONCURRENCY = 4  — 4 parallel rename tasks firing per bot simultaneously.
      • GHOST_THRESHOLD = 99s — virtually every RetryAfter is ghost-skipped.
        Ghost skip = 1–3 ms micro-jitter then immediately fire again, no wait.
      • Hard floods (>99s, nearly impossible) capped to 3s by BotFloodTracker.
      • Each bot runs its own independent worker; one bot's flood never slows others.
      • Main loop yields to event loop via asyncio.sleep(0) — never blocks.
    """
    CONCURRENCY     = 3

    if not bots:
        return

    async def _fire(bot, name: str, bot_id: int, sem: asyncio.Semaphore):
        try:
            await bot.set_chat_title(chat_id, name)
        except RetryAfter as e:
            _flood_tracker.mark_flooded(bot_id, e.retry_after)
        except Exception:
            pass
        finally:
            sem.release()

    async def _bot_worker(bot):
        bot_id     = getattr(bot, "id", id(bot))
        sem        = asyncio.Semaphore(CONCURRENCY)
        fire_tasks: set = set()
        try:
            while not stop_event.is_set():
                if _flood_tracker.is_flooded(bot_id):
                    wait = _flood_tracker.remaining(bot_id)
                    if wait > 0:
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.2))
                        except asyncio.TimeoutError:
                            pass
                    continue
                try:
                    await asyncio.wait_for(sem.acquire(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if stop_event.is_set():
                    sem.release()
                    break
                name = name_factory()[:255]
                t = asyncio.create_task(_fire(bot, name, bot_id, sem))
                fire_tasks.add(t)
                t.add_done_callback(fire_tasks.discard)
        finally:
            for t in list(fire_tasks):
                if not t.done():
                    t.cancel()

    workers = [asyncio.create_task(_bot_worker(bot)) for bot in bots]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()


async def _ghost_burn_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    """
    GHOST BURN ENGINE — 10 bots acting like flood doesn't exist.
    RetryAfter ≤ 8s → micro-jitter only (0.05–0.4s), NOT full wait.
    RetryAfter > 8s → standard per-bot bypass, others keep full speed.
    """
    if not bots:
        return

    async def _bot_worker(bot):
        bot_id = getattr(bot, "id", id(bot))
        while not stop_event.is_set():
            if _flood_tracker.is_flooded(bot_id):
                wait = _flood_tracker.remaining(bot_id)
                if wait > 0:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.3))
                    except asyncio.TimeoutError:
                        pass
                continue

            try:
                name = name_factory()[:255]
                await bot.set_chat_title(chat_id, name)
            except RetryAfter as e:
                _flood_tracker.mark_flooded(bot_id, e.retry_after)
                continue
            except (BadRequest, Forbidden):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
                continue
            except (TimedOut, NetworkError):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.3)
                except asyncio.TimeoutError:
                    pass
                continue
            except Exception:
                if stop_event.is_set():
                    break
                await asyncio.sleep(0.05)
                continue

            if stop_event.is_set():
                break
            await asyncio.sleep(0)

    workers = [asyncio.create_task(_bot_worker(bot)) for bot in bots]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()


async def _relay_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    FULL_DELAY  = 0.0
    SLOW_DELAY  = switch_delay
    FLOOD_LIMIT = 2

    if not bots:
        return

    pairs: List[List[Any]] = []
    for i in range(0, len(bots), 2):
        group = bots[i: i + 2]
        if group:
            pairs.append(group)

    n_pairs = len(pairs)
    active_group = [0]
    flood_hits: List[int] = [0] * n_pairs

    async def _bot_worker(bot, group_idx: int):
        bot_id = getattr(bot, "id", id(bot))
        while not stop_event.is_set():
            is_active = (group_idx == active_group[0])
            delay = FULL_DELAY if is_active else SLOW_DELAY

            if _flood_tracker.is_flooded(bot_id):
                wait = _flood_tracker.remaining(bot_id)
                if wait > 0:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=min(wait, 0.3))
                    except asyncio.TimeoutError:
                        pass
                continue

            try:
                name = name_factory()[:255]
                await bot.set_chat_title(chat_id, name)
                if is_active and flood_hits[group_idx] > 0:
                    flood_hits[group_idx] = max(0, flood_hits[group_idx] - 1)
            except RetryAfter as e:
                _flood_tracker.mark_flooded(bot_id, e.retry_after)
                if is_active:
                    flood_hits[group_idx] += 1
                    if flood_hits[group_idx] >= FLOOD_LIMIT:
                        active_group[0] = (active_group[0] + 1) % n_pairs
                        flood_hits[group_idx] = 0
                continue
            except (BadRequest, Forbidden, TimedOut, NetworkError):
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
                continue
            except Exception:
                if stop_event.is_set():
                    break
                await asyncio.sleep(0.05)
                continue

            if stop_event.is_set():
                break

            if delay > 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    continue
                else:
                    break
            else:
                await asyncio.sleep(0)

    workers = []
    for g_idx, group in enumerate(pairs):
        for bot in group:
            workers.append(asyncio.create_task(_bot_worker(bot, g_idx)))

    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        for w in workers:
            if not w.done():
                w.cancel()


async def _pfp_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    photo_data: bytes,
):
    """Continuously apply the selected group photo using all configured bots."""
    if not bots or not photo_data:
        return

    while not stop_event.is_set():
        async def _set_one(bot):
            try:
                photo = io.BytesIO(photo_data)
                photo.name = "group_pfp.jpg"
                await bot.set_chat_photo(chat_id, photo=photo)
                return True
            except RetryAfter as e:
                await asyncio.sleep(min(float(e.retry_after), 3.0))
            except (BadRequest, Forbidden, TimedOut, NetworkError):
                pass
            except Exception:
                pass
            return False

        await asyncio.gather(
            *[_set_one(bot) for bot in bots],
            return_exceptions=True,
        )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, pic_delay))
        except asyncio.TimeoutError:
            pass


async def pic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -pic / /pic — reply to a photo and continuously set it as the group PFP
    using all configured bots.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    msg = update.message.reply_to_message
    if not msg or not msg.photo:
        return await update.message.reply_text("⚠️ Reply to a photo")

    try:
        f = await msg.photo[-1].get_file()
        b = io.BytesIO()
        await f.download_to_memory(b)
        photo_data = b.getvalue()
    except Exception as e:
        return await update.message.reply_text(f"❌ Failed to download photo: {e}")

    if not photo_data:
        return await update.message.reply_text("❌ Empty photo data")

    chat_id = update.effective_chat.id
    pic_media_cache[chat_id] = photo_data
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]

    async def pfp_loop(stop_event: asyncio.Event):
        await _pfp_engine(chat_id, bots, stop_event, photo_data)

    await task_controller.start_task(chat_id, "pic", pfp_loop)
    await update.message.reply_text(
        f" 𝙋𝙁𝙋 𝙎𝙏𝘼𝙍𝙏𝙀𝘿 ({pic_delay:g}s)** ({len(bots)} bots)"
    )


async def stop_pic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop the PFP changer in the current chat."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    stopped = await task_controller.stop_task(update.effective_chat.id, "pic")
    pic_media_cache.pop(update.effective_chat.id, None)
    if _is_primary_bot(context):
        await update.message.reply_text("🛑 𝙋𝙁𝙋 𝙎𝙏𝙊𝙋𝙋𝙀𝘿" if stopped else "PFP Rush is not active here.")


async def _adaptive_burst_engine(
    chat_id: int,
    bots: List[Any],
    stop_event: asyncio.Event,
    name_factory,
):
    MAX_GAP      = 1.2
    BACKOFF_STEP = 0.15
    RECOVERY     = 0.85

    if not bots:
        return

    adaptive_gap = [0.0]

    async def _safe_rename(bot, name: str) -> bool:
        bot_id = getattr(bot, "id", id(bot))
        if _flood_tracker.is_flooded(bot_id):
            return False
        try:
            await bot.set_chat_title(chat_id, name)
            return True
        except RetryAfter as e:
            _flood_tracker.mark_flooded(bot_id, e.retry_after)
            return False
        except (BadRequest, Forbidden):
            return True
        except (TimedOut, NetworkError):
            return False
        except Exception:
            return False

    while not stop_event.is_set():
        name = name_factory()[:255]
        tasks = [asyncio.create_task(_safe_rename(bot, name)) for bot in bots]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        flood_count = sum(1 for r in results if r is False)

        if flood_count > 0:
            adaptive_gap[0] = min(MAX_GAP, adaptive_gap[0] + BACKOFF_STEP * flood_count)
        else:
            adaptive_gap[0] = max(0.0, adaptive_gap[0] * RECOVERY)

        if stop_event.is_set():
            break

        gap = adaptive_gap[0]
        if gap > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=gap)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(0)


# ─────────────────────────────────────────────────────────────────
#  MULTI-MENU SYSTEM
#  /menu  = master menu
#  /xprime1 = NC & PRIME
#  /xprime2 = SPAM / REPLY / REACT
#  /xprime3 = CHAT / MEDIA / MUSIC
#  /xprime4 = BOT / SETTINGS / USER / TOOLS
# ─────────────────────────────────────────────────────────────────

_MENU_MASTER = (
 "╔════════════════════╗\n"
 "║      𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔     \n"
 "╚════════════════════╝\n\n"
"╔═══════════════════════╗\n"
"║─────────𝙈𝙀𝙉𝙐────────\n"
"║   \n"
"║ ├ » /xprime1   \n"
"║   \n"
"║  → 💫 𝙉𝘾 \n"
"║   \n"
"║ ├ » /xprime2 \n"
"║   \n" 
"║  → 💬 𝙎𝙇𝙄𝘿𝙀 & 𝙎𝙋𝘼𝙈   \n"
"║   \n"
"║ ├ » /xprime3 \n"
"║   \n"
"║  → 🎵 𝘾𝙃𝘼𝙏 & 𝙈𝙀𝘿𝙄𝘼 \n"
"║   \n"
"║ ├ » /xprime4 \n"
"║   \n"
"║ → 🤖 𝘽𝙊𝙏𝙎 𝘼𝙉𝘿 𝙎𝙀𝙏𝙏𝙄𝙉𝙂𝙎 \n"  
"║   \n"
"╚═══════════════════════╝\n\n"
)

_MENU1_TEXT = (
    "╔═══════════════════════╗\n"
    "║        𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔  \n"
    "╚═══════════════════════╝\n\n"
    "╔══════════════════════════╗\n"
    "║───────── 💫 𝙉𝘾 ──────── \n"
    "║   \n"
    "║         𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║   \n"
    "║  ├ »   -ncemo     \n"
    "║  ├ »   -ncmoon    \n"
    "║  ├ »   -crync     \n"
    "║  ├ »   -ncflag    \n"
    "║  ├ »   -ncrose    \n"
    "║  ├ »   -ncultra   \n"
    "║  ├ »   -ncflood   \n"
    "║  ├ »   -ncflower  \n"
    "║  ├ »   -prime   \n"
    "║  ├ »   /ncdel     \n"
    "║  \n"
    "║───── 🛑 𝙎𝙏𝙊𝙋 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ─────  \n"
    "║   \n"
    "║  ├ »   /stopnc    \n"
    "╚══════════════════════════╝\n\n"
)

_MENU2_TEXT = (
    "╔══════════════════════════╗\n"
    "║         𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔    \n"
    "╚══════════════════════════╝\n\n"
    "╔══════════════════════════╗\n"
    "║────── 💬 𝙎𝙋𝘼𝙈 & 𝙎𝙇𝙄𝘿𝙀 ──────  \n"
    "║   \n"
    "║           𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║  \n"
    "║  ├ »   -slide               \n"
    "║  ├ »   -spam                \n"
    "║  ├ »   -slidereply          \n"
    "║  ├ »   -autoreply           \n"
    "║  ├ »   -targetreply         \n"
    "║    \n"
    "║──── 🛑 𝙎𝙏𝙊𝙋 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ──── \n"
    "║   \n"
    "║  ├ »   /stopspam            \n"
    "║  ├ »   /stopslidereply      \n"
    "║  ├ »   /stopautoreply       \n"
    "║  ├ »   /stoptargetreply     \n"
    "╠══════════════════════════╗\n"
    "║────── 😂 𝙍𝙀𝘼𝘾𝙏𝙄𝙊𝙉 ────── \n" 
    "║  \n"
    "║          𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║   \n"
    "║  ├ »   -autoreact            \n"
    "║  ├ »   -react <emoji>  \n"
    "║   \n"
    "║───── 🛑 𝙎𝙏𝙊𝙋 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ───── \n"
    "║     \n"
    "║  ├ »   /stopreact            \n"
    "╚══════════════════════════╝\n\n"
)

_MENU3_TEXT = (
    "╔══════════════════════════╗\n"
    "║        𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔   \n"
    "╚══════════════════════════╝\n\n"
    "╔══════════════════════════╗\n"
    "║──────── 🎵 𝙎𝙊𝙉𝙂 ───────\n"
    "║   \n"
    "║  ├ »   ~song <name>              \n"
    "║   \n"
    "╠══════════════════════════╗\n"
    "║────── 🔇 𝘾𝙃𝘼𝙏 𝘾𝙊𝙉𝙏𝙍𝙊𝙇 ─────\n"
    "║   \n"
    "║            𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║    \n"
    "║  ├ »   /mutegc         \n"
    "║  ├ »   /unmutegc       \n"
    "║  ├ »   /muteuser       \n"
    "║  ├ »   /unmuteuser     \n"
    "║  ├ »   /lock           \n"
    "║  ├ »   /unlock         \n"
    "║  ├ »   /kick           \n"
    "║  ├ »   /ban            \n"
    "║  ├ »   /unban          \n"
    "╠══════════════════════════╗\n"
    "║──────── 🖼 𝙈𝙀𝘿𝙄𝘼 ──────── \n"
    "║ \n"
    "║           𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║    \n"
    "║  ├ »   /menupic 1,2,3,4  \n"
    "║  ├ »   /menuvid 1,2,3,4  \n"
    "║  ├ »   /menuclear        \n"
    "║    \n"
    "║─────   𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ───── \n"
    "║    \n"
    "║  ├ »   /pic      \n"
    "║  ├ »   /stoppic          \n"
    "╚══════════════════════════╝\n\n"
)

_MENU4_TEXT = (
    "╔══════════════════════════╗\n"
    "║        𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔    \n"
       "╚══════════════════════════╝\n\n"
    "╔══════════════════════════╗\n"
    "║──────── 🤖 𝘽𝙊𝙏 ────────\n"
    "║    \n"
    "║           𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║      \n"
    "║  ├ »   /addbot         \n"
    "║  ├ »   /kickbot           \n"
    "║  ├ »   /admin                  \n"
    "║  ├ »   /creategc <name>        \n"
    "╠══════════════════════════╗\n"
    "║──────── ⚙️ 𝙎𝙀𝙏𝙏𝙄𝙉𝙂𝙎 ────────\n"
    "║    \n"
    "║           𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║   \n"
    "║  ├ »   /gclist         \n"
    "║  ├ »   /leave          \n"
    "║  ├ »   /stop           \n"
    "║  ├ »   /uptime         \n"
    "║  ├ »   /setdelay       \n"
    "║  ├ »   /bots           \n"
    "║  ├ »   /ping           \n"
    "║  ├ »   /refresh        \n"
    "║  ├ »   /floodbypass on|off|status \n"
    "╠══════════════════════════╗\n"
    "║────── 👑 𝙎𝙐𝘿𝙊 & 𝙊𝙑𝙀𝙍 ─────\n"
    "║     \n"
    "║           𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎\n"
    "║   \n"
    "║  ├ »   /sudo       \n"
    "║  ├ »   /delsudo      \n"
    "║  ├ »   /sudolist   \n"
    "║  ├ »   /restartbot    \n"
    "║  ├ »   /over <target>     \n"
    "╚══════════════════════════╝\n\n"
)

# Backward-compatible alias used by /xprime and /help.
_MENU_TEXT = _MENU_MASTER

async def _send_menu_page(target_msg, caption: str, menu_key: str = "0"):
    await _send_menu(target_msg, caption, menu_key)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await _send_menu_page(update.message, _MENU_MASTER, "0")


async def menu1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await _send_menu_page(update.message, _MENU1_TEXT, "1")


async def menu2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await _send_menu_page(update.message, _MENU2_TEXT, "2")


async def menu3_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await _send_menu_page(update.message, _MENU3_TEXT, "3")


async def menu4_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await _send_menu_page(update.message, _MENU4_TEXT, "4")


_TG_CAPTION_LIMIT = 1024


async def _send_menu(target_msg, caption: str, menu_key: str = "0"):
    # New storage is menu-specific: {"0": {"photo_id": ...}, "1": {...}}.
    # Continue supporting the old flat media JSON file as menu 0.
    media = _menu_media.get(str(menu_key), {})
    if not isinstance(media, dict):
        media = {}
    if str(menu_key) == "0" and not media and any(
        key in _menu_media for key in ("photo_id", "video_id", "animation_id", "document_id")
    ):
        media = _menu_media

    pid = media.get("photo_id")
    vid = media.get("video_id")
    anim = media.get("animation_id")
    doc = media.get("document_id")
    if not any((pid, vid, anim, doc)):
        await target_msg.reply_text(caption)
        return

    cap1 = caption if len(caption) <= _TG_CAPTION_LIMIT else caption[:_TG_CAPTION_LIMIT - 1] + "…"
    cap2 = caption[_TG_CAPTION_LIMIT - 1:] if len(caption) > _TG_CAPTION_LIMIT else None
    try:
        if pid:
            await target_msg.reply_photo(photo=pid, caption=cap1)
        elif vid:
            await target_msg.reply_video(video=vid, caption=cap1)
        elif anim:
            await target_msg.reply_animation(animation=anim, caption=cap1)
        elif doc:
            await target_msg.reply_document(document=doc, caption=cap1)
        if cap2:
            await target_msg.reply_text(cap2)
    except Exception:
        await target_msg.reply_text(caption)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    known_chats.add(update.effective_chat.id)
    save_groups(known_chats)
    await _send_menu(update.message, _MENU_TEXT, "0")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await _send_menu(update.message, _MENU_TEXT, "0")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    count = await task_controller.stop_all_for_chat(update.effective_chat.id)
    if count > 0:
        await update.message.reply_text("𝙎𝙏𝙊𝙋𝙋𝙀𝘿 - 𝘼𝙇𝙇 𝙏𝘼𝙎𝙆.")
    else:
        await update.message.reply_text("𝙉𝙊𝙏𝙃𝙄𝙉𝙂 𝙍𝙐𝙉𝙉𝙄𝙉𝙂.")


async def sudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    if not update.message:
        return
    target_id: Optional[int] = None
    if context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            return await update.message.reply_text("Usage: /sudo <user_id>")
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
    if not target_id:
        return await update.message.reply_text("Usage: /sudo <user_id>  or reply to a user's message")
    if target_id == OWNER_ID:
        return await update.message.reply_text("You are already the owner.")
    SUDO_USERS.add(target_id)
    save_sudo()
    await update.message.reply_text(
        f"𝙐𝙎𝙀𝙍 `{target_id}` 𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔 𝙆𝘼 𝙂𝙐𝙇𝘼𝙈 𝘽𝘼𝙉 𝙂𝘼𝙔𝘼.",
        parse_mode="Markdown",
    )


async def delsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    if not update.message:
        return
    target_id: Optional[int] = None
    if context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            return await update.message.reply_text("Usage: /delsudo <user_id>")
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
    if not target_id:
        return await update.message.reply_text("Usage: /delsudo <user_id>  or reply to a user's message")
    if target_id == OWNER_ID:
        return await update.message.reply_text("Cannot remove the owner.")
    if target_id not in SUDO_USERS:
        return await update.message.reply_text(f"User `{target_id}` is not a sudo user.", parse_mode="Markdown")
    SUDO_USERS.discard(target_id)
    save_sudo()
    await update.message.reply_text(
        f"𝙐𝙎𝙀𝙍 `{target_id}` 𝙉𝙊 𝙈𝙊𝙍𝙀 𝙎𝙇𝘼𝙑𝙀.",
        parse_mode="Markdown",
    )


async def sudolist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show sudo users with their Telegram username and numeric ID."""
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    if not update.effective_message:
        return

    sudo_ids = sorted(SUDO_USERS - {OWNER_ID})
    if not sudo_ids:
        await update.effective_message.reply_text(
            "No sudo users added yet.\nUse /sudo <user_id> to grant access."
        )
        return

    rows = []
    for user_id in sudo_ids:
        username = None
        display_name = None
        try:
            # Telegram only returns profile details when this bot is allowed
            # to access that user's chat. The numeric ID is always available.
            chat = await context.bot.get_chat(chat_id=user_id)
            username = getattr(chat, "username", None)
            display_name = getattr(chat, "full_name", None) or getattr(chat, "first_name", None)
        except Exception as exc:
            logger.debug("Could not fetch sudo profile for %s: %s", user_id, exc)

        username_text = f"@{username}" if username else "Username unavailable"
        name_text = display_name or "Name unavailable"
        rows.append(
            f"• <b>{html.escape(name_text)}</b> — {html.escape(username_text)}\n"
            f"  ID: <code>{user_id}</code>"
        )

    text = (
        f"👥 <b>SUDO USERS ({len(sudo_ids)})</b>\n\n"
        + "\n\n".join(rows)
       
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def bots_info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    count = len([b for b in all_bot_instances if b is not None])
    await update.message.reply_text(f"🎀 𝘼𝘾𝙏𝙄𝙑𝙀 𝘽𝙊𝙏𝙎: {count}")






async def ncemo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-ncemo", "ncemo", "/ncemo"), context)
    if not base:
        return await update.message.reply_text("Usage: -ncemo <text>")

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]
    _last = [""]

    def make_name():
        return _build_name(base, _last)

    async def nc_loop(stop_event: asyncio.Event):
        await _steadync_engine(chat_id, bots, stop_event, make_name, ncloop_delay)

    await task_controller.start_task(chat_id, "nc", nc_loop)
    _show_preview = f"{random.choice(WRAP_RIGHT)}{base}{make_suffix()}"
    await update.message.reply_text(
        f"𝙉𝘾𝙀𝙈𝙊 𝙎𝙏𝘼𝙍𝙏𝙀𝘿🦋 \n"
    )




async def ncflag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-ncflag", "💦ncflag", "/ncflag"), context)
    if not base:
        return await update.message.reply_text("Usage: -ncflag <text>")

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]
    _last = [""]

    def make_name():
        s1 = random.choice(WAVE_SYMBOLS + BURN_SYMS)
        s2 = random.choice(WAVE_SYMBOLS + BURN_SYMS)
        return f"{s1}{base}{s2}{make_suffix()}"[:255]

    async def nc_loop(stop_event: asyncio.Event):
        await _adaptive_burst_engine(chat_id, bots, stop_event, make_name)

    await task_controller.start_task(chat_id, "nc", nc_loop)
    await update.message.reply_text(
        f"𝙉𝘾𝙁𝙇𝘼𝙂 𝙎𝙏𝘼𝙍𝙏𝙀𝘿🦋\n"
    )


async def ncrose_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw,
        ("-ncrose", "-ncrose", "ncrose", "ncrose", "/ncrose", "/ncrose"),
        context)
    if not base:
        return await update.message.reply_text("Usage: -ncrose <text>")

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]
    _last = [""]

    def make_name():
        for _ in range(len(WATER_SYMS)):
            sym = random.choice(WATER_SYMS)
            candidate = f"{sym} {base} {sym}{make_suffix()}"[:255]
            if candidate != _last[0]:
                _last[0] = candidate
                return candidate
        return f"{base}{make_suffix()}"[:255]

    async def nc_loop(stop_event: asyncio.Event):
        await _hyperfire_engine(chat_id, bots, stop_event, make_name)

    await task_controller.start_task(chat_id, "nc", nc_loop)
    preview = random.choice(WATER_SYMS)
    await update.message.reply_text(
        f"𝙉𝘾𝙍𝙊𝙎𝙀 𝙎𝙏𝘼𝙍𝙏𝙀𝘿🦋\n"
    )

_LUND_SYMS = [
    "꒰꒱","꒦꒷","ꗃ","ꖰ","ꗍ","ꗆ","꙰","ꬶ","ꬷ",
    "⌇","꠸","꠹","꠺","ꦰ","ꦱ","ꦲ","꦳",
    "🍆","🔥","⚡","💥","🌋","☄️","💣","🗡️","⚔️","🌊",
    "꧃","꧄","꧅","꧆","꧇","꧈","꧉","꧊",
]

_BHOSDA_SYMS = [
    "⸨","⸩","⟦","⟧","⦃","⦄","⦅","⦆","⦇","⦈",
    "𓂀","𓃰","𓆏","𓅓","𓆑","𓆈","𓅃","𓃟",
    "♠","♣","♟","⚜","🔱","⚡","💀","☠️",
    "꩜","꩜","⌬","◈","⎔","⧖","⬡","⬢","⍟",
    "🖤","🗡️","⚔️","🛡","🔪","💣","💥","☄️",
]



_AREY_SYMS = [
    "¿","¡","✧","˚","⊹","₊","⁎","◌","⌖","⌗",
    "꩓","꩔","꩕","꩖","ꫂ","꫁","ꫀ","꫃",
    "🫦","😏","😈","👀","💅","🤌","👁️","💬","🗣️",
    "⟨","⟩","《","》","〈","〉","「","」","【","】",
    "🎭","🎪","🎯","🃏","🎲","♟️","🎴","🀄",
]



_HAT_SYMS = [
    "𓂀","𓃰","𓆏","𓅓","𓆑","𓅃",
    "☠️","💀","🖤","🗡️","⚔️","🔪","⚰️","🩸","🕯️","🌑",
    "꙰","꙱","꙲","ꙴ","ꙵ","ꙶ","ꙷ","ꙸ","ꙹ","ꙺ",
    "⛅","🕳️","🌞","🌚","🌝","🌜","🌛","⭐","✨","☀️",
    "🌒","🌓","🌔","🌑","🌘","🌙","🪐","🌍","🌖","🌕",
]

async def ncmoon_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-ncmoon", "ncmoon", "/ncmoon"), context)
    if not base:
        return await update.message.reply_text("Usage: -ncmoon <text>")

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]
    _last = [""]

    def make_name():
        return _build_name(base, _last)

    async def nc_loop(stop_event: asyncio.Event):
        await _stealth_engine(chat_id, bots, stop_event, make_name)

    await task_controller.start_task(chat_id, "nc", nc_loop)
    await update.message.reply_text(
        f"𝙉𝘾𝙈𝙊𝙊𝙉 𝙎𝙏𝘼𝙍𝙏𝙀𝘿🦋\n"
    )


_CRY_SYMS = [
    "😭","💔","🥺","🥹","😢","😞","😔","😿","🫂","🤍",
    "ꦿ","ꪆ","ꦾ","ꦽ","ꦼ","ꪊ","ꪋ","ꪌ","ꪍ",
    "꩓","꩔","꩕","꩖","ꪗ","ꪘ","ꪙ","ꪚ","ꪛ",
    "🌧️","🌨️","❄️","🌊","💧","🫧","☁️","🌫️","🌁","🌃",
    "🕊️","🪽","🌺","🌸","🌼","💮","🤍","🩶","🩷","💫",
]

async def crync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-nccry", "💦nccry", "/nccry", "+crync", "💦crync", "/crync"), context)
    if not base:
        return await update.message.reply_text("Usage: -nccry <text>")

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]
    _last = [""]

    def make_name():
        s1 = random.choice(_CRY_SYMS)
        s2 = random.choice(_CRY_SYMS)
        suf = make_suffix()
        c = f"😭{s1}{base}{s2}😭{suf}"[:255]
        if c != _last[0]:
            _last[0] = c
        return c

    async def nc_loop(stop_event: asyncio.Event):
        await _steadync_engine(chat_id, bots, stop_event, make_name, ncloop_delay)

    await task_controller.start_task(chat_id, "nc", nc_loop)
    await update.message.reply_text(
        f"𝙉𝘾𝘾𝙍𝙔 𝙎𝙏𝘼𝙍𝙏𝙀𝘿🦋\n"
    )


_PERSONAL_SYMS = [
    "꒰","꒱","꒦","꒷","ꗃ","ꖰ","꙰","ꬶ","ꬷ","꧃","꧅","꧇",
    "⌇","⟦","⟧","⸨","⸩","◈","꩜","⌬","⍟","⎔","⧖",
    "🔥","💥","⚡","☄️","💀","🖤","🗡️","⚔️","💣","🌋",
    "𓂀","𓃰","𓆏","𓅓","♠","♣","⚜","🔱",
    "꫁","ꫂ","⟡","✦","◉","✧","⊹","✶","⋆",
]

def _personal_nc_name(user_txt: str, taunt: str, last: list) -> str:
    for _ in range(20):
        s1 = random.choice(_PERSONAL_SYMS)
        s2 = random.choice(_PERSONAL_SYMS)
        suf = make_suffix()
        c = f"{s1}{user_txt} {taunt}{s2}{suf}"[:255]
        if c != last[0]:
            last[0] = c
            return c
    return f"{user_txt} {taunt}{make_suffix()}"[:255]


def _make_personal_nc_handler(cmd_names, taunt: str, label: str, engine="hyperfire"):
    """
    Factory that builds a personal NC handler.
    cmd_names  — tuple of accepted prefixes e.g. ("+burnavnc","burnavnc","/burnavnc")
    taunt      — fixed insult embedded in every title e.g. "burnav se chud"
    label      — display name in confirmation msg
    engine     — "hyperfire" | "ghost" | "stealth" | "steady"
    """
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not is_admin(update.effective_user.id):
            return
        if not update.effective_chat or not update.message:
            return
        if not _is_primary_bot(context):
            return
        raw  = (update.message.text or "").strip()
        base = _extract_base(raw, cmd_names, context)
        if not base:
            main = cmd_names[0]
            return await update.message.reply_text(f"Usage: {main} <text>")
        chat_id = update.effective_chat.id
        bots    = [b for b in all_bot_instances if b is not None] or [context.bot]
        _last   = [""]
        def make_name():
            return _personal_nc_name(base, taunt, _last)
        if engine == "hyperfire":
            async def nc_loop(stop_event: asyncio.Event):
                await _hyperfire_engine(chat_id, bots, stop_event, make_name)
        elif engine == "ghost":
            async def nc_loop(stop_event: asyncio.Event):
                await _ghost_burn_engine(chat_id, bots, stop_event, make_name)
        elif engine == "stealth":
            async def nc_loop(stop_event: asyncio.Event):
                await _stealth_engine(chat_id, bots, stop_event, make_name)
        else:
            async def nc_loop(stop_event: asyncio.Event):
                await _steadync_engine(chat_id, bots, stop_event, make_name, ncloop_delay)
        await task_controller.start_task(chat_id, "nc", nc_loop)
        preview = make_name()
        await update.message.reply_text(
            f" {label} 𝙉𝘾 𝘼𝘾𝙏𝙄𝙑𝙀🦋\n"
        )
    return handler


ncprime_handler = _make_personal_nc_handler(
    cmd_names=("-prime", "-prime", "/ncprime"),
    taunt="༶⛧𝙋𝙍𝙞𝙈𝙀 𝙆𝘼 𝙇𝙐𝙉𝘿 𝘾𝙃𝙐𝙎♛😈🖕🏼𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫𒐫",
    label="𝙋𝙍𝙞𝙈𝙀",
    engine="hyperfire",
)

async def ncultra_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -ncultra <text>
    ════════════════════════════════════════════════════════════
    ULTRA NC — Combines every flood bypass technique:

    ⚡ Fire-and-forget pipeline (no wait between renames)
    🔄 Trio stagger (1.5 s) — flood windows never overlap
    👻 Ghost mode — floods ≤ 20 s skipped (10-40 ms jitter)
    🛡  Pre-emptive guard at 12 renames/min before hard limit
    🎨 4 rotating name templates — every rename looks unique
       (3 symbol pools × 4 templates = insane variety)

    10 bots split into 4 trios. Each trio fires independently.
    At any moment, 6-9 bots are naming at full speed.
    Flood laga hi nahi — ya laga to kisi ne notice nahi kiya.
    ════════════════════════════════════════════════════════════
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw  = (update.message.text or "").strip()
    base = _extract_base(raw, ("-ncultra", "ncultra", "/ncultra"), context)
    if not base:
        return await update.message.reply_text("Usage: -ncultra <text>")

    chat_id = update.effective_chat.id
    bots    = [b for b in all_bot_instances if b is not None] or [context.bot]
    _last   = [""]
    n_trios = max(1, (len(bots) + 2) // 3)

    def make_name():
        return _ultra_name(base, _last)

    async def nc_loop(stop_event: asyncio.Event):
        await _ultra_engine(chat_id, bots, stop_event, make_name)

    await task_controller.start_task(chat_id, "nc", nc_loop)
    await update.message.reply_text(
        f"𝙉𝘾𝙐𝙇𝙏𝙍𝘼 𝙎𝙏𝘼𝙍𝙏𝙀𝘿🦋\n"
    )


_INFERNO_SYMS  = ["🌺","🌹","💐","🌷","🪷","🌸","💮","🌸","🪻","🏵️","🌻","🌼","🍂","🍁","🪷"]
_BLOOD_SYMS    = ["🫧","🌬️","🌀","🌪️","⚡","☔","💧","☁️","🌈","🌨️","🌧️","🌩️","🌦️","🌦️","🌥️"]

def _make_blitz_nc_handler(cmd_names: tuple, sym_pool: list, label: str, template: int = 0):
    """
    Factory → creates a NC handler using the BLITZ ENGINE.
    template 0: {e1}{text}{e2}{suf}
    template 1: {e1}{e2}{text}{suf}
    template 2: {text}{e1}{e2}{suf}
    template 3: {e1}{e2}{text}{e1}{suf}
    """
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not is_admin(update.effective_user.id):
            return
        if not update.effective_chat or not update.message:
            return
        if not _is_primary_bot(context):
            return
        raw  = (update.message.text or "").strip()
        base = _extract_base(raw, cmd_names, context)
        if not base:
            return await update.message.reply_text(f"Usage: {cmd_names[0]} <text>")
        chat_id = update.effective_chat.id
        bots    = [b for b in all_bot_instances if b is not None] or [context.bot]
        _last   = [""]
        def make_name():
            e1 = random.choice(sym_pool)
            e2 = random.choice(sym_pool)
            sf = make_suffix()
            if template == 0:
                c = f"{e1}{base}{e2}{sf}"
            elif template == 1:
                c = f"{e1}{e2}{base}{sf}"
            elif template == 2:
                c = f"{base}{e1}{e2}{sf}"
            else:
                c = f"{e1}{e2}{base}{e1}{sf}"
            c = c[:255]
            if c != _last[0]:
                _last[0] = c
            return c
        async def nc_loop(stop_event: asyncio.Event):
            await _blitz_engine(chat_id, bots, stop_event, make_name)
        await task_controller.start_task(chat_id, "nc", nc_loop)
        await update.message.reply_text(
            f"⚡ {label} 𝙁𝘼𝙎𝙏𝙉𝘾 𝘼𝘾𝙏𝙄𝙑𝙀🎀"
        )
    return handler


ncflower_handler = _make_blitz_nc_handler(
    ("-ncflower",  "ncflower",  "/ncflower"),  _INFERNO_SYMS, "𝙉𝘾𝙁𝙇𝙊𝙒𝙀𝙍🦋", template=0)
ncflood_handler = _make_blitz_nc_handler(
    ("-ncflood",  "ncflood",  "/ncflood"),  _BLOOD_SYMS,  "𝙉𝘾𝙁𝙇𝙊𝙊𝘿🦋", template=3)


_PRIME_TXT  = "_𝐑𝐀𝐍𝐃_"

_PRIME_POOLS = [
    ["🔥","💥","🌋","☄️","🔴","🟠"],
    ["⚡","🌩️","💫","✨","🌟","🌠"],
    ["💀","☠️","🌑","🖤","🕷️","🦇"],
]

_PRIME_TEMPLATES = [
    lambda e1,e2,t,s: f"{e1}{_PRIME_TXT}{t}{e2}{s}",
    lambda e1,e2,t,s: f"{e2}{_PRIME_TXT}{e1}{t}{s}",
    lambda e1,e2,t,s: f"{e1}{e2}{t}{_PRIME_TXT}{s}",
]

def _make_prime_nc_handler(num: int, emoji_pool: list):
    cmd_names = (f"+prime{num}", f"prime{num}", f"/xprime{num}")
    tmpl      = _PRIME_TEMPLATES[(num - 1) % len(_PRIME_TEMPLATES)]
    label     = f"𝐏𝐫𝐢𝐦𝐞{num}"

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not is_admin(update.effective_user.id):
            return
        if not update.effective_chat or not update.message:
            return
        if not _is_primary_bot(context):
            return
        raw  = (update.message.text or "").strip()
        base = _extract_base(raw, cmd_names, context)
        if not base:
            return await update.message.reply_text(f"Usage: {cmd_names[0]} <text>")
        chat_id = update.effective_chat.id
        bots    = [b for b in all_bot_instances if b is not None] or [context.bot]
        _last   = [""]
        def make_name():
            e1 = random.choice(emoji_pool)
            e2 = random.choice(emoji_pool)
            sf = make_suffix()
            c  = tmpl(e1, e2, base, sf)[:255]
            if c == _last[0]:
                c = tmpl(random.choice(emoji_pool), random.choice(emoji_pool), base, make_suffix())[:255]
            _last[0] = c
            return c
        async def nc_loop(stop_event: asyncio.Event):
            await _prime_hyperblitz_engine(chat_id, bots, stop_event, make_name)
        await task_controller.start_task(chat_id, "nc", nc_loop)
        e_preview = random.choice(emoji_pool)
        await update.message.reply_text(
            f"{label} 𝙋𝙍𝙞𝙈𝙀 𝘼𝘾𝙏𝙄𝙑𝙀🦋\n"
        )
    return handler

prime1_handler  = _make_prime_nc_handler(1,  _PRIME_POOLS[0])
prime2_handler  = _make_prime_nc_handler(2,  _PRIME_POOLS[1])
prime3_handler  = _make_prime_nc_handler(3,  _PRIME_POOLS[2])


_POLLINATIONS_URL = (
    "https://image.pollinations.ai/prompt/{prompt}"
    "?width=1024&height=1024&model=flux&nologo=true&enhance=true"
)

def _download_image_sync(prompt: str) -> bytes:
    encoded = urllib.parse.quote(prompt, safe="")
    url = _POLLINATIONS_URL.format(prompt=encoded)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

async def aiimg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    +aiimg <prompt>  or  /aiimg <prompt>
    Generates an AI image using Pollinations.ai (free, no API key needed).
    Sends the image directly to the current chat.

    Examples:
      +aiimg anime girl with blue hair
      +aiimg dark warrior in rain cinematic
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    prompt = _extract_base(raw, ("+aiimg", "aiimg", "/aiimg"), context)
    if not prompt:
        return await update.message.reply_text(
            "Usage: +aiimg <prompt>\n"
            "Example: +aiimg anime girl with blue hair glowing eyes"
        )

    wait_msg = await update.message.reply_text(
        f"🎨 Generating AI image…\n"
        f"📝 Prompt: {prompt[:80]}"
    )
    loop = asyncio.get_running_loop()
    try:
        img_bytes = await asyncio.wait_for(
            loop.run_in_executor(None, _download_image_sync, prompt),
            timeout=70,
        )
    except asyncio.TimeoutError:
        await wait_msg.edit_text("❌ Generation timed out. Try a simpler prompt.")
        return
    except Exception as e:
        await wait_msg.edit_text(f"❌ Failed: {e}")
        return

    img_file = io.BytesIO(img_bytes)
    img_file.name = "ai_image.jpg"
    bot = all_bot_instances[0] if all_bot_instances else context.bot
    try:
        await bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=img_file,
            caption=(
                f"🎨 *AI Image*\n"
                f"📝 {prompt[:120]}\n\n"
                f"💦 𝘣y ᎮᏒᎥᎷᏋ⚡"
            ),
            parse_mode="Markdown",
        )
        await wait_msg.delete()
    except Exception as e:
        await wait_msg.edit_text(f"❌ Failed to send image: {e}")


async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /leave — Makes ALL bots leave the current group chat.
    Primary bot sends confirmation before leaving.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]

    try:
        await update.message.reply_text(
            f"𝙂𝘾 𝙇𝙀𝘼𝙑𝙀 𝙇𝙀 𝙍𝙃𝘼({len(bots)} bots)\n"
        )
    except Exception:
        pass

    await asyncio.sleep(0.5)

    await task_controller.stop_all_for_chat(chat_id)
    known_chats.discard(chat_id)
    save_groups(known_chats)

    async def _leave_one(bot):
        try:
            await bot.leave_chat(chat_id)
        except Exception:
            pass

    await asyncio.gather(*[_leave_one(bot) for bot in bots], return_exceptions=True)


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable mute mode; non-admin messages are deleted until /unmute."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    mute_chats.add(chat_id)
    await update.message.reply_text("🔇 𝙈𝙐𝙏𝙀 𝙊𝙉")


async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable mute mode for the current chat."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    mute_chats.discard(chat_id)
    await update.message.reply_text("🔉 𝙈𝙐𝙏𝙀 𝙊𝙁𝙁")


async def ncdel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -ncdel — TOGGLE.
    When ON: every NEW_CHAT_TITLE service message from a non-admin user
    is immediately deleted. So if an enemy bot/user tries to NC (change
    the group title), their service message ("X changed group name to Y")
    is wiped instantly — making their NC invisible.
    Bot needs delete_messages admin right.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    if chat_id in ncdel_chats:
        ncdel_chats.discard(chat_id)
        await update.message.reply_text(
            "🌑 𝙉𝘾𝘿𝙀𝙇 𝙊𝙁𝙁"
        )
    else:
        ncdel_chats.add(chat_id)
        await update.message.reply_text(
            "🌕 𝙉𝘾𝘿𝙀𝙇 𝙊𝙉\n"
        )


async def stopnc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop all NC rename tasks in the current chat."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    stopped = 0
    for task_type in ("nc",):
        if await task_controller.stop_task(chat_id, task_type):
            stopped += 1
    if stopped:
        await update.message.reply_text("🛑 𝙎𝙏𝙊𝙋𝙋𝙀𝘿 𝙉𝘾")
    else:
        await update.message.reply_text("𝙉𝙊 𝙉𝘾 𝙄𝙎 𝙍𝙐𝙉𝙉𝙄𝙉𝙂 ")


async def gclist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /gclist — Lists all group chat IDs the bot has seen.
    Also tries to fetch the current title for each group.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return

    if not known_chats:
        return await update.message.reply_text(" No groups known yet.")

    lines = [f" 𝙆𝙉𝙊𝙒𝙉 𝙂𝘾𝙎({len(known_chats)})\n"]
    bot = context.bot
    for cid in list(known_chats):
        try:
            chat = await bot.get_chat(cid)
            title = chat.title or "—"
        except Exception:
            title = "?"
        status_icons = []
        if cid in mute_chats:
            status_icons.append("🔇")
        if cid in ncdel_chats:
            status_icons.append("🗑")
        if cid in autoreact_chats:
            status_icons.append("😂")
        icons = " ".join(status_icons)
        lines.append(f"• {title[:35]} {icons}\n  ID: {cid}")

    await update.message.reply_text("\n".join(lines))


_NO_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
)
_ALL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=False,
    can_invite_users=True,
    can_pin_messages=False,
)


async def restrict_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /restrict — Reply to a user's message → restrict all their permissions.
    Bot must be admin with restrict_members right.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return

    target = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            return await update.message.reply_text("Usage: /restrict (reply to user)")
        try:
            target = await context.bot.get_chat_member(update.effective_chat.id, target_id)
            target = target.user
        except Exception:
            return await update.message.reply_text("❌ Could not find that user.")

    if not target:
        return await update.message.reply_text("Usage: /restrict (reply to a message)")

    if is_admin(target.id):
        return await update.message.reply_text("❌ Cannot restrict an admin.")

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=_NO_PERMS,
        )
        name = target.first_name or str(target.id)
        await update.message.reply_text(
            f"🔒  @{target.username or name} restricted\n"
            f"All permissions removed. /unrestrict to restore."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot lacks restrict_members permission.")
    except BadRequest as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def unrestrict_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /unrestrict — Reply to a restricted user → restore all normal permissions.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return

    target = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target_id = int(context.args[0])
            member = await context.bot.get_chat_member(update.effective_chat.id, target_id)
            target = member.user
        except Exception:
            return await update.message.reply_text("Usage: /unrestrict (reply to user)")

    if not target:
        return await update.message.reply_text("Usage: /unrestrict (reply to a message)")

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=_ALL_PERMS,
        )
        name = target.first_name or str(target.id)
        await update.message.reply_text(
            f"🔓  @{target.username or name} unrestricted\n"
            f"All permissions restored."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot lacks restrict_members permission.")
    except BadRequest as e:
        await update.message.reply_text(f"❌ Error: {e}")


_REACT_RANDOM = [
    "👍","❤️","🔥","🥰","👏","😁","🤔","🤯","😱","🤩",
    "🎉","💯","🦄","⚡","🌚","💫","🏆","😎","👾","🫡",
    "🎃","🎄","🎆","✨","🍓","🍾","💋","🙏","👀","🫶",
]
_REACT_HEART = [
    "❤️","🧡","💛","💚","💙","💜","🖤","🤍","🤎","❤️‍🔥",
    "💝","💖","💗","💓","💞","💕","💘","💟","🫀","🥰",
]
_REACT_BOOM = [
    "🔥","⚡","💥","🤯","😱","🏆","👊","💣","🤩","🚀",
    "🎯","💫","⭐","🌟","😈","👑","🦁","🐉","🔱","⚔️",
]


async def _do_react_one(bot, chat_id: int, msg_id: int, emoji: str):
    try:
        await bot.set_message_reaction(
            chat_id,
            msg_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
            is_big=False,
        )
    except Exception:
        pass

async def _do_react(bots: list, chat_id: int, msg_id: int, style: str):
    if style == "heart":
        emoji = random.choice(_REACT_HEART)
    elif style == "boom":
        emoji = random.choice(_REACT_BOOM)
    elif style == "custom":
        emoji = custom_react_emojis.get(chat_id, "💦")
    else:
        emoji = random.choice(_REACT_RANDOM)
    await asyncio.gather(
        *[_do_react_one(b, chat_id, msg_id, emoji) for b in bots],
        return_exceptions=True,
    )


async def autoreact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -autoreact — Toggle: react to every incoming message with a random emoji.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if autoreact_chats.get(chat_id) == "random":
        autoreact_chats.pop(chat_id, None)
        await update.message.reply_text("😶 𝙍𝙀𝘼𝘾𝙏 𝙊𝙁𝙁")
    else:
        autoreact_chats[chat_id] = "random"
        await update.message.reply_text(
            "😂 𝙍𝙀𝘼𝘾𝙏 𝙊𝙉 — to every message\n"
            "-autoreact again to off · /stopreact to stop"
        )

async def stopreact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id in autoreact_chats:
        autoreact_chats.pop(chat_id)
        custom_react_emojis.pop(chat_id, None)
        await update.message.reply_text("😶 𝙍𝙀𝘼𝘾𝙏 𝙎𝙏𝙊𝙋𝙋𝙀𝘿")
    else:
        await update.message.reply_text("No auto react active here.")


async def react_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -react <emoji>
    React to every incoming message with your chosen emoji.
    -react (no emoji) → off.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    chat_id = update.effective_chat.id
    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-react", "react", "/react"), context)

    if not base:
        if autoreact_chats.get(chat_id) == "custom":
            autoreact_chats.pop(chat_id)
            custom_react_emojis.pop(chat_id, None)
            return await update.message.reply_text("😶 𝙍𝙀𝘼𝘾𝙏 𝙊𝙁𝙁")
        return await update.message.reply_text("Usage: -react <emoji>  e.g. -react 🔥")

    emoji_char = base.split()[0]
    custom_react_emojis[chat_id] = emoji_char
    autoreact_chats[chat_id] = "custom"
    await update.message.reply_text(
        f"✨ 𝙍𝙀𝘼𝘾𝙏 𝙊𝙉 → {emoji_char}\n"
    )


async def _set_menu_media(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_key: str, media_kind: str):
    if not update.effective_user or not is_admin(update.effective_user.id) or not update.message:
        return
    ref = update.message.reply_to_message or update.message
    photo = ref.photo[-1] if ref.photo else None
    doc_img = ref.document if ref.document and ref.document.mime_type and ref.document.mime_type.startswith("image/") else None
    video = ref.video if ref.video else None
    anim = ref.animation if ref.animation else None
    doc_vid = ref.document if ref.document and ref.document.mime_type and ref.document.mime_type.startswith("video/") else None

    selected = {}
    if media_kind == "photo":
        if photo:
            selected["photo_id"] = photo.file_id
        elif doc_img:
            selected["document_id"] = doc_img.file_id
        else:
            return await update.message.reply_text(f"❌ Reply to a photo or send one with /menupic{menu_key if menu_key != '0' else ''}")
    else:
        if video:
            selected["video_id"] = video.file_id
        elif anim:
            selected["animation_id"] = anim.file_id
        elif doc_vid:
            selected["document_id"] = doc_vid.file_id
        else:
            return await update.message.reply_text(f"❌ Reply to a video/GIF or send one with /menuvid{menu_key if menu_key != '0' else ''}")

    _menu_media[str(menu_key)] = selected
    save_menu_media(_menu_media)
    label = "𝙈𝙀𝙉𝙐 𝙋𝙄𝘾" if media_kind == "photo" else "𝙈𝙀𝙉𝙐 𝙑𝙄𝘿𝙀𝙊"
    await update.message.reply_text(f"✅ {label}{menu_key if menu_key != '0' else ''} 𝙎𝙀𝙏")


async def menupic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_menu_media(update, context, "0", "photo")


async def menuvid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_menu_media(update, context, "0", "video")


def _make_menu_media_cmd(menu_key: str, media_kind: str):
    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await _set_menu_media(update, context, menu_key, media_kind)
    return callback


async def menuclear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /menuclear — Remove any attached photo/video from the menu.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return

    _menu_media.clear()
    save_menu_media(_menu_media)
    await update.message.reply_text("✨ 𝘾𝙇𝙀𝘼𝙍𝙀𝘿 𝙈𝙀𝙉𝙐")


SLIDE_TEXTS = [
    "𝐂ʜᴜ𝐏 𝐑ɴᴅʏ𝐊 𝐁ᴀᴄʜ𝐄 𓂃🇦🇨𓂂",
    "𝐓ᴇʀ𝐈 𝐌ᴀ𝐀 𝐊ɪ 𝐂ʜᴜ𝐓 𓂃🇦🇩𓂂"   
    "𝐓ᴇʀ𝐈 𝐌ᴀ𝐀 𝐖ᴀ𝐀 𝐂ʜᴏ𝐃 𝐃ᴜɴɢ𝐀 𝐑ɴᴅʏ𝐊 𓂃🇦🇫𓂂",
    "𝐅ʀᴀɴ𝐊 𝐊ᴀɪs𝐄 𝐇ᴏ 𝐑ᴀʜ𝐀 𝐏ɪʟʟ𝐄 𓂃🇦🇬𓂂",
    "ᎮᏒᎥᎷᏋ 𝐁ᴀᴀ𝐏 𝐊ᴏ 𝐌ᴀ𝐓 𝐁ʜᴜ𝐋 𝐁ᴇᴛ𝐀 𓂃🇦🇮𓂂",
    "𝐓ᴇʀ𝐈 𝐁ᴇʜᴇ𝐍 𝐂ʜᴏᴅ𝐔 𝐓ᴏ𝐇 𝐑ᴏ𝐊 𝐋ᴇɢ𝐀 𝐊ʏ𝐀 𓂃🇦🇱𓂂",
    "𝐀ᴡᴀᴀ𝐙 𝐌ᴀ𝐓 𝐍ɪᴋᴀ𝐋 𝐂ʜᴜᴅᴀᴋᴋᴀ𝐃 𓂃🇦🇴𓂂",
    "ᎮᏒᎥᎷᏋ 𝐁ᴀᴀ𝐏 𝐒ᴇ 𝐋ᴀᴅᴇɢ𝐀 𓂃🇦🇶𓂂",
    "𝐀ʙᴇ𝐘 𝐍ᴏʀᴍɪ𝐄 𝐓ᴇʀ𝐈 𝐌ᴀᴜs𝐈 𝐂ʜᴜ𝐃 𝐆ᴀʏ𝐈 𓂃🇦🇷𓂂",
    "𝐇ᴀᴋʟ𝐄 𝐒ᴀʟ𝐄 𝐀ᴜᴋᴀ𝐓 𝐊ʏ𝐀 𝐇ᴀ𝐈 𝐓ᴇʀ𝐈 𓂃🇦🇹𓂂 ",
    "𝐁ᴇʜᴇ𝐍 𝐂ʜᴜᴅ𝐀 𝐏ɪʟʟ𝐄 𓂃🇦🇲𓂂",
     "𝐓ᴍᴋʙ 𝐑ɴᴅʏ ᴋᴇ 𝐋ᴀᴅᴋᴇ 😈🖕🏻😈🖕🏻😈",
    "𝐓ᴇʀɪ ᴍᴀᴀ ᴍᴀʀ ɢʏɪ ¿😆😆😆",
    "𝐀ᴀʀ ꜱᴀᴍᴀɴᴅᴀʀ ᴘᴀᴀʀ ꜱᴀᴍᴀɴᴅᴀʀ ʙᴇᴇᴄʜ ᴍɪᴇ ʜᴀɪ ɴᴀɪʏᴀ ᴘʜʟᴇ ᴛᴇʀɪ ʙʜᴇɴ चोदू ʙᴀᴀᴅ ᴍɪᴇ चोदू ᴍᴀɪʏᴀ ¡! 🥰🖕🏻🥰🖕🏻🥰🖕🏻",
     "𝐓ᴇʀɪ 𝐌ᴀᴀ ʜᴜᴍᴇꜱʜᴀ ᴍᴜᴊʜꜱᴇ ʜɪ ᴋʏᴜ चुडती है ¡! 😡🤬😡🤬😡",
    "𝐃ᴇᴋʜ ᴀᴀʀ ᴛᴇʀɪ 𝐌ᴀᴀ ᴋᴀ ɴᴀɴɢᴀ ᴅᴀɴᴄᴇ ᴅɪᴋʜᴀᴜ ! 🩰🧑🏻‍🩰",
   "𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐆ᴜʟᴀʙɪ 𝐂ʜᴜᴛ ᴍɪᴇ 𝐌ᴜᴛ ᴋʀ ʙʜᴀɢ ᴊᴀᴜɢᴀ 𝐁ꜱᴅᴋ ! 😆",
    "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴄʜᴏᴅɴᴇ ᴀʀʜᴀ ʜᴜ ʀᴋ ᴡʜɪ ɢᴜʟᴀᴍ ! 😾",
    "𝐓ᴇʀɪ ʙʜᴇɴ ᴋᴇ ʙᴏᴏʙɪᴇꜱ ᴋᴇ ʙᴇᴇᴄʜ ᴍɪᴇ ʟɴᴅ ꜰᴀꜱᴀ ᴋʀ ᴍᴜᴛʜ ᴍᴀᴀʀ ᴅᴜɢᴀ ʙꜱᴅᴋ 😆",
    "𝐓ᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍɪᴇ ᴍᴀɢɢɪᴇ ʙɴᴀ ᴋʀ ᴍᴜᴛʜ ʙʜᴀʀ ᴅᴜɢᴀ𝐓ᴇʀɪ ᴍᴀᴀ ʙʜᴛ ʀᴏᴛɪ ᴇʏ ʙɪʟᴋᴜʟ 𝐓ᴇʀɪ ᴛʀʜ ᴅᴏɴᴏ ʀɴᴅʏ ʀᴏɴᴀ ᴋʀᴛᴇ ʜᴏ ᴇᴡᴡ ! 😆",
    "𝐓ᴇʀɪ ʙʜᴇɴ ᴋɪ ɢᴜʟᴀʙɪ ᴄʜᴛ ᴋᴀᴀᴛ ᴅᴜɢᴀ ɢᴜʟᴀᴍ ! 😆",
          
]

async def _slide_reply_burst(bot, chat_id: int, message_id: int, count: int = 6):
    """Fire `count` rapid replies to a specific message using one bot."""
    for i in range(count):
        text = random.choice(SLIDE_TEXTS)
        try:
            await bot.send_message(
                chat_id,
                text,
                reply_to_message_id=message_id,
            )
        except (RetryAfter, Forbidden, BadRequest):
            break
        except Exception:
            pass
        await asyncio.sleep(0)


async def slidereply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -slidereply — Reply to a user's message to set them as the slide-reply target.
    Every message they send after that gets a rapid burst of replies from all bots.
    -slidereply again (while active) toggles it off.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    chat_id = update.effective_chat.id

    target_user = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        try:
            uid_arg = int(context.args[0])
            slide_reply_targets[chat_id] = uid_arg
            await update.message.reply_text(
                f"📩 𝙎𝙇𝙄𝘿𝙀 𝙍𝙀𝙋𝙇𝙔 \n"
                f"🎯 Target UID: {uid_arg} \n"
            )
            return
        except ValueError:
            pass

    if target_user is None:
        if chat_id in slide_reply_targets:
            slide_reply_targets.pop(chat_id)
            return await update.message.reply_text("💬 𝙎𝙇𝙄𝘿𝙀 𝙍𝙀𝙋𝙇𝙔 𝙊𝙁𝙁")
        return await update.message.reply_text("Usage: -slidereply (reply to target user's message)")

    if is_admin(target_user.id):
        return await update.message.reply_text("❌ Cannot target an admin.")

    if slide_reply_targets.get(chat_id) == target_user.id:
        slide_reply_targets.pop(chat_id)
        return await update.message.reply_text(
            f"💬 𝙎𝙇𝙄𝘿𝙀𝙍𝙀𝙋𝙇𝙔 𝙊𝙁𝙁 — @{target_user.username or target_user.first_name}"
        )

    slide_reply_targets[chat_id] = target_user.id
    name = target_user.username or target_user.first_name or str(target_user.id)
    await update.message.reply_text(
        f"💬 𝙎𝙇𝙄𝘿𝙀𝙍𝙀𝙋𝙇𝙔 𝙊𝙉 \n"
        f"🎯 Target: @{name}\n"
    )


async def stopslidereply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id in slide_reply_targets:
        slide_reply_targets.pop(chat_id)
        await update.message.reply_text("💬 𝙎𝙇𝙄𝘿𝙀𝙍𝙀𝙋𝙇𝙔  𝙎𝙏𝙊𝙋𝙋𝙀𝘿")
    else:
        await update.message.reply_text("No slidereply active here.")


_SLIDE_SYMS = [
              " "
]

async def plus_slide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -slide <text>
    ─────────────────────────────────────────────────────────
    SLIDE SPAM — reply-bomb with all bots + modern symbols.

    • Reply to any message → all bots reply to THAT message
    • Each bot picks a random modern symbol pair each time
    • Fires as fast as possible across all 10 bots in parallel
    • /stop stops it like any other task

    Example:
      -slide gn         (while replying to a user's message)
    ─────────────────────────────────────────────────────────
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not _is_primary_bot(context):
        return
    if not update.effective_chat or not update.message:
        return
    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "↩️ Reply to a message, then use -slide <text>"
        )

    raw_text = (update.message.text or "").strip()
    if raw_text.lower().startswith("-slide"):
        base = raw_text[6:].strip()
    else:
        base = " ".join(context.args) if context.args else ""
    if not base:
        return await update.message.reply_text("Usage: -slide <text>")

    chat_id       = update.effective_chat.id
    target_msg_id = update.message.reply_to_message.message_id
    bots          = [b for b in all_bot_instances if b is not None] or [context.bot]

    async def _bot_slide_worker(bot, stop_event: asyncio.Event):
        while not stop_event.is_set():
            sym1 = random.choice(_SLIDE_SYMS)
            sym2 = random.choice(_SLIDE_SYMS)
            text = f"{sym1} {base} {sym2}"
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_to_message_id=target_msg_id,
                )
            except RetryAfter as e:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=float(e.retry_after))
                except asyncio.TimeoutError:
                    pass
            except (BadRequest, Forbidden, TimedOut, NetworkError):
                pass
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.05)
            except asyncio.TimeoutError:
                pass

    async def slide_loop(stop_event: asyncio.Event):
        workers = [
            asyncio.create_task(_bot_slide_worker(bot, stop_event))
            for bot in bots
        ]
        try:
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            for w in workers:
                if not w.done():
                    w.cancel()

    await task_controller.start_task(chat_id, "spam", slide_loop)
    await update.message.reply_text(
        f" 𝙎𝙇𝙄𝘿𝙀 𝙎𝙏𝘼𝙍𝙏𝙀𝘿 \n"
    )


async def spam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -spam <text>
    All bots spam-send the text to the current chat as fast as possible.
    /stopspam to stop.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-spam", "💦spam", "/spam"), context)
    if not base:
        return await update.message.reply_text("Usage: -spam <text>")

    chat_id = update.effective_chat.id
    bots = [b for b in all_bot_instances if b is not None] or [context.bot]

    async def _bot_spam_worker(bot, stop_event: asyncio.Event):
        while not stop_event.is_set():
            try:
                await bot.send_message(chat_id=chat_id, text=base)
            except RetryAfter as e:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=float(e.retry_after))
                except asyncio.TimeoutError:
                    pass
            except (BadRequest, Forbidden):
                break
            except (TimedOut, NetworkError):
                pass
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, spam_delay))
            except asyncio.TimeoutError:
                pass

    async def spam_loop(stop_event: asyncio.Event):
        workers = [asyncio.create_task(_bot_spam_worker(bot, stop_event)) for bot in bots]
        try:
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            for w in workers:
                if not w.done():
                    w.cancel()

    await task_controller.start_task(chat_id, "spam", spam_loop)
    await update.message.reply_text(
        f"💬 𝙎𝙋𝘼𝙈 𝙎𝙏𝘼𝙍𝙏𝙀𝘿 \n"
    )


async def stopspam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    stopped = await task_controller.stop_task(update.effective_chat.id, "spam")
    if stopped:
        await update.message.reply_text("🛑 𝙎𝙋𝘼𝙈 𝙎𝙏𝙊𝙋𝙋𝙀𝘿 ")
    else:
        await update.message.reply_text("No spam running here.")


async def autoreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -autoreply <text>
    Every incoming message in this chat gets an automatic reply with <text>.
    -autoreply (no text) or /stopreply to turn off.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-autoreply", "💦autoreply", "/autoreply"), context)
    chat_id = update.effective_chat.id

    if not base:
        if chat_id in autoreply_chats:
            autoreply_chats.pop(chat_id)
            return await update.message.reply_text("𝘼𝙐𝙏𝙊𝙍𝙀𝙋𝙇𝙔 𝙊𝙁𝙁")
        return await update.message.reply_text("Usage: -autoreply <text>")

    autoreply_chats[chat_id] = base
    await update.message.reply_text(
        f"💬 𝘼𝙐𝙏𝙊𝙍𝙀𝙋𝙇𝙔 𝙊𝙉 \n"
    )


async def stopautoreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id in autoreply_chats:
        autoreply_chats.pop(chat_id)
        await update.message.reply_text("𝘼𝙐𝙏𝙊𝙍𝙀𝙋𝙇𝙔  𝙎𝙏𝙊𝙋𝙋𝙀𝘿")
    else:
        await update.message.reply_text("No autoreply active here.")


async def targetreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    -targetreply <text>  (reply to target user's message)
    Every message from that user gets an automatic reply with <text>.
    -targetreply on the same user (no text) or /stopreply to stop.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    base = _extract_base(raw, ("-targetreply", "💦targetreply", "/targetreply"), context)
    chat_id = update.effective_chat.id

    target_user = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user

    if not target_user:
        if chat_id in targetreply_chats:
            targetreply_chats.pop(chat_id)
            return await update.message.reply_text("𝙏𝘼𝙍𝙂𝙀𝙏𝙍𝙀𝙋𝙇𝙔  𝙊𝙁𝙁")
        return await update.message.reply_text(
            "Usage: -targetreply <text> (reply to the target user's message)"
        )

    if is_admin(target_user.id):
        return await update.message.reply_text("❌ Cannot target an admin.")

    if not base:
        if targetreply_chats.get(chat_id, {}).get("uid") == target_user.id:
            targetreply_chats.pop(chat_id)
            return await update.message.reply_text("𝙏𝘼𝙍𝙂𝙀𝙏𝙍𝙀𝙋𝙇𝙔  𝙊𝙁𝙁 ")
        return await update.message.reply_text(
            "Usage: -targetreply <text> (reply to the target user's message)"
        )

    name = target_user.username or target_user.first_name or str(target_user.id)
    targetreply_chats[chat_id] = {"uid": target_user.id, "text": base}
    await update.message.reply_text(
        f"🎯 𝙏𝘼𝙍𝙂𝙀𝙏𝙍𝙀𝙋𝙇𝙔 𝙊𝙉\n"
        f"👤 Target: @{name}\n"
    )


async def stoptargetreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id in targetreply_chats:
        targetreply_chats.pop(chat_id)
        await update.message.reply_text("𝙏𝘼𝙍𝙂𝙀𝙏𝙍𝙀𝙋𝙇𝙔 𝙎𝙏𝙊𝙋𝙋𝙀𝘿")
    else:
        await update.message.reply_text("No targetreply active here.")


# Pyrogram is required by the user-login commands.
# Try a normal import first. If the hosting service did not install the
# requirements file, make one automatic installation attempt at startup.
_PYRO_AVAILABLE = False

def _load_pyrogram():
    global PyroClient, SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
    global FloodWait, UserAlreadyParticipant, PeerFlood
    global UserPrivacyRestricted, ChatAdminRequired, UserNotParticipant
    global ChatPrivileges, _PYRO_AVAILABLE

    # Pyrogram's sync module calls asyncio.get_event_loop() during import.
    # Python 3.14 can raise RuntimeError here when the bot is already inside
    # asyncio.run(). Temporarily make get_event_loop return the active loop
    # only while Pyrogram is being imported.
    _original_get_event_loop = asyncio.get_event_loop
    _running_loop = None
    try:
        _running_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if _running_loop is not None:
        asyncio.get_event_loop = lambda: _running_loop

    try:
        from pyrogram import Client as _Client
        from pyrogram.errors import (
            SessionPasswordNeeded as _SessionPasswordNeeded,
            PhoneCodeInvalid as _PhoneCodeInvalid,
            PhoneCodeExpired as _PhoneCodeExpired,
            FloodWait as _FloodWait,
            UserAlreadyParticipant as _UserAlreadyParticipant,
            PeerFlood as _PeerFlood,
            UserPrivacyRestricted as _UserPrivacyRestricted,
            ChatAdminRequired as _ChatAdminRequired,
            UserNotParticipant as _UserNotParticipant,
        )
        from pyrogram.types import ChatPrivileges as _ChatPrivileges

        PyroClient = _Client
        SessionPasswordNeeded = _SessionPasswordNeeded
        PhoneCodeInvalid = _PhoneCodeInvalid
        PhoneCodeExpired = _PhoneCodeExpired
        FloodWait = _FloodWait
        UserAlreadyParticipant = _UserAlreadyParticipant
        PeerFlood = _PeerFlood
        UserPrivacyRestricted = _UserPrivacyRestricted
        ChatAdminRequired = _ChatAdminRequired
        UserNotParticipant = _UserNotParticipant
        ChatPrivileges = _ChatPrivileges
        _PYRO_AVAILABLE = True
        return True
    except (ImportError, RuntimeError) as exc:
        logger.error("Pyrogram import failed: %s", exc)
        return False
    finally:
        if _running_loop is not None:
            asyncio.get_event_loop = _original_get_event_loop

# Do not install packages at runtime. AWS/VPS deployments should install
# requirements.txt once before starting the bot. This keeps startup deterministic.

if not _PYRO_AVAILABLE:
    logger.error("Pyrogram is unavailable. Automatic installation was blocked or failed; restart the bot and try again.")

# Fill in your own Telegram API credentials here (from https://my.telegram.org).
# Keep these values private. API_ID must be an integer; API_HASH is a string.
API_ID = 35455608        # <-- enter your API ID here
API_HASH = "42b542863c07baccd1427d0754c86686"       # <-- enter your API HASH here

USER_API_FILE = "user_api.json"

def _load_user_api() -> Dict:
    try:
        if os.path.exists(USER_API_FILE):
            with open(USER_API_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_user_api(data: Dict):
    try:
        with open(USER_API_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

_user_api: Dict = _load_user_api()
# The API credentials are configured directly in this Python file.
if API_ID and API_HASH:
    _user_api["api_id"] = int(API_ID)
    _user_api["api_hash"] = API_HASH
    _save_user_api(_user_api)
_pyro_client: Optional[Any] = None
_pyro_login_state: Dict = {}


async def _get_pyro():
    global _pyro_client
    if _pyro_client and _pyro_client.is_connected:
        return _pyro_client
    return None


async def _connect_pyro_from_saved() -> bool:
    global _pyro_client
    if not _PYRO_AVAILABLE:
        return False
    api_id    = _user_api.get("api_id")
    api_hash  = _user_api.get("api_hash")
    session   = _user_api.get("session_string")
    if not (api_id and api_hash and session):
        return False
    try:
        client = PyroClient(
            "nc_user",
            api_id=int(api_id),
            api_hash=api_hash,
            session_string=session,
            in_memory=True,
        )
        await client.start()
        _pyro_client = client
        me = await client.get_me()
        pass
        return True
    except Exception as e:
        print(f"⚠️  User account auto-connect failed: {e}")
        return False


async def userlogin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /userlogin +91XXXXXXXXXX
    Start login — Telegram will send you an OTP.
    """
    global _pyro_client
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message or not _is_primary_bot(context):
        return
    if not _PYRO_AVAILABLE:
        return await update.message.reply_text("❌ Pyrogram could not be loaded. The hosting service must allow Python package installation. Restart the bot once and try again.", parse_mode="Markdown")
    api_id   = _user_api.get("api_id")
    api_hash = _user_api.get("api_hash")
    if not (api_id and api_hash):
        return await update.message.reply_text(
            "❌ Fill API_ID and API_HASH near the user API configuration in this Python file, then restart the bot."
        )
    args = context.args or []
    if not args:
        return await update.message.reply_text(
            "Usage: /userlogin <phone>  e.g. /userlogin +919876543210"
        )
    phone = args[0].strip().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"\+?[1-9]\d{7,14}", phone):
        return await update.message.reply_text(
            "❌ Invalid phone number. Use international format, e.g. +919876543210"
        )
    # Always discard an older pending login so its OTP hash cannot be reused.
    old_client = _pyro_login_state.get("client")
    if old_client:
        try:
            await old_client.disconnect()
        except Exception:
            pass
    _pyro_login_state.clear()
    _user_api["phone"] = phone
    _save_user_api(_user_api)
    try:
        client = PyroClient(
            "nc_login_tmp",
            api_id=int(api_id),
            api_hash=api_hash,
            in_memory=True,
        )
        await client.connect()
        sent = await client.send_code(phone)
        _pyro_login_state["phone"]  = phone
        _pyro_login_state["hash"]   = sent.phone_code_hash
        _pyro_login_state["client"] = client
        await update.message.reply_text(
            f"📲 OTP sent to {phone}!\n"
            f"Enter it with: /userotp <code>\n"
            f"Example: /userotp 12345"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send OTP: {e}")


async def userotp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /userotp <code>
    Complete login with the OTP you received.
    """
    global _pyro_client
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message or not _is_primary_bot(context):
        return
    if not _PYRO_AVAILABLE:
        return await update.message.reply_text("❌ Pyrogram could not be loaded. The hosting service must allow Python package installation. Restart the bot once and try again.", parse_mode="Markdown")
    args = context.args or []
    if not args:
        return await update.message.reply_text("Usage: /userotp <code>")
    # Telegram OTPs may be displayed with spaces or hyphens.  Pyrogram
    # requires the actual numeric code only.
    code = re.sub(r"\D", "", "".join(args))
    if not code or not 3 <= len(code) <= 8:
        return await update.message.reply_text(
            "❌ Invalid OTP format. Enter the latest numeric code, e.g. /userotp 12345"
        )
    client            = _pyro_login_state.get("client")
    phone             = _pyro_login_state.get("phone")
    phone_code_hash   = _pyro_login_state.get("hash")
    if not (client and phone and phone_code_hash):
        return await update.message.reply_text(
            "❌ No login in progress. Use /userlogin <phone> first."
        )
    try:
        await client.sign_in(phone, phone_code_hash, code)
        session_str = await client.export_session_string()
        _user_api["session_string"] = session_str
        _save_user_api(_user_api)
        real_client = PyroClient(
            "nc_user",
            api_id=int(_user_api["api_id"]),
            api_hash=_user_api["api_hash"],
            session_string=session_str,
            in_memory=True,
        )
        await real_client.start()
        _pyro_client = real_client
        me = await real_client.get_me()
        _pyro_login_state.clear()
        try:
            await client.disconnect()
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ 👤 Logged in as: {me.first_name} (@{me.username or 'N/A'})\n"
            f"User account ready! Check status: /userstatus"
        )
    except SessionPasswordNeeded:
        await update.message.reply_text(
            "🔐 2FA enabled! Send password: /user2fa <password>"
        )
    except (PhoneCodeInvalid, PhoneCodeExpired):
        # Do not keep a stale phone_code_hash: it will cause the same error
        # on every subsequent attempt.
        _pyro_login_state.clear()
        try:
            await client.disconnect()
        except Exception:
            pass
        await update.message.reply_text(
            "❌ OTP rejected or expired. Request a fresh code with /userlogin, "
            "then enter only the newest Telegram code once."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Login failed: {e}")


async def user2fa_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /user2fa <password>
    Enter your 2FA password to complete login.
    """
    global _pyro_client
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message or not _is_primary_bot(context):
        return
    if not _PYRO_AVAILABLE:
        return await update.message.reply_text("❌ Pyrogram could not be loaded. The hosting service must allow Python package installation. Restart the bot once and try again.", parse_mode="Markdown")
    args = context.args or []
    if not args:
        return await update.message.reply_text("Usage: /user2fa <password>")
    password = " ".join(args)
    client   = _pyro_login_state.get("client")
    if not client:
        return await update.message.reply_text(
            "❌ No login in progress. Use /userlogin <phone> first."
        )
    try:
        await client.check_password(password)
        session_str = await client.export_session_string()
        _user_api["session_string"] = session_str
        _save_user_api(_user_api)
        real_client = PyroClient(
            "nc_user",
            api_id=int(_user_api["api_id"]),
            api_hash=_user_api["api_hash"],
            session_string=session_str,
            in_memory=True,
        )
        await real_client.start()
        _pyro_client = real_client
        me = await real_client.get_me()
        _pyro_login_state.clear()
        try:
            await client.disconnect()
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ 👤 Logged in as: {me.first_name} (@{me.username or 'N/A'})\n"
            f"User account ready!"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 2FA failed: {e}")


async def userlogout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _pyro_client
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text("❌ No user account connected.")
    try:
        await client.log_out()
    except Exception:
        pass
    _pyro_client = None
    _user_api.pop("session_string", None)
    _save_user_api(_user_api)
    await update.message.reply_text("👋 User account logged out.")


async def userstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return
    client = await _get_pyro()
    if not client:
        status = (
            "📊 User Account Status:\n"
            f"🔑 API set: {'✅' if _user_api.get('api_id') else '❌'}\n"
            f"📱 Session saved: {'✅' if _user_api.get('session_string') else '❌'}\n"
            f"🔴 Client: NOT connected\n\n"
            f"Setup: fill API_ID/API_HASH in the file → /userlogin → /userotp"
        )
    else:
        try:
            me = await client.get_me()
            status = (
                f"📊 User Account Status:\n"
                f"✅ Connected as: {me.first_name}\n"
                f"👤 Username: @{me.username or 'N/A'}\n"
                f"📱 Phone: {me.phone_number or 'N/A'}\n"
                f"🆔 ID: `{me.id}`"
            )
        except Exception as e:
            status = f"⚠️ Connected but error getting info: {e}"
    await update.message.reply_text(status, parse_mode="Markdown")


async def addbot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addbot @username [...]  or reply to a bot message → adds that bot.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text(
            "❌ User account not connected.\nSetup: fill API_ID/API_HASH in the file → /userlogin → /userotp"
        )
    chat_id = update.effective_chat.id
    usernames: List[str] = []
    if context.args:
        usernames = [u.lstrip("@") for u in context.args]
    elif (update.message.reply_to_message
          and update.message.reply_to_message.from_user
          and update.message.reply_to_message.from_user.username):
        usernames = [update.message.reply_to_message.from_user.username]
    if not usernames:
        return await update.message.reply_text(
            "Usage: /addbot @username  or reply to a bot message"
        )
    results: List[str] = []
    for uname in usernames:
        try:
            await client.add_chat_members(chat_id, uname)
            results.append(f"✅ @{uname} added")
        except UserAlreadyParticipant:
            results.append(f"ℹ️ @{uname} already in group")
        except Exception as e:
            results.append(f"❌ @{uname}: {type(e).__name__}")
    await update.message.reply_text("👥 Add Bot:\n" + "\n".join(results))


async def addallbots_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addallbots — Add ALL configured bots to this group via user account.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text("❌ User account not connected.")
    chat_id  = update.effective_chat.id
    wait_msg = await update.message.reply_text("⏳ 𝘼𝘿𝘿𝙄𝙉𝙂 𝘼𝙇𝙇 𝘽𝙊𝙏𝙎…")
    results: List[str] = []
    for bot in all_bot_instances:
        try:
            me    = await bot.get_me()
            uname = me.username
            if not uname:
                continue
            await client.add_chat_members(chat_id, uname)
            results.append(f"✅ @{uname}")
            await asyncio.sleep(0.5)
        except UserAlreadyParticipant:
            try:
                me = await bot.get_me()
                results.append(f"ℹ️ @{me.username} already in")
            except Exception:
                pass
        except Exception as e:
            try:
                me = await bot.get_me()
                results.append(f"❌ @{me.username}: {type(e).__name__}")
            except Exception:
                results.append(f"❌ Bot error: {type(e).__name__}")
    await wait_msg.edit_text(
        "👥 Add All Bots:\n" + ("\n".join(results) if results else "No results.")
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promote configured bot accounts and report verified results."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return

    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("👑 Checking bot admin status...")

    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        admin_ids = {admin.user.id for admin in admins}
    except Exception as exc:
        await status_msg.edit_text(
            f"❌ Cannot read group admins: {type(exc).__name__}"
        )
        return

    promoted = []
    already_admin = []
    failed = []

    # Deduplicate IDs, and count every configured bot only once.
    bots_by_id = {
        getattr(bot, "id", None): bot
        for bot in all_bot_instances
        if bot is not None and getattr(bot, "id", None) is not None
    }

    async def promote_one(bot_id: int, bot):
        username = getattr(bot, "username", None) or str(bot_id)
        if bot_id in admin_ids:
            already_admin.append(username)
            return

        # Telegram does not allow a bot to promote itself. A different bot
        # account must grant its admin rights.
        if bot_id == context.bot.id:
            failed.append(f"{username}: main bot cannot promote itself")
            return

        try:
            await context.bot.promote_chat_member(
                chat_id=chat_id,
                user_id=bot_id,
                is_anonymous=False,
                can_manage_chat=True,
                can_delete_messages=True,
                can_manage_video_chats=True,
                can_restrict_members=True,
                can_promote_members=True,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True,
                can_manage_topics=True,
            )
            # Confirm from Telegram rather than relying on the API call alone.
            member = await context.bot.get_chat_member(chat_id, bot_id)
            if member.status in ("administrator", "creator"):
                promoted.append(username)
            else:
                failed.append(f"{username}: Telegram did not confirm admin status")
        except Exception as exc:
            failed.append(f"{username}: {type(exc).__name__}")

    await asyncio.gather(
        *(promote_one(bot_id, bot) for bot_id, bot in bots_by_id.items()),
        return_exceptions=True,
    )

    total_admin = len(promoted) + len(already_admin)
    report = (
        f"👑 𝘼𝘿𝙈𝙄𝙉 𝙎𝙏𝘼𝙏𝙐𝙎 𝘾𝙃𝙀𝘾𝙆𝙀𝘿\n"
        f"✅ 𝙋𝙍𝙊𝙈𝙊𝙏𝙀𝘿 𝙉𝙊𝙒 : {len(promoted)}\n"
        f"ℹ️ 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝘼𝘿𝙈𝙄𝙉 : {len(already_admin)}\n"
        f"📊 𝙏𝙊𝙏𝘼𝙇 𝘼𝘿𝙈𝙄𝙉 𝘾𝙊𝙉𝙁𝙄𝙍𝙈𝙀𝘿 : {total_admin}/{len(bots_by_id)}"
    )
    if promoted:

        report += "\n\n𝙋𝙍𝙊𝙈𝙊𝙏𝙀𝘿 : " + ", ".join("@" + name for name in promoted)
    if already_admin:

        report += "\n\n𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝘼𝘿𝙈𝙄𝙉 : " + ", ".join("@" + name for name in already_admin)
    if failed:
        report += "\n\n𝙁𝘼𝙄𝙇𝙀𝘿 :\\n" + "\\n".join("• " + item for item in failed)

    await status_msg.edit_text(report)


async def upall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for admin_cmd, matching the 4.py command."""
    return await admin_cmd(update, context)




async def promotebot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /promotebot @username  or reply to a bot message → promote as full admin.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text("❌ User account not connected.")
    chat_id = update.effective_chat.id
    usernames: List[str] = []
    if context.args:
        usernames = [u.lstrip("@") for u in context.args]
    elif (update.message.reply_to_message
          and update.message.reply_to_message.from_user
          and update.message.reply_to_message.from_user.username):
        usernames = [update.message.reply_to_message.from_user.username]
    if not usernames:
        return await update.message.reply_text(
            "Usage: /promotebot @username  or reply to a bot message"
        )
    _full_admin = ChatPrivileges(
        can_manage_chat=True,
        can_change_info=True,
        can_delete_messages=True,
        can_invite_users=True,
        can_restrict_members=True,
        can_pin_messages=True,
        can_promote_members=True,
        can_manage_video_chats=True,
        is_anonymous=False,
    )
    results: List[str] = []
    for uname in usernames:
        try:
            await client.promote_chat_member(chat_id, uname, privileges=_full_admin)
            results.append(f"✅ @{uname} promoted")
        except ChatAdminRequired:
            results.append(f"❌ @{uname}: I'm not admin here")
        except Exception as e:
            results.append(f"❌ @{uname}: {type(e).__name__}")
    await update.message.reply_text("👑 Promote Bot:\n" + "\n".join(results))





# ─────────────────────────────────────────────────────────────────
# USER MODERATION COMMANDS
# Usage: reply to a user's message, or provide a numeric user ID/@username.
# The bot must have the appropriate administrator permissions in the group.
# ─────────────────────────────────────────────────────────────────

async def _resolve_moderation_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat = update.effective_chat
    if not message or not chat:
        return None

    replied = message.reply_to_message
    if replied and replied.from_user:
        return replied.from_user

    if not context.args:
        return None

    raw = context.args[0].strip()
    try:
        target_id = int(raw)
        member = await context.bot.get_chat_member(chat.id, target_id)
        return member.user
    except (ValueError, BadRequest):
        pass
    except Exception:
        return None

    # Telegram's Bot API can resolve public usernames through get_chat.
    try:
        target_chat = await context.bot.get_chat(raw if raw.startswith("@") else f"@{raw}")
        return target_chat if getattr(target_chat, "id", None) else None
    except Exception:
        return None


async def _moderation_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return False
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return False
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("This command only works in a group or supergroup.")
        return False
    return True


async def muteuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mute a member and automatically delete their future messages in this group."""
    if not await _moderation_guard(update, context):
        return
    target = await _resolve_moderation_target(update, context)
    if not target:
        return await update.message.reply_text(
            "Usage: reply to a user's message with /muteuser, "
            "or send /muteuser <user_id|@username>."
        )
    # Owner and sudo accounts are always exempt; bot accounts are not targets.
    if target.is_bot or is_admin(target.id):
        return await update.message.reply_text("❌ I won't mute a bot, owner, or sudo user.")

    chat_id = update.effective_chat.id
    try:
        await context.bot.restrict_chat_member(
            chat_id, target.id, permissions=_NO_PERMS
        )
        muted_users_by_chat.setdefault(chat_id, set()).add(target.id)
        await update.message.reply_text(
            f"🔇 Muted {('@' + target.username) if target.username else target.first_name}. "
            "Their future messages will be deleted."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot needs the restrict_members permission.")
    except BadRequest as exc:
        await update.message.reply_text(f"❌ Couldn't mute that user: {exc}")


async def unmuteuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unmute a member and stop auto-deleting their messages."""
    if not await _moderation_guard(update, context):
        return
    target = await _resolve_moderation_target(update, context)
    if not target:
        return await update.message.reply_text(
            "Usage: reply to a user's message with /unmuteuser, "
            "or send /unmuteuser <user_id|@username>."
        )
    chat_id = update.effective_chat.id
    try:
        await context.bot.restrict_chat_member(
            chat_id, target.id, permissions=_ALL_PERMS
        )
        chat_muted = muted_users_by_chat.get(chat_id)
        if chat_muted:
            chat_muted.discard(target.id)
            if not chat_muted:
                muted_users_by_chat.pop(chat_id, None)
        await update.message.reply_text(
            f"🔉 Unmuted {('@' + target.username) if target.username else target.first_name}."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot needs the restrict_members permission.")
    except BadRequest as exc:
        await update.message.reply_text(f"❌ Couldn't unmute that user: {exc}")


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban one member. Reply or use /ban <user_id|@username>."""
    if not await _moderation_guard(update, context):
        return
    target = await _resolve_moderation_target(update, context)
    if not target:
        return await update.message.reply_text(
            "Usage: reply to a user's message with /ban, or /ban <user_id|@username>."
        )
    if target.id == context.bot.id or is_admin(target.id):
        return await update.message.reply_text("❌ I won't ban a bot or sudo admin.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            f"🚫 Banned {('@' + target.username) if target.username else target.first_name}."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot needs the ban_members permission.")
    except BadRequest as exc:
        await update.message.reply_text(f"❌ Couldn't ban that user: {exc}")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban one member. Use /unban <user_id|@username>."""
    if not await _moderation_guard(update, context):
        return
    target = await _resolve_moderation_target(update, context)
    if not target:
        return await update.message.reply_text(
            "Usage: /unban <user_id|@username> (the user need not be in the group)."
        )
    try:
        await context.bot.unban_chat_member(
            update.effective_chat.id, target.id, only_if_banned=True
        )
        await update.message.reply_text(
            f"✅ Unbanned {('@' + target.username) if target.username else target.first_name}."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot needs the ban_members permission.")
    except BadRequest as exc:
        await update.message.reply_text(f"❌ Couldn't unban that user: {exc}")


async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick one member (ban then unban). Reply or use /kick <user_id|@username>."""
    if not await _moderation_guard(update, context):
        return
    target = await _resolve_moderation_target(update, context)
    if not target:
        return await update.message.reply_text(
            "Usage: reply to a user's message with /kick, or /kick <user_id|@username>."
        )
    if target.id == context.bot.id or is_admin(target.id):
        return await update.message.reply_text("❌ I won't kick a bot or an owner/sudo admin.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(
            update.effective_chat.id, target.id, only_if_banned=True
        )
        await update.message.reply_text(
            f"👢 Kicked {('@' + target.username) if target.username else target.first_name}."
        )
    except Forbidden:
        await update.message.reply_text("❌ Bot needs the ban_members permission.")
    except BadRequest as exc:
        await update.message.reply_text(f"❌ Couldn't kick that user: {exc}")


async def kickbot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /kickbot @username  or reply to a bot message → kick (ban+unban) from group.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text("❌ User account not connected.")
    chat_id = update.effective_chat.id
    usernames: List[str] = []
    if context.args:
        usernames = [u.lstrip("@") for u in context.args]
    elif (update.message.reply_to_message
          and update.message.reply_to_message.from_user
          and update.message.reply_to_message.from_user.username):
        usernames = [update.message.reply_to_message.from_user.username]
    if not usernames:
        return await update.message.reply_text(
            "Usage: /kickbot @username  or reply to a bot message"
        )
    results: List[str] = []
    for uname in usernames:
        try:
            await client.ban_chat_member(chat_id, uname)
            await asyncio.sleep(0.4)
            await client.unban_chat_member(chat_id, uname)
            results.append(f"✅ @{uname} kicked")
        except UserNotParticipant:
            results.append(f"ℹ️ @{uname} not in group")
        except Exception as e:
            results.append(f"❌ @{uname}: {type(e).__name__}")
    await update.message.reply_text("🦶 Kick Bot:\n" + "\n".join(results))


async def kickallbots_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /kickallbots — Kick ALL configured bots from this group.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text("❌ User account not connected.")
    chat_id  = update.effective_chat.id
    wait_msg = await update.message.reply_text("⏳ Kicking all bots…")
    results: List[str] = []
    for bot in all_bot_instances:
        try:
            me    = await bot.get_me()
            uname = me.username
            if not uname:
                continue
            await client.ban_chat_member(chat_id, uname)
            await asyncio.sleep(0.3)
            await client.unban_chat_member(chat_id, uname)
            results.append(f"✅ @{uname} kicked")
        except Exception as e:
            try:
                me = await bot.get_me()
                results.append(f"❌ @{me.username}: {type(e).__name__}")
            except Exception:
                results.append(f"❌ Bot: {type(e).__name__}")
    await wait_msg.edit_text(
        "🦶 Kick All Bots:\n" + ("\n".join(results) if results else "No results.")
    )


async def creategc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /creategc <group name>
    Creates a new Telegram group using your user account,
    invites all configured bots, and sends the invite link here.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text(
            "❌ User account not connected.\nSetup: fill API_ID/API_HASH in the file → /userlogin → /userotp"
        )
    gc_name = " ".join(context.args).strip() if context.args else ""
    if not gc_name:
        return await update.message.reply_text("Usage: /creategc <group name>")
    wait_msg = await update.message.reply_text(f"⏳ Creating group \"{gc_name}\"…")
    bot_usernames: List[str] = []
    for bot in all_bot_instances:
        try:
            me = await bot.get_me()
            if me.username:
                bot_usernames.append(me.username)
        except Exception:
            pass
    try:
        first_batch = bot_usernames[:1] if bot_usernames else []
        group = await client.create_group(gc_name, first_batch if first_batch else [])
        new_chat_id = group.id
        added: List[str] = []
        if first_batch:
            added.append(f"✅ @{first_batch[0]}")
        for uname in bot_usernames[1:]:
            try:
                await client.add_chat_members(new_chat_id, uname)
                added.append(f"✅ @{uname}")
                await asyncio.sleep(0.5)
            except UserAlreadyParticipant:
                added.append(f"ℹ️ @{uname} already in")
            except Exception as e:
                added.append(f"❌ @{uname}: {type(e).__name__}")
        try:
            link = await client.export_chat_invite_link(new_chat_id)
        except Exception:
            raw_id = str(new_chat_id).replace("-100", "")
            link = f"https://t.me/c/{raw_id}"
        bots_info = "\n".join(added) if added else "No bots added"
        reply = (
            f"🎉 Group Created!\n"
            f"📛 Name: **{gc_name}**\n"
            f"🔗 Link: {link}\n\n"
            f"🤖 Bots added:\n{bots_info}\n\n"
            f"💫 𝘣𝘺 ᎮᏒᎥᎷᏋ"
        )
        await wait_msg.edit_text(reply, parse_mode="Markdown")
    except Exception as e:
        await wait_msg.edit_text(f"❌ Failed to create group: {e}")


def _extract_base(raw: str, prefixes: tuple, context) -> str:
    for prefix in prefixes:
        if raw.lower().startswith(prefix.lower()):
            return raw[len(prefix):].strip()
    return " ".join(context.args) if context.args else ""


_SAAVN_MIRRORS = [
    "https://saavn.dev/api/search/songs?query={q}&page=1&limit=3",
    "https://saavn-api-privateciy.vercel.app/api/search/songs?query={q}&page=1&limit=3",
    "https://saavnapi-six.vercel.app/api/search/songs?query={q}&page=1&limit=3",
]

def _saavn_search_sync(query: str):
    q = urllib.parse.quote(query)
    headers = {"User-Agent": "Mozilla/5.0"}
    data = None
    last_err = None
    for mirror in _SAAVN_MIRRORS:
        try:
            url = mirror.format(q=q)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            break
        except Exception as e:
            last_err = e
            continue
    if data is None:
        raise Exception(f"All mirrors failed. Last error: {last_err}")
    results = data.get("data", {}).get("results", [])
    if not results:
        return None
    song = results[0]
    dl_list = song.get("downloadUrl") or []
    dl_url = None
    for quality in ("320kbps", "160kbps", "96kbps"):
        for entry in dl_list:
            if entry.get("quality") == quality:
                dl_url = entry.get("url")
                break
        if dl_url:
            break
    if not dl_url and dl_list:
        dl_url = dl_list[-1].get("url")
    if not dl_url:
        return None
    title = song.get("name", "Unknown")
    artists_raw = song.get("artists") or {}
    if isinstance(artists_raw, dict):
        primary = artists_raw.get("primary") or []
        artist = ", ".join(a.get("name", "") for a in primary) if primary else "Unknown"
    elif isinstance(artists_raw, str):
        artist = artists_raw
    else:
        artist = "Unknown"
    duration = int(song.get("duration") or 0)
    return {"title": title, "artist": artist, "duration": duration, "url": dl_url}


def _download_audio_sync(url: str) -> bytes:
    """Blocking download — run inside executor."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


async def song_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ~song <song name>  or  /song <song name>
    Searches JioSaavn, downloads the best quality MP3, and sends as audio.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if not _is_primary_bot(context):
        return

    raw = (update.message.text or "").strip()
    query = _extract_base(raw, ("~song", "💦song", "/song"), context)
    if not query:
        return await update.message.reply_text(
            "Usage: ~song <song name>\nExample: ~song Circle"
        )

    searching_msg = await update.message.reply_text(f"🔍 Searching: {query}…")
    loop = asyncio.get_running_loop()

    try:
        info = await loop.run_in_executor(None, _saavn_search_sync, query)
    except Exception as e:
        await searching_msg.edit_text(f"❌ Search failed: {e}")
        return

    if not info:
        await searching_msg.edit_text("❌ Song not found on JioSaavn. Try a different name.")
        return

    await searching_msg.edit_text(
        f"🎵 Found: *{info['title']}* — {info['artist']}\n⬇️ Downloading…",
        parse_mode="Markdown",
    )

    try:
        audio_bytes = await asyncio.wait_for(
            loop.run_in_executor(None, _download_audio_sync, info["url"]),
            timeout=45,
        )
    except asyncio.TimeoutError:
        await searching_msg.edit_text("❌ Download timed out. Try again.")
        return
    except Exception as e:
        await searching_msg.edit_text(f"❌ Download failed: {e}")
        return

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"{info['title'][:40]}.mp3"

    bot = all_bot_instances[0] if all_bot_instances else context.bot
    try:
        await bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=audio_file,
            title=info["title"],
            performer=info["artist"],
            caption=f"🎶 *{info['title']}*\n\n",
            duration=info["duration"] or None,
            parse_mode="Markdown",
          
            )
        await searching_msg.delete()
    except Exception as e:
        await searching_msg.edit_text(f"❌ Failed to send audio: {e}")






async def muted_user_autodelete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete all message types from /muteuser targets, except owner and sudo."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    if chat.type not in ("group", "supergroup"):
        return
    # Never delete owner/sudo messages, even if an old mute entry exists.
    if is_admin(user.id):
        return
    if user.id not in muted_users_by_chat.get(chat.id, set()):
        return
    try:
        await message.delete()
    except (BadRequest, Forbidden):
        # Telegram requires the bot to have delete_messages permission.
        pass
    except Exception:
        pass


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    known_chats.add(chat_id)
    uid = update.message.from_user.id
    msg = (update.message.text or "").strip()
    msg_lower = msg.lower()

    if chat_id in mute_chats and not is_admin(uid):
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if chat_id in autoreact_chats and update.message.message_id:
        style = autoreact_chats[chat_id]
        react_bots = [b for b in all_bot_instances if b is not None] or [context.bot]
        asyncio.create_task(_do_react(react_bots, chat_id, update.message.message_id, style))

    if msg_lower == "-pic" or msg_lower.startswith("-pic ") or msg_lower == "💦pic" or msg_lower.startswith("💦pic "):
        if is_admin(uid):
            await pic_cmd(update, context)
        return

    if msg_lower == "-stoppic" or msg_lower.startswith("-stoppic ") or msg_lower == "💦stoppic" or msg_lower.startswith("💦stoppic "):
        if is_admin(uid):
            await stop_pic(update, context)
        return

    if msg_lower.startswith("-admin") or msg_lower.startswith("💦admin"):
        if is_admin(uid):
            await admin_cmd(update, context)
        return

    if msg_lower.startswith("-upall") or msg_lower.startswith("💦upall"):
        if is_admin(uid):
            await upall(update, context)
        return






    if msg_lower.startswith("-ncrose") or msg_lower.startswith("💦ncrose"):
        if is_admin(uid):
            await ncrose_handler(update, context)
        return


    if msg_lower.startswith("-ncmoon") or msg_lower.startswith("💦ncmoon"):
        if is_admin(uid):
            await ncmoon_handler(update, context)
        return

    if msg_lower.startswith("-nccry") or msg_lower.startswith("💦nccry") or msg_lower.startswith("+crync") or msg_lower.startswith("💦crync"):
        if is_admin(uid):
            await crync_handler(update, context)
        return

    if msg_lower.startswith("-prime") or msg_lower.startswith("💦ncprime"):
        if is_admin(uid):
            await ncprime_handler(update, context)
        return



    if msg_lower.startswith("-ncultra") or msg_lower.startswith("💦ncultra"):
        if is_admin(uid):
            await ncultra_handler(update, context)
        return

    if msg_lower.startswith("-ncflower")  or msg_lower.startswith("💦ncflower"):
        if is_admin(uid): await ncflower_handler(update, context)
        return
    if msg_lower.startswith("-ncflood")  or msg_lower.startswith("💦ncflood"):
        if is_admin(uid): await ncflood_handler(update, context)
        return
    if msg_lower.startswith("+prime1")  or msg_lower.startswith("💦prime1"):
        if is_admin(uid): await prime1_handler(update, context)
        return
    if msg_lower.startswith("+prime2")  or msg_lower.startswith("💦prime2"):
        if is_admin(uid): await prime2_handler(update, context)
        return
    if msg_lower.startswith("+prime3")  or msg_lower.startswith("💦prime3"):
        if is_admin(uid): await prime3_handler(update, context)
        return
    if msg_lower.startswith("+prime8")  or msg_lower.startswith("💦prime8"):
        return
    if msg_lower.startswith("+aiimg") or msg_lower.startswith("💦aiimg"):
        if is_admin(uid):
            await aiimg_cmd(update, context)
        return

    if msg_lower.startswith("-ncemo") or msg_lower.startswith("💦ncemo"):
        if is_admin(uid):
            await ncemo_handler(update, context)
        return

    if msg_lower.startswith("-ncflag") or msg_lower.startswith("💦ncflag"):
        if is_admin(uid):
            await ncflag_handler(update, context)
        return

    if msg_lower == "/stopnc" or msg_lower == "stopnc":
        if is_admin(uid):
            await stop_nc_cmd(update, context)
        return

    if msg_lower.startswith("-autoreact") or msg_lower.startswith("💦autoreact"):
        if is_admin(uid):
            await autoreact_cmd(update, context)
        return

    if msg_lower.startswith("-react") or msg_lower.startswith("💦react"):
        if is_admin(uid):
            await react_cmd(update, context)
        return

    if msg_lower.startswith("~song") or msg_lower.startswith("💦song"):
        if is_admin(uid):
            await song_cmd(update, context)
        return

    if msg_lower.startswith("-slidereply") or msg_lower.startswith("💦slidereply"):
        if is_admin(uid):
            await slidereply_cmd(update, context)
        return

    if msg_lower.startswith("-slide") and not msg_lower.startswith("-slidereply"):
        if is_admin(uid):
            await plus_slide(update, context)
        return

    if msg_lower.startswith("-spam") or msg_lower.startswith("💦spam"):
        if is_admin(uid):
            await spam_cmd(update, context)
        return

    if msg_lower.startswith("-autoreply") or msg_lower.startswith("💦autoreply"):
        if is_admin(uid):
            await autoreply_cmd(update, context)
        return

    if msg_lower.startswith("-targetreply") or msg_lower.startswith("💦targetreply"):
        if is_admin(uid):
            await targetreply_cmd(update, context)
        return

    if chat_id in autoreply_chats and not is_admin(uid):
        reply_text = autoreply_chats[chat_id]
        bot = all_bot_instances[0] if all_bot_instances else context.bot
        async def _do_autoreply():
            try:
                await bot.send_message(
                    chat_id,
                    reply_text,
                    reply_to_message_id=update.message.message_id,
                )
            except Exception:
                pass
        asyncio.create_task(_do_autoreply())

    tr = targetreply_chats.get(chat_id)
    if tr and uid == tr["uid"] and not is_admin(uid):
        reply_text = tr["text"]
        bot = all_bot_instances[0] if all_bot_instances else context.bot
        async def _do_targetreply():
            try:
                await bot.send_message(
                    chat_id,
                    reply_text,
                    reply_to_message_id=update.message.message_id,
                )
            except Exception:
                pass
        asyncio.create_task(_do_targetreply())

    target_uid = slide_reply_targets.get(chat_id)
    if target_uid and uid == target_uid and not is_admin(uid):
        bots = [b for b in all_bot_instances if b is not None] or [context.bot]
        mid = update.message.message_id
        async def _bot_burst(bot):
            await _slide_reply_burst(bot, chat_id, mid, count=5)
        asyncio.create_task(
            asyncio.gather(*[_bot_burst(b) for b in bots], return_exceptions=True)
        )


async def title_change_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fires on every NEW_CHAT_TITLE service message.

    1. ncdel ON → delete the service message (makes enemy NC invisible).

    Both can be active simultaneously.
    Only primary bot acts to avoid duplicate actions.
    """
    if not _is_primary_bot(context):
        return
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    changer = update.message.from_user

    if chat_id in ncdel_chats:
        changer_id = changer.id if changer else 0
        our_bot_ids = {getattr(b, "id", 0) for b in all_bot_instances if b}
        if changer_id not in our_bot_ids and not is_admin(changer_id):
            try:
                await update.message.delete()
            except Exception:
                pass

    # Title changes are handled here only for optional service-message cleanup.


# ────────────────────────────────────────────────────────────
# OVER / OVERPFP
# ────────────────────────────────────────────────────────────
_OVER_PFP_PATH = None
_OVER_PFP_SAVED = False

async def _cmd_opfp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a replied photo as the OVER PFP."""
    global _OVER_PFP_SAVED, _OVER_PFP_PATH

    msg = update.message
    if not msg:
        return

    if not is_admin(update.effective_user.id if update.effective_user else 0):
        return

    if not msg.reply_to_message or not msg.reply_to_message.photo:
        return await msg.reply_text("❌ Reply to a photo with /overpfp to save it")

    try:
        photo = msg.reply_to_message.photo[-1]
        _OVER_PFP_PATH = photo.file_id
        _OVER_PFP_SAVED = True
        await msg.reply_text("✅ **𝙊𝙑𝙀𝙍 𝙋𝙁𝙋**", parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Error: {str(e)[:100]}")


async def _cmd_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the GAME OVER message with the saved photo."""
    global _OVER_PFP_SAVED, _OVER_PFP_PATH

    msg = update.message
    if not msg:
        return

    if not is_admin(update.effective_user.id if update.effective_user else 0):
        return

    if not _is_primary_bot(context):
        return

    cid = update.effective_chat.id

    if not _OVER_PFP_SAVED or not _OVER_PFP_PATH:
        return await msg.reply_text("❌ No Over PFP saved. Use /overpfp first")

    target_name = " ".join(context.args or []).strip() or "Unknown Target"

    try:
        from datetime import datetime, timezone, timedelta
        ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        time_str = ist.strftime("%H:%M:%S")
        date_str = ist.strftime("%d-%m-%Y")

        game_over_msg = f"""━━━━━━━━━━━━━━━━━━━
 𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔 💫
━━━━━━━━━━━━━━━━━━━
⏰ 𝙏𝙄𝙈𝙀   :: {time_str}
📅 𝗗𝗔𝗧𝗘   :: {date_str}
{target_name} - 𝑭𝒖𝑪𝑲𝒆𝑫 𝑩𝒚 𝐏ʀ𝐈ᴍ𝐄 𝐀ʙʙ𝐔 ꨄ︎
━━━━━━━━━━━━━━━━━━━
{target_name} 𓂃✍︎ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ 𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎
━━━━━━━━━━━━━━━━━━━
"""

        # /over is handled and sent by the MAIN BOT only.
        await context.bot.send_photo(
            chat_id=cid,
            photo=_OVER_PFP_PATH,
            caption=game_over_msg,
        )


    except Exception as e:
        await msg.reply_text(f"❌ Error: {str(e)[:100]}")


async def promoteallbots_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /promoteallbots — Promote ALL configured bots as full admins.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message or not _is_primary_bot(context):
        return
    client = await _get_pyro()
    if not client:
        return await update.message.reply_text("❌ User account not connected.")
    chat_id  = update.effective_chat.id
    wait_msg = await update.message.reply_text("⏳ 𝙋𝙍𝙊𝙈𝙊𝙏𝙄𝙉𝙂 𝘼𝙇𝙇 𝘽𝙊𝙏𝙎…")
    _full_admin = ChatPrivileges(
        can_manage_chat=True,
        can_change_info=True,
        can_delete_messages=True,
        can_invite_users=True,
        can_restrict_members=True,
        can_pin_messages=True,
        can_promote_members=True,
        can_manage_video_chats=True,
        is_anonymous=False,
    )
    results: List[str] = []
    for bot in all_bot_instances:
        try:
            me    = await bot.get_me()
            uname = me.username
            if not uname:
                continue
            await client.promote_chat_member(chat_id, uname, privileges=_full_admin)
            results.append(f"✅ @{uname}")
            await asyncio.sleep(0.3)
        except Exception as e:
            try:
                me = await bot.get_me()
                results.append(f"❌ @{me.username}: {type(e).__name__}")
            except Exception:
                results.append(f"❌ Bot: {type(e).__name__}")
    await wait_msg.edit_text(
        "👑 Promote All Bots:\n" + ("\n".join(results) if results else "No results.")
    )



async def lock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restrict regular members from sending messages in the current group."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return await update.message.reply_text("❌ This command works only in groups.")

    permissions = ChatPermissions(can_send_messages=False)
    try:
        await context.bot.set_chat_permissions(
            chat_id=update.effective_chat.id,
            permissions=permissions,
        )
        await update.message.reply_text("🔒 𝘾𝙃𝘼𝙏 𝙇𝙊𝘾𝙆𝙀𝘿")
    except Exception as e:
        await update.message.reply_text(f"❌ Lock failed: {type(e).__name__}")


async def unlock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow regular members to send messages in the current group."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.effective_chat or not update.message:
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return await update.message.reply_text("❌ This command works only in groups.")

    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
    )
    try:
        await context.bot.set_chat_permissions(
            chat_id=update.effective_chat.id,
            permissions=permissions,
        )
        await update.message.reply_text("🔓 𝘾𝙃𝘼𝙏 𝙐𝙉𝙇𝙊𝘾𝙆𝙀𝘿.")
    except Exception as e:
        await update.message.reply_text(f"❌ Unlock failed: {type(e).__name__}")


async def refresh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh the current bot's polling connection."""
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        return

    bot_id = getattr(context.bot, "id", "unknown")
    try:
        _flood_tracker.clear(bot_id)
    except Exception:
        pass

    try:
        await update.message.reply_text(
            f"🔄 𝘽𝙊𝙏 𝙍𝙀𝙁𝙍𝙀𝙎𝙃𝙀𝘿 ⚡", parse_mode="Markdown"
        )
    except Exception:
        pass

    # Do not stop/restart the Updater from inside its own command handler.
    # This handler runs on the polling event loop; stopping and starting polling
    # here can raise lifecycle errors (for example, updater already running or
    # application not running) and can interrupt update processing. Refresh the
    # bot's local flood-tracking state and leave polling alive.
    logger.info("Refresh command handled for bot %s; polling remains active.", bot_id)


def _register_handlers(app):
    cmds = {
        "ping":               ping_cmd,
"menu":               menu_cmd,
         "xprime1":            menu1_cmd,
         "xprime2":            menu2_cmd,
         "xprime3":            menu3_cmd,
         "xprime4":            menu4_cmd,
                 "lock":        lock_cmd,
        "unlock":      unlock_cmd,
        "xprime":      start_cmd,
        "help":        help_cmd,
        "stop":        stop_cmd,
        "sudo":     sudo_cmd,
        "delsudo":  delsudo_cmd,
        "sudolist":    sudolist_cmd,
        "bots":        bots_info_cmd,
        "leave":       leave_cmd,
        "mutegc":      mute_cmd,
        "unmutegc":    unmute_cmd,
        "ncdel":       ncdel_cmd,
        "stopnc":      stopnc_cmd,
        "gclist":      gclist_cmd,
        "restrict":        restrict_cmd,
        "unrestrict":      unrestrict_cmd,
        "stopreact":       stopreact_cmd,
        "menupic":    menupic_cmd,
        "menuvid":    menuvid_cmd,
        "menuclear":       menuclear_cmd,
        "slidereply":         slidereply_cmd,
        "stopslidereply":      stopslidereply_cmd,
        "slide":              plus_slide,
        "spam":               spam_cmd,
        "stopspam":           stopspam_cmd,
        "autoreply":          autoreply_cmd,
        "stopautoreply":       stopautoreply_cmd,
        "targetreply":        targetreply_cmd,
        "stoptargetreply":     stoptargetreply_cmd,
        "react":        react_cmd,
        "song":               song_cmd,
        "uptime":           uptime_cmd,
        "restartbot":       restartbot_cmd,
        "setdelay":          set_delay_cmd,
        "floodbypass":        floodbypass_cmd,
        "userlogin":          userlogin_cmd,
        "userotp":            userotp_cmd,
        "user2fa":            user2fa_cmd,
        "userlogout":         userlogout_cmd,
        "userstatus":         userstatus_cmd,
        "addbot":             addbot_cmd,
        "addallbots":         addallbots_cmd,
        "promotebot":         promotebot_cmd,
        "admin":             admin_cmd,
        "upall":             upall,
        "pic":               pic_cmd,
        "stoppic":           stop_pic,
        "muteuser":           muteuser_cmd,
        "unmuteuser":         unmuteuser_cmd,
        "ban":                ban_cmd,
        "unban":              unban_cmd,
        "kick":               kick_cmd,
        "kickbot":            kickbot_cmd,
        "kickallbots":        kickallbots_cmd,
        "creategc":           creategc_cmd,
        "ncemo":      ncemo_handler,
        "ncflag":       ncflag_handler,
        "ncrose":    ncrose_handler,
        "ncmoon":       ncmoon_handler,
        "crync":       crync_handler,
        "aiimg":       aiimg_cmd,
        "ncprime":     ncprime_handler,
        "ncultra":     ncultra_handler,
        "ncflower":     ncflower_handler,
        "ncflood":     ncflood_handler,
        "prime1":     prime1_handler,
        "prime2":     prime2_handler,
        "prime3":     prime3_handler,
        "promoteallbots": promoteallbots_cmd,
        "overpfp":       _cmd_opfp,
        "over":          _cmd_over,
    }
    # Media commands are scoped to their corresponding menu page:
    # /menuvid and /menupic -> /xprime (master menu, slot 0)
    # /menuvid1 and /menupic1 -> /xprime1, ... through page 4.
    for menu_key in range(1, 5):
        cmds[f"menupic{menu_key}"] = _make_menu_media_cmd(str(menu_key), "photo")
        cmds[f"menuvid{menu_key}"] = _make_menu_media_cmd(str(menu_key), "video")

    # This function is called only for the main bot. Worker bots are API-only
    # clients and do not register handlers or poll for updates.
    app.add_handler(CommandHandler("refresh", _dedup(refresh_cmd)))

    for cmd, h in cmds.items():
        if callable(h):
            app.add_handler(CommandHandler(cmd, _dedup(h)))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_TITLE,
        title_change_handler
    ))

    app.add_handler(MessageHandler(
        filters.ALL,
        muted_user_autodelete_handler,
    ), group=-1)

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        _dedup(message_handler)
    ))


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply from every configured bot with that bot's own Telegram round-trip ping."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return

    bot = context.bot
    bot_name = f"Bot {getattr(bot, 'id', 'Unknown')}"

    try:
        t0 = time.perf_counter()
        msg = await update.message.reply_text(f" 𝐏ɪ𝐧𝐠ɪ𝐧𝐠..")
        t1 = time.perf_counter()
        ms = round((t1 - t0) * 1000)

        try:
            await msg.edit_text(
                f" 𝐏ɪ𝐧𝐠!  𝐋𝐚𝐭𝐞𝐧𝐜𝐲 → `{ms} ms`",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    except RetryAfter as e:
        try:
            await update.message.reply_text(
                f" {bot_name} ⏳ 𝐅ʟᴏᴏᴅ → {e.retry_after}s"
            )
        except Exception:
            pass
    except Exception as e:
        try:
            await update.message.reply_text(
                f" {bot_name} ❌ 𝐏ɪɴɢ 𝐄ʀʀ → `{str(e)[:40]}`",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def run_bots():
    """Start all configured Telegram bots with isolated HTTP clients.

    Important compatibility note:
    The Telegram networking stack used by python-telegram-bot is sensitive to
    mismatched Python/httpx/httpcore versions. The screenshot that motivated
    this fix shows Python 3.15. Use Python 3.13 (recommended) or 3.14 with a
    current python-telegram-bot release and its supported httpx dependency.
    """
    global all_bot_instances, all_apps

    if sys.version_info >= (3, 15):
        logger.warning(
            "Python %s.%s detected. For stable python-telegram-bot networking, "
            "use Python 3.13 or 3.14. Python 3.15 may cause HTTPX/HTTP-core "
            "compatibility errors such as 'sentinel is not defined'.",
            sys.version_info.major,
            sys.version_info.minor,
        )

    base_tokens = get_base_tokens()
    all_tokens = base_tokens + [t for t in extra_tokens if t not in base_tokens]
    all_tokens = [t.strip() for t in all_tokens if isinstance(t, str) and t.strip()]

    # Keep hosting logs limited to the bot usernames below.

    # Each Application gets its own HTTPXRequest. Sharing one request object
    # between multiple Applications can cause lifecycle/connection problems.
    def make_request():
        from telegram.request import HTTPXRequest
        return HTTPXRequest(
            connection_pool_size=16,
            read_timeout=45,
            write_timeout=45,
            connect_timeout=30,
            pool_timeout=15,
        )

    apps = []
    all_apps.clear()
    all_bot_instances.clear()

    for index, token in enumerate(all_tokens, 1):
        if not token or "YOUR_BOT" in token:
            continue

        app = None
        try:
            req_cfg = make_request()
            app = Application.builder().token(token).request(req_cfg).build()
            await app.initialize()
            me = await app.bot.get_me()

            # Only the first successfully initialized bot is the MAIN BOT.
            # Register command/message handlers and start polling on that bot
            # only. Remaining bot clients are kept as API workers for group
            # actions, so they cannot reply to commands or duplicate actions.
            is_main_bot = not all_bot_instances
            if is_main_bot:
                _register_handlers(app)

            await app.start()
            apps.append(app)
            all_apps.append(app)
            all_bot_instances.append(app.bot)

            if is_main_bot and app.updater is not None:
                await app.updater.start_polling(drop_pending_updates=True)
                print(f"✅ MAIN BOT: @{me.username or me.id}")
            else:
                print(f"✅ Worker bot {index}/{len(all_tokens)}: @{me.username or me.id} ")

        except (TimedOut, NetworkError) as e:
            logger.error(
                "❌ Bot %s/%s network startup failed: %s",
                index, len(all_tokens), e,
            )
            if app is not None:
                try:
                    if app.updater is not None:
                        await app.updater.stop()
                except Exception:
                    pass
                try:
                    await app.stop()
                except Exception:
                    pass
                try:
                    await app.shutdown()
                except Exception:
                    pass
            continue

        except Exception:
            logger.exception(
                "❌ Bot %s/%s failed during startup; continuing with remaining bots.",
                index, len(all_tokens),
            )
            if app is not None:
                try:
                    if app.updater is not None:
                        await app.updater.stop()
                except Exception:
                    pass
                try:
                    await app.stop()
                except Exception:
                    pass
                try:
                    await app.shutdown()
                except Exception:
                    pass
            continue

    if not all_bot_instances:
        raise RuntimeError(
            "No Telegram bot started successfully. "
            "This usually means the installed python-telegram-bot/httpx versions "
            "do not match requirements.txt. Reinstall the pinned dependencies "
            "and run with Python 3.13."
        )

    # Bot usernames already identify the successfully started bots.

    try:
        await _connect_pyro_from_saved()
    except Exception:
        logger.exception("Saved Pyrogram session could not be connected; bot polling will continue.")

    try:
        await asyncio.Event().wait()
    finally:
        for app in list(apps):
            try:
                if app.updater is not None:
                    await app.updater.stop()
            except Exception:
                pass
            try:
                await app.stop()
            except Exception:
                pass
            try:
                await app.shutdown()
            except Exception:
                pass


async def _host_main():
    """Keep the process alive and restart after recoverable runtime failures."""
    restart_delay = 5
    while True:
        try:
            await run_bots()
            logger.warning(
                "run_bots() exited unexpectedly; restarting in %ss...",
                restart_delay,
            )
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception(
                "Bot runtime error; restarting in %ss...",
                restart_delay,
            )

        await asyncio.sleep(restart_delay)
        # Gradually back off repeated failures, but never wait more than 60s.
        restart_delay = min(restart_delay * 2, 60)


def _print_runtime_diagnostics():
    """Print useful dependency/version information without exposing bot tokens."""
    try:
        import telegram
        import httpx
        print(
            f"🐍 Python: {sys.version.split()[0]} | "
            f"python-telegram-bot: {getattr(telegram, '__version__', 'unknown')} | "
            f"httpx: {getattr(httpx, '__version__', 'unknown')}"
        )
    except Exception as exc:
        logger.warning("Could not read Telegram/httpx versions: %s", exc)

    if sys.version_info >= (3, 15):
        logger.warning(
            "⚠️ Python %s.%s detected. Use Python 3.13 for the most stable "
            "complete setup, especially because this file optionally uses Pyrogram.",
            sys.version_info.major,
            sys.version_info.minor,
        )


if __name__ == "__main__":
    _print_runtime_diagnostics()
    if os.environ.get("ENABLE_HEALTH_SERVER", "0").strip().lower() in {"1", "true", "yes", "on"}:
        threading.Thread(target=run_health_check_server, daemon=True).start()
    try:
        asyncio.run(_host_main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")