# --- MOVE ALL IMPORTS TO TOP ---
import asyncio
import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask, render_template, request, redirect, url_for, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId


# --- Place after bot is defined ---
import os
import threading
import datetime
import subprocess
import shutil


TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID")) if os.getenv("LOG_CHANNEL_ID") else None
TIER_LOG_CHANNEL_ID = 1502966105940164638
QUEUE_CHANNEL_ID = 1507057131436642334
STATUS_CHANNEL_ID = 1497989003721310249
TESTER_NOTIF_CHANNEL_ID = 1507062245366956134
CLAIM_CHANNEL_ID = 1504206348324311131
PARTNER_CHANNEL_ID = 1502975682513473787
PARTNER_CATEGORY_ID = 1498359340065624165
VERIFY_CHANNEL_ID = 1502966365466656948
VERIFY_IGN_CHANNEL_ID = 1507804249554292826
MEMBER_ROLE_ID = int(os.getenv("MEMBER_ROLE_ID")) if os.getenv("MEMBER_ROLE_ID") else None
UNVERIFIED_ROLE_ID = int(os.getenv("UNVERIFIED_ROLE_ID")) if os.getenv("UNVERIFIED_ROLE_ID") else None
MEMBER_ROLE_NAME = os.getenv("MEMBER_ROLE_NAME", "Member")
UNVERIFIED_ROLE_NAME = os.getenv("UNVERIFIED_ROLE_NAME", "Unverified")

# --- TESTER ROLE IDS ---
TRAINEE_ROLE_ID = 1499375993167675392
TESTER_ROLE_ID = 1497964651806326936
HIGH_TESTER_ROLE_ID = 1508407033559519304

# --- REGION ROLE IDS ---
REGION_ROLE_IDS = {
    "EU": 1499373016445096096,
    "NA": 1499373055934206033,
    "AF": 1499117778207248535,
    "AS": 1507060208927772692,
    "OC": 1499373068504666183,
}

# --- GAMEMODE ROLE IDS ---
GAMEMODE_ROLE_IDS = {
    "Sword": 1507060831093788823,
    "Axe": 1507060845790888016,
    "Crystal": 1507060847980187775,
    "Pot": 1507060885238190111,
    "UHC": 1507060966137921637,
    "SMP": 1507061382195974366,
    "Mace": 1507060902753734827,
}

# --- QUEUE CHANNELS PER REGION (fill in actual IDs) ---
REGION_QUEUE_CHANNELS = {
    "EU": 1507809038392496288,
    "NA": 1507809068742611105,
    "AF": 1507809079316320417,
    "AS": 1507809090292678728,
    "OC": 1507809110392045680,
}

REGION_TICKET_CATEGORIES = {
    "EU": 1507809548923306004,
    "NA": 1507809586017734846,
    "AS": 1507809700744270066,
    "OC": 1507809606007652672,
}

# --- GAMEMODE QUEUE CHANNELS (entry point embeds) ---
GAMEMODE_QUEUE_CHANNELS = {
    "Sword": 1507059703920722081,
    "Axe": 1507059730936234066,
    "Crystal": 1507062550767079516,
    "Pot": 1507059818597453995,
    "UHC": 1507062607641575588,
    "SMP": 1507062672473063595,
    "Mace": 1507064079683158168,
}

class TierlistQueue:
    def __init__(self, maxQueue=20, maxTesters=5, cooldown=1440):
        self.regions = {}
        self.gamemodes = {}
        self.maxQueue = maxQueue
        self.maxTesters = maxTesters
        self.cooldown = cooldown

    def setup(self):
        for rcode in REGION_ROLE_IDS:
            self.regions[rcode] = {
                "queue": [],
                "testers": [],
                "open": False,
                "queue_channel_id": REGION_QUEUE_CHANNELS.get(rcode),
                "queue_message_id": None,
                "ticket_category_id": REGION_TICKET_CATEGORIES.get(rcode),
                "ping_role_id": REGION_ROLE_IDS[rcode],
            }
        for gm in GAMEMODE_QUEUE_CHANNELS:
            self.gamemodes[gm] = {
                "channel_id": GAMEMODE_QUEUE_CHANNELS[gm],
                "message_id": None,
                "was_open": False,
                "closed_at": None,
            }

    def add_user(self, region, user_id, ign="Unknown", gamemode=None):
        r = self.regions.get(region)
        if not r:
            return "Region not found"
        for entry in r["queue"]:
            if entry["user_id"] == user_id:
                return "You are already in the queue"
        if len(r["queue"]) >= self.maxQueue:
            return "The queue is full!"
        r["queue"].append({"user_id": user_id, "ign": ign, "gamemode": gamemode})
        return "You have been added to the queue"

    def remove_user(self, region, user_id):
        r = self.regions.get(region)
        if not r:
            return "Region not found"
        for i, entry in enumerate(r["queue"]):
            if entry["user_id"] == user_id:
                r["queue"].pop(i)
                return "You have left the queue"
        return "You are not in the queue"

    def add_tester(self, region, user_id):
        r = self.regions.get(region)
        if not r:
            return "Region not found"
        if not r["open"]:
            r["open"] = True
        if user_id in r["testers"]:
            return "You are already testing this region"
        if len(r["testers"]) >= self.maxTesters:
            return "Max testers reached for this region"
        r["testers"].append(user_id)
        return "You have opened the queue"

    def remove_tester(self, region, user_id):
        r = self.regions.get(region)
        if not r or not r["open"]:
            return "Queue is not open"
        if user_id not in r["testers"]:
            return "You are not testing this region"
        r["testers"].remove(user_id)
        if not r["testers"]:
            r["open"] = False
            r["queue"] = []
            return "Testing is closed"
        return "You have stopped testing"

    def next_user(self, region):
        r = self.regions.get(region)
        if not r or not r["queue"]:
            return None
        return r["queue"].pop(0)

    def next_for_tester(self, region, gamemodes):
        r = self.regions.get(region)
        if not r or not r["queue"]:
            return None
        for i, entry in enumerate(r["queue"]):
            if not entry["gamemode"] or entry["gamemode"] in gamemodes:
                return r["queue"].pop(i)
        return None

    def addQueueMessageId(self, region, message_id):
        r = self.regions.get(region)
        if r:
            r["queue_message_id"] = message_id

    def getqueueraw(self):
        return self.regions

    def make_region_embed(self, region):
        r = self.regions.get(region)
        if not r or not r["open"]:
            embed = discord.Embed(title=f"{region} Queue", description="Queue is closed.", color=0x525768)
            return embed
        capacity = f"{len(r['queue'])}/{self.maxQueue}"
        tester_capacity = f"{len(r['testers'])}/{self.maxTesters}"
        queue_lines = [f"{i+1}. <@{e['user_id']}> ({e['ign']})" + (f" [{e['gamemode']}]" if e['gamemode'] else "") for i, e in enumerate(r["queue"])]
        tester_lines = [f"{i+1}. <@{uid}>" for i, uid in enumerate(r["testers"])]
        embed = discord.Embed(title=f"{region} Queue", color=0xff4500)
        embed.add_field(name=f"In Queue ({capacity})", value="\n".join(queue_lines) or "None", inline=True)
        embed.add_field(name=f"Testers ({tester_capacity})", value="\n".join(tester_lines) or "None", inline=True)
        embed.set_footer(text=f"{len(r['queue'])} waiting · {len(r['testers'])} testing")
        return embed

    def make_gamemode_embed(self, gamemode):
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M:%S %p").lstrip("0").lower()
        gdata = self.gamemodes.get(gamemode)

        queue_entries = []
        tester_entries = []
        open_regions = []
        for rcode, rdata in self.regions.items():
            has_tester = any(
                db_mgr.tester_profiles.find_one({"discord_id": uid, "online": True, "gamemodes": gamemode})
                for uid in rdata["testers"]
            )
            if has_tester:
                open_regions.append(rcode)
            for e in rdata["queue"]:
                if not e["gamemode"] or e["gamemode"] == gamemode:
                    queue_entries.append(e)
            for uid in rdata["testers"]:
                tdoc = db_mgr.tester_profiles.find_one({"discord_id": uid, "online": True})
                if tdoc and gamemode in tdoc.get("gamemodes", []):
                    tester_entries.append(uid)

        regions_str = ", ".join(open_regions) if open_regions else "None"

        if not open_regions:
            closed_at = gdata.get("closed_at") if gdata else None
            if closed_at:
                closed_local = closed_at.replace(tzinfo=datetime.timezone.utc).astimezone()
                ended_str = closed_local.strftime("%d %b %Y at %I:%M %p")
            else:
                ended_str = time_str
            embed = discord.Embed(
                title=f"\U0001f512 {gamemode} Queue Closed",
                description="This testing session has ended. You will be notified here when a new queue opens.",
                color=0xed4245,
            )
            embed.add_field(name="📋 Reason", value="Queue manually ended by command", inline=False)
            embed.add_field(name="⏰ Session Ended", value=ended_str, inline=False)
            embed.set_footer(text="Thank you for testing!")
            return embed

        queue_lines = [f"<@{e['user_id']}>" for e in queue_entries[:15]]
        if len(queue_entries) > 15:
            queue_lines.append(f"+{len(queue_entries) - 15} more")
        queue_val = "\n".join(queue_lines) if queue_lines else "None"

        tester_lines = [f"<@{uid}>" for uid in tester_entries[:15]]
        tester_val = "\n".join(tester_lines) if tester_lines else "None"

        embed = discord.Embed(
            description=f"✅ **{gamemode} Tester Available!**\nThe queue is now open and updates in real-time.",
            color=0x5865F2,
        )
        embed.add_field(name="📋 Queue", value=queue_val, inline=False)
        embed.add_field(name="🎮 Active Testers", value=tester_val, inline=False)
        embed.set_footer(text=f"🌍 Region: {regions_str} | ⏱️ Last Refresh: {time_str}")
        return embed

    def has_testers_for_gamemode(self, gamemode):
        for rdata in self.regions.values():
            for uid in rdata["testers"]:
                tdoc = db_mgr.tester_profiles.find_one({"discord_id": uid, "online": True})
                if tdoc and gamemode in tdoc.get("gamemodes", []):
                    return True
        return False

    def is_gamemode_open(self, gamemode):
        return self.has_testers_for_gamemode(gamemode)

    def format_no_queue(self):
        embed = discord.Embed(title="Queue Closed", description="No testers are currently open.", color=0x525768)
        return embed

tier_queue = TierlistQueue()

# --- GAMEMODE/REGION CHANNEL IDS (example, fill in actual IDs as needed) ---
GAMEMODE_REGION_CHANNEL_IDS = {
    ("Sword", "EU"): 1507059703920722081,  # e.g. 123456789012345678
    ("Sword", "NA"): 1507059703920722081,
    ("Sword", "AS"): 1507059703920722081,
    ("Sword", "AF"): 1507059703920722081,
    ("Sword", "OC"): 1507059703920722081,
    ("Axe", "EU"): 1507059703920722081,
    ("Axe", "NA"): 1507059703920722081,
    ("Axe", "AS"): 1507059703920722081,
    ("Axe", "AF"): 1507059703920722081,
    ("Crystal", "EU"): 1507059703920722081,
    ("Crystal", "NA"): 1507059703920722081,
    # ADD ASIA AFRICA OCEANIA CHANNELS AND OTHER GAMEMODES AS NEEDED
    ("Mace", "EU"): 1507059703920722081,
    ("Mace", "NA"): 1507059703920722081,
    ("Mace", "AS"): 1507059703920722081,
    ("Mace", "AF"): 1507059703920722081,
    ("Mace", "OC"): 1507059703920722081,

    # Add all combos as needed
}


MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

REGION_COLORS = {
    "NA": "#ff4d4d", "EU": "#4d94ff", "AS": "#ffdb4d",
    "SA": "#4dff88", "OC": "#ff4dff", "AF": "#ffa64d"
}
RANK_COLORS = {
    "Grandmaster": "#ff0000", "Legend": "#ff8c00",
    "Master": "#9370db", "Elite": "#00ced1",
    "Bronze": "#cd7f32", "Stone": "#a9a9a9"
}

GAMEMODE_ICON_URLS = {
    "Crystal": "https://imgur.com/g9GZWN4.png",
    "UHC": "https://imgur.com/Bhr49wo.png",
    "Pot": "https://imgur.com/HSR3a7Z.png",
    "SMP": "https://imgur.com/tu6NG54.png",
    "Axe": "https://imgur.com/tj9EPtk.png",
    "Sword": "https://imgur.com/Wf9dcUa.png",
    "Mace": "https://imgur.com/W4qul51.png",
    "Cart": "https://img.icons8.com/ios-filled/64/ffffff/minecart.png",
    "1.8": "https://img.icons8.com/ios-filled/64/ffffff/shield.png",
    "Trident": "https://img.icons8.com/ios-filled/64/ffffff/trident.png",
    "Spear": "https://img.icons8.com/ios-filled/64/ffffff/spear.png"
}
DEFAULT_GAMEMODE_ICON_URL = "https://img.icons8.com/ios-filled/64/ffffff/question-mark.png"

# --- DATABASE ---
class DummyCollection:
    def find(self, *args, **kwargs): return []
    def find_one(self, *args, **kwargs): return None
    def insert_one(self, *args, **kwargs): return type('obj', (object,), {'inserted_id': None})
    def insert_many(self, *args, **kwargs): return type('obj', (object,), {'inserted_ids': []})
    def update_one(self, *args, **kwargs): return None
    def update_many(self, *args, **kwargs): return type('obj', (object,), {'modified_count': 0})
    def distinct(self, *args, **kwargs): return []

class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri) if uri else None
        self.db = self.client['magmatiers_db'] if self.client else None
        if self.db is not None:
            self.players = self.db['players']
            self.settings = self.db['settings']
            self.reports = self.db['reports']
            self.console_messages = self.db['console_messages']
            self.queues = self.db['queues']
            self.tester_profiles = self.db['tester_profiles']
            self.partners = self.db['partners']
            self.link_codes = self.db['link_codes']
            self.alt_logs = self.db['alt_logs']
        else:
            self.players = DummyCollection()
            self.settings = DummyCollection()
            self.reports = DummyCollection()
            self.console_messages = DummyCollection()
            self.queues = DummyCollection()
            self.tester_profiles = DummyCollection()
            self.partners = DummyCollection()
            self.link_codes = DummyCollection()
            self.alt_logs = DummyCollection()

db_mgr = DatabaseManager(MONGO_URI)

# --- CONSOLE LOG BUFFER ---
console_logs = []
console_logs_lock = threading.Lock()

def push_console_log(ts, action, details, runner=""):
    with console_logs_lock:
        console_logs.append({
            "ts": ts,
            "action": action,
            "details": details,
            "runner": runner,
        })
        if len(console_logs) > 200:
            console_logs[:] = console_logs[-200:]

# --- CORE LOGIC ---
def normalize_tier(tier_name):
    if not tier_name: return ""
    return str(tier_name).upper().strip()

def normalize_mode(mode_name):
    if not mode_name: return ""
    mode_name = str(mode_name).strip()
    for mode in MODES:
        if mode.lower() == mode_name.lower():
            return mode
    return mode_name

def get_tier_value(tier_name):
    try:
        return TIER_ORDER.index(normalize_tier(tier_name)) + 1
    except ValueError:
        return 0

def get_rank_info(tier_list):
    if not tier_list: return "Stone", RANK_COLORS["Stone"]
    score = sum(get_tier_value(t) for t in tier_list)
    highest = max([get_tier_value(t) for t in tier_list]) if tier_list else 0
    if highest >= 9 and len(tier_list) >= 3: name = "Grandmaster"
    elif score >= 35: name = "Legend"
    elif score >= 25: name = "Master"
    elif score >= 15: name = "Elite"
    else: name = "Bronze"
    return name, RANK_COLORS.get(name, "#ffffff")

def is_maintenance_active():
    status = db_mgr.settings.find_one({"_id": "maintenance_mode"})
    return status if status is not None else {"active": False}


def _is_service_offline(service_name: str) -> bool:
    """service_name in {web, bot, database, backups}"""
    try:
        s = db_mgr.settings.find_one({"_id": "offline_mode"})
    except Exception:
        s = None
    if not s:
        return False
    return bool(s.get("services", {}).get(service_name, False))


def is_web_offline() -> bool:
    return _is_service_offline("web")


def is_bot_offline() -> bool:
    return _is_service_offline("bot")


def is_database_offline() -> bool:
    return _is_service_offline("database")

def is_partner_offline() -> bool:
    return _is_service_offline("partner")


def _reject_if_database_offline(write: bool = False):
    if not is_database_offline():
        return
    # In database-offline mode, allow maintenance check to still work.
    # For everything else, block reads/writes.
    raise RuntimeError("Database is offline")


# --- SKIN HELPERS ---
UUID_CACHE = {}
SKIN_CACHE = {}

def resolve_uuid(username):
    username = username.strip().lower()
    if username in UUID_CACHE:
        return UUID_CACHE[username]
    player = db_mgr.players.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
    if player and player.get("uuid"):
        UUID_CACHE[username] = player["uuid"]
        return player["uuid"]
    try:
        import urllib.request, json
        resp = urllib.request.urlopen(f"https://api.mojang.com/users/profiles/minecraft/{username}", timeout=5)
        if resp.status == 200:
            data = json.loads(resp.read())
            uuid = data["id"]
            UUID_CACHE[username] = uuid
            db_mgr.players.update_many({"username": {"$regex": f"^{username}$", "$options": "i"}}, {"$set": {"uuid": uuid}})
            return uuid
    except:
        pass
    return None

def get_skin_url(uuid):
    if uuid in SKIN_CACHE:
        return SKIN_CACHE[uuid]
    try:
        import urllib.request, json, base64
        resp = urllib.request.urlopen(f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}", timeout=5)
        if resp.status == 200:
            data = json.loads(resp.read())
            for prop in data.get("properties", []):
                if prop["name"] == "textures":
                    textures = json.loads(base64.b64decode(prop["value"]))
                    url = textures["textures"]["SKIN"]["url"]
                    SKIN_CACHE[uuid] = url
                    return url
    except:
        pass
    return None

def get_player_head_url(username, size=32):
    username = (username or "Steve").strip()
    player = db_mgr.players.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
    identifier = (player.get("uuid") or username) if player else username
    return f"https://minotar.net/helm/{identifier}/{size}"

# --- DISCORD BOT ---

# --- ACTION LOGGING (Discord) ---
async def log_action(action: str, details: str, interaction: discord.Interaction = None, public: bool = False, hide_action: bool = False) -> None:
    runner = ""
    if interaction is not None and getattr(interaction, "user", None) is not None:
        runner = f"{interaction.user.mention} ({interaction.user})"

    details_s = (details or "").strip()
    if len(details_s) > 1700:
        details_s = details_s[:1700] + "…"

    prefix = "" if hide_action else f"**[{action}]**\n"

    # Tier/admin-only channel (TIER_LOG_CHANNEL_ID)
    admin_channel = bot.get_channel(TIER_LOG_CHANNEL_ID)
    admin_msg = f"{prefix}{runner}\n{details_s}" if runner else f"{prefix}{details_s}"
    try:
        if admin_channel:
            await admin_channel.send(admin_msg)
    except Exception as e:
        print(f"[log_action] Failed to send tier log: {e}")

    # (Removed) Public channel (LOG_CHANNEL_ID) — now testers are responsible for sending to log channel.

    # Push to web console
    push_console_log(
        datetime.datetime.utcnow().isoformat(),
        action, details_s, runner
    )


# --- BACKUP LOOP (MongoDB) ---
BACKUP_DIR = os.getenv("MONGO_BACKUP_DIR", os.path.join(os.getcwd(), "mongo_backups"))

BACKUP_RETENTION_DAYS = int(os.getenv("MONGO_BACKUP_RETENTION_DAYS", "14"))
DB_NAME = os.getenv("MONGO_DB_NAME", "magmatiers_db")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _cleanup_old_backups(backup_dir: str, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
    try:
        for name in os.listdir(backup_dir):
            full = os.path.join(backup_dir, name)
            if not os.path.isdir(full):
                continue
            mtime = datetime.datetime.utcfromtimestamp(os.path.getmtime(full))
            if mtime < cutoff:
                shutil.rmtree(full, ignore_errors=True)
    except FileNotFoundError:
        return


def _run_mongodump_once() -> None:
    if not MONGO_URI:
        return

    _ensure_dir(BACKUP_DIR)

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    out_dir = os.path.join(BACKUP_DIR, f"{DB_NAME}-{ts}")
    os.makedirs(out_dir, exist_ok=True)

    # mongodump writes into the target directory.
    # Requires `mongodump` to be installed and available in PATH.
    cmd = [
        "mongodump",
        f"--uri={MONGO_URI}",
        f"--db={DB_NAME}",
        f"--out={out_dir}",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            # Don’t crash the server—just log.
            print("[backup] mongodump failed:")
            print(proc.stdout)
            print(proc.stderr)
            # If dump failed, remove directory to avoid confusion.
            shutil.rmtree(out_dir, ignore_errors=True)
            return

        _cleanup_old_backups(BACKUP_DIR, BACKUP_RETENTION_DAYS)
        print(f"[backup] MongoDB backup complete: {out_dir}")
    except FileNotFoundError:
        print("[backup] mongodump not found in PATH; skipping MongoDB backups.")
    except Exception as e:
        print(f"[backup] Unexpected error during backup: {e}")


def start_mongo_backup_loop() -> None:
    # Runs every 24 hours.
    def loop():
        # Stagger initial run to avoid multiple instances dumping at the same instant.
        time_to_sleep = int(os.getenv("MONGO_BACKUP_INITIAL_DELAY_SECONDS", "0"))
        if time_to_sleep > 0:
            try:
                import time
                time.sleep(time_to_sleep)
            except Exception:
                pass

        while True:
            _run_mongodump_once()
            try:
                import time
                time.sleep(24 * 60 * 60)
            except Exception:
                break

    t = threading.Thread(target=loop, daemon=True)
    t.start()


class MagmaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()
        self.add_view(EnterQueueView())
        self.add_view(VerifyIGNView())
        self.add_view(WaitlistButton())
        self.add_view(CloseTicketButton())
        refresh_region_queues.start()

    async def on_ready(self):
        tier_queue.setup()
        # Build channel -> gamemode reverse lookup
        global CHANNEL_TO_GAMEMODE
        CHANNEL_TO_GAMEMODE.clear()
        for gm, gdata in tier_queue.gamemodes.items():
            cid = gdata["channel_id"]
            if cid:
                CHANNEL_TO_GAMEMODE[cid] = gm
        # Send queue embeds to gamemode channels (entry points for players)
        for gm, gdata in tier_queue.gamemodes.items():
            chan_id = gdata["channel_id"]
            if not chan_id:
                continue
            channel = self.get_channel(chan_id)
            if not channel:
                continue
            try:
                async for msg in channel.history(limit=5):
                    if msg.author == self.user:
                        await msg.delete()
            except Exception:
                pass
            embed = tier_queue.make_gamemode_embed(gm)
            view = EnterQueueView()
            msg = await channel.send(embed=embed, view=view)
            gdata["message_id"] = msg.id
        # Send IGN verification embed
        verify_chan = self.get_channel(VERIFY_IGN_CHANNEL_ID)
        if verify_chan:
            async for msg in verify_chan.history(limit=5):
                if msg.author == self.user:
                    await msg.delete()
            verify_embed = discord.Embed(
                title="Verify Your Minecraft IGN",
                description="Click the button below to link your Minecraft IGN to your Discord account. This saves your IGN so you don't have to re-enter it every time you queue.",
                color=0x5865F2,
            )
            await verify_chan.send(embed=verify_embed, view=VerifyIGNView())

        # Send waitlist entry button
        waitlist_chan = self.get_channel(QUEUE_CHANNEL_ID)
        if waitlist_chan:
            async for msg in waitlist_chan.history(limit=5):
                if msg.author == self.user:
                    await msg.delete()
            waitlist_embed = discord.Embed(
                title="Join the Testing Waitlist",
                description="Click the button below to join the testing waitlist. You'll need to provide your Minecraft IGN, region, and preferred server.\n\nAlready registered? Just use the **Enter Queue** button in your gamemode channel!",
                color=0x5865F2,
            )
            await waitlist_chan.send(embed=waitlist_embed, view=WaitlistButton())

bot = MagmaBot()

# --- GAMEMODE ROLE SELECTION ---
class GamemodeRoleDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=gm, value=gm, description=f"Toggle {gm} role", emoji=None)
            for gm in GAMEMODE_ROLE_IDS.keys()
        ]
        super().__init__(placeholder="Select gamemode roles...", min_values=1, max_values=len(options), options=options, custom_id="gmrole_dropdown")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return
        added = []
        removed = []
        for gm in self.values:
            role_id = GAMEMODE_ROLE_IDS.get(gm)
            if not role_id:
                continue
            role = guild.get_role(role_id)
            if not role:
                continue
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Removed gamemode role")
                removed.append(gm)
            else:
                await interaction.user.add_roles(role, reason="Added gamemode role")
                added.append(gm)
        msg = ""
        if added:
            msg += f"Added: {', '.join(added)}\n"
        if removed:
            msg += f"Removed: {', '.join(removed)}"
        if not msg:
            msg = "No changes."
        await interaction.response.send_message(msg, ephemeral=True)

class GamemodeRoleDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeRoleDropdown())

@tasks.loop(seconds=30)
async def refresh_region_queues():
    # Update gamemode channel embeds
    for gm, gdata in tier_queue.gamemodes.items():
        gchan_id = gdata["channel_id"]
        gmsg_id = gdata.get("message_id")
        if not gchan_id or not gmsg_id:
            continue
        channel = bot.get_channel(gchan_id)
        if not channel:
            continue
        try:
            msg = await channel.fetch_message(gmsg_id)
            embed = tier_queue.make_gamemode_embed(gm)
            view = EnterQueueView()
            await msg.edit(embed=embed, view=view)
        except Exception:
            pass
    # Update region channel embeds
    for rcode, rdata in tier_queue.regions.items():
        if not rdata["open"]:
            continue
        chan_id = rdata["queue_channel_id"]
        msg_id = rdata.get("queue_message_id")
        if not chan_id or not msg_id:
            continue
        channel = bot.get_channel(chan_id)
        if not channel:
            continue
        try:
            msg = await channel.fetch_message(msg_id)
            embed = tier_queue.make_region_embed(rcode)
            await msg.edit(embed=embed)
        except Exception:
            pass












# --- QUEUE SYSTEM ---
def _get_tester_profiles():
    return list(db_mgr.tester_profiles.find({"online": True}))




class VerifyIGNModal(discord.ui.Modal, title="Verify Your IGN"):
    def __init__(self):
        super().__init__()
        self.ign_input = discord.ui.TextInput(
            label="Minecraft IGN",
            placeholder="Enter your Minecraft username",
            required=True,
            max_length=16,
        )
        self.add_item(self.ign_input)

    async def on_submit(self, interaction: discord.Interaction):
        ign = self.ign_input.value.strip()

        existing = db_mgr.players.find_one({"username": {"$regex": f"^{ign}$", "$options": "i"}, "discord_id": {"$ne": interaction.user.id}})
        if existing:
            return await interaction.response.send_message(f"The IGN **{ign}** is already linked to another Discord account.", ephemeral=True)

        uuid = resolve_uuid(ign)
        update = {
            "username": ign,
            "discord_id": interaction.user.id,
            "ts": datetime.datetime.utcnow(),
        }
        if uuid:
            update["uuid"] = uuid
        db_mgr.players.update_one(
            {"discord_id": interaction.user.id},
            {"$set": update},
            upsert=True,
        )
        embed = discord.Embed(title="IGN Verified!", color=0x34d399)
        embed.add_field(name="IGN", value=ign, inline=True)
        embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class VerifyIGNView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify IGN", style=discord.ButtonStyle.primary, custom_id="verify_ign")
    async def verify_ign(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyIGNModal())


class EnterQueueModal(discord.ui.Modal, title="Join Queue"):
    def __init__(self, gamemode, region, ign_default=""):
        super().__init__()
        self.gamemode = gamemode
        self.region = region

        self.ign_input = discord.ui.TextInput(
            label="In-Game Name",
            placeholder="Enter your Minecraft IGN",
            default=ign_default,
            required=not bool(ign_default),
            max_length=16,
        )
        self.add_item(self.ign_input)

    async def on_submit(self, interaction: discord.Interaction):
        ign = self.ign_input.value.strip()

        rdata = tier_queue.regions.get(self.region)
        if not rdata or not rdata["open"]:
            return await interaction.response.send_message(f"The {self.region} queue is not currently open.", ephemeral=True)

        result = tier_queue.add_user(self.region, interaction.user.id, ign=ign, gamemode=self.gamemode)
        await interaction.response.send_message(result, ephemeral=True)

        await _update_gamemode_queue_embed(self.gamemode)
        await _update_region_queue_embed(self.region)


class RegionSelectView(discord.ui.View):
    def __init__(self, gamemode, detected_region, ign_default):
        super().__init__(timeout=120)
        self.gamemode = gamemode
        self.detected_region = detected_region
        self.ign_default = ign_default

    @discord.ui.select(
        placeholder="Select your region...",
        options=[discord.SelectOption(label=rc, value=rc) for rc in REGION_ROLE_IDS.keys()],
        custom_id="region_select_queue",
    )
    async def select_region(self, interaction: discord.Interaction, select: discord.ui.Select):
        region = select.values[0]
        await interaction.response.send_modal(EnterQueueModal(self.gamemode, region, ign_default=self.ign_default))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="region_select_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


# Reverse lookup: channel_id -> gamemode
CHANNEL_TO_GAMEMODE = {}

class EnterQueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _gamemode_from_channel(self, channel_id):
        return CHANNEL_TO_GAMEMODE.get(channel_id)

    @discord.ui.button(label="Enter Queue", style=discord.ButtonStyle.success, custom_id="enter_queue")
    async def enter_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        gamemode = self._gamemode_from_channel(interaction.channel_id)
        if not gamemode:
            return await interaction.response.send_message("This channel is not set up for queuing.", ephemeral=True)

        player_doc = db_mgr.players.find_one({"discord_id": interaction.user.id})
        if player_doc and player_doc.get("banned"):
            return await interaction.response.send_message("You are restricted from queuing.", ephemeral=True)

        detected_region = None
        if interaction.guild and isinstance(interaction.user, discord.Member):
            for rcode, rid in REGION_ROLE_IDS.items():
                role = interaction.guild.get_role(rid)
                if role and role in interaction.user.roles:
                    detected_region = rcode
                    break

        if player_doc and player_doc.get("username") and detected_region:
            ign = player_doc["username"]
            rdata = tier_queue.regions.get(detected_region)
            if not rdata or not rdata["open"]:
                return await interaction.response.send_message(f"The {detected_region} queue is not currently open.", ephemeral=True)
            result = tier_queue.add_user(detected_region, interaction.user.id, ign=ign, gamemode=gamemode)
            await interaction.response.send_message(result, ephemeral=True)
            await _update_gamemode_queue_embed(gamemode)
            await _update_region_queue_embed(detected_region)
            return

        ign_default = player_doc.get("username", "") if player_doc else ""
        view = RegionSelectView(gamemode, detected_region or "NA", ign_default=ign_default)
        await interaction.response.send_message("Select your region:", view=view, ephemeral=True)

    @discord.ui.button(label="Exit Queue", style=discord.ButtonStyle.danger, custom_id="exit_queue")
    async def exit_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        gamemode = self._gamemode_from_channel(interaction.channel_id)
        if not gamemode:
            return await interaction.response.send_message("This channel is not set up for queuing.", ephemeral=True)

        region = None
        if interaction.guild and isinstance(interaction.user, discord.Member):
            for rcode, rid in REGION_ROLE_IDS.items():
                role = interaction.guild.get_role(rid)
                if role and role in interaction.user.roles:
                    region = rcode
                    break
        if not region:
            return await interaction.response.send_message("You must have a region role (EU, NA, AF, AS, or OC) to queue.", ephemeral=True)

        result = tier_queue.remove_user(region, interaction.user.id)
        await interaction.response.send_message(result, ephemeral=True)

        await _update_gamemode_queue_embed(gamemode)
        await _update_region_queue_embed(region)

    @discord.ui.button(label="My Position", style=discord.ButtonStyle.secondary, custom_id="queue_position")
    async def my_position(self, interaction: discord.Interaction, button: discord.ui.Button):
        found = None
        for rcode, rdata in tier_queue.regions.items():
            for i, entry in enumerate(rdata["queue"]):
                if entry["user_id"] == interaction.user.id:
                    found = (rcode, i + 1, len(rdata["queue"]), rdata["open"])
                    break
            if found:
                break

        if not found:
            return await interaction.response.send_message("You are not in any queue.", ephemeral=True)

        region, pos, total, is_open = found
        ahead = pos - 1
        embed = discord.Embed(title=f"Queue Position — {region}", color=0x5865F2)
        embed.add_field(name="Position", value=f"**#{pos}** of {total}", inline=True)
        embed.add_field(name="Ahead of You", value=f"{ahead} player{'s' if ahead != 1 else ''}", inline=True)

        rdata = tier_queue.regions[region]
        testers = len(rdata["testers"])
        if is_open and testers > 0:
            est_min = max(5, (ahead // testers) * 12)
            embed.add_field(name="Est. Wait", value=f"~{est_min} min", inline=True)
        elif not is_open:
            embed.add_field(name="Status", value="Queue closed", inline=True)
        else:
            embed.add_field(name="Status", value="No testers online", inline=True)

        if ahead > 0:
            ahead_users = [f"{i+1}. <@{e['user_id']}> ({e['ign']})" for i, e in enumerate(rdata["queue"][:pos-1])]
            embed.add_field(name="Ahead of You", value="\n".join(ahead_users[-5:]), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="openqueue")
async def openqueue(interaction: discord.Interaction, region: str):
    """Open the queue for a region and mark yourself as a tester (staff only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    region_u = region.upper().strip()
    if region_u not in REGION_ROLE_IDS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_ROLE_IDS.keys())}", ephemeral=True)

    result = tier_queue.add_tester(region_u, interaction.user.id)
    await _update_region_queue_embed(region_u)
    await interaction.response.send_message(f"{result} for **{region_u}**.", ephemeral=True)


@bot.tree.command(name="closequeue")
async def closequeue(interaction: discord.Interaction, region: str):
    """Close the queue for a region and remove yourself as tester (staff only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    region_u = region.upper().strip()
    if region_u not in REGION_ROLE_IDS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_ROLE_IDS.keys())}", ephemeral=True)

    result = tier_queue.remove_tester(region_u, interaction.user.id)
    await _update_region_queue_embed(region_u)
    await interaction.response.send_message(f"{result} for **{region_u}**.", ephemeral=True)


@bot.tree.command(name="next")
async def next_in_queue(interaction: discord.Interaction):
    """Claim the next player matching your region and online gamemodes (staff only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)

    region_u = None
    if interaction.guild and isinstance(interaction.user, discord.Member):
        for rcode, rid in REGION_ROLE_IDS.items():
            role = interaction.guild.get_role(rid)
            if role and role in interaction.user.roles:
                region_u = rcode
                break
    if not region_u:
        return await interaction.response.send_message("You must have a region role (EU, NA, AF, AS, or OC) to use /next.", ephemeral=True)

    # Get tester's online gamemodes
    tester_doc = db_mgr.tester_profiles.find_one({"discord_id": interaction.user.id})
    if not tester_doc or not tester_doc.get("online"):
        return await interaction.response.send_message("You are not online as a tester. Use /online first.", ephemeral=True)
    online_modes = set(tester_doc.get("gamemodes", []))
    if not online_modes:
        return await interaction.response.send_message("You have no gamemodes selected. Use /online <gamemodes> first.", ephemeral=True)

    rdata = tier_queue.regions.get(region_u)
    if not rdata or not rdata["open"]:
        return await interaction.response.send_message(f"The {region_u} queue is not open.", ephemeral=True)
    if interaction.user.id not in rdata["testers"]:
        return await interaction.response.send_message("You must be a tester for this region to claim the next user. Use /openqueue first.", ephemeral=True)

    entry = tier_queue.next_for_tester(region_u, online_modes)
    if not entry:
        return await interaction.response.send_message(f"No users in the {region_u} queue match your online gamemodes ({', '.join(sorted(online_modes))}).", ephemeral=True)

    user_id = entry["user_id"]
    player_name = entry.get("ign", "Unknown")
    player_mention = f"<@{user_id}>"
    tester_mention = interaction.user.mention
    entry_gamemode = entry.get("gamemode") or "Any"
    # Fetch full player info for tier display
    player_doc = db_mgr.players.find_one({"discord_id": user_id})

    # Create ticket channel in region's category
    category_id = rdata["ticket_category_id"]
    ticket_channel = None
    if category_id:
        category = bot.get_channel(category_id)
        if category and isinstance(category, discord.CategoryChannel):
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            target_member = interaction.guild.get_member(user_id)
            if target_member:
                overwrites[target_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            safe_name = player_name.replace(" ", "-").lower()[:32]
            ticket_channel = await category.create_text_channel(f"ticket-{safe_name}", overwrites=overwrites)

    # Send ticket info
    embed = discord.Embed(title=f"Next in Queue — {region_u}", color=0x34d399)
    embed.add_field(name="Player", value=f"{player_mention} ({player_name})", inline=True)
    embed.add_field(name="Gamemode", value=entry_gamemode, inline=True)
    embed.add_field(name="Tester", value=tester_mention, inline=True)
    embed.add_field(name="Region", value=region_u, inline=True)
    if player_doc:
        active_modes = []
        for gm in MODES:
            record = db_mgr.players.find_one({"discord_id": user_id, "gamemode": gm})
            if record and not record.get("retired") and not record.get("banned"):
                active_modes.append(f"{gm}: {record.get('tier', 'N/A')}")
        if active_modes:
            embed.add_field(name="Tiers", value="\n".join(active_modes), inline=False)

    msg = f"{player_mention}, {tester_mention}"
    if ticket_channel:
        msg += f"\nTicket channel: {ticket_channel.mention}"
        await ticket_channel.send(embed=embed)
    await interaction.response.send_message(msg, ephemeral=False)

    # Update the queue embed
    await _update_region_queue_embed(region_u)













class PartnerView(discord.ui.View):
    def __init__(self, sub_id, channel_id):
        super().__init__(timeout=None)
        self.sub_id = sub_id
        self.channel_id = channel_id

    async def _update(self, interaction, new_status, color):
        await interaction.response.defer()
        try:
            doc = db_mgr.partners.find_one({"_id": ObjectId(self.sub_id)})
            if not doc:
                return await interaction.followup.send("Submission not found.", ephemeral=True)
            db_mgr.partners.update_one({"_id": ObjectId(self.sub_id)}, {"$set": {"status": new_status}})
            embed = interaction.message.embeds[0]
            embed.color = color
            old_count = len(embed.fields)
            embed.remove_field(old_count - 1)
            embed.add_field(name="Status", value=new_status, inline=True)
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(embed=embed, view=self)

            if "Approved" in new_status and doc.get("discord_id"):
                try:
                    category = interaction.guild.get_channel(PARTNER_CATEGORY_ID) if interaction.guild else None
                    if category and isinstance(category, discord.CategoryChannel):
                        ign = doc.get("ign", "partner")
                        member = interaction.guild.get_member(doc["discord_id"])
                        overwrites = {
                            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                        }
                        if member:
                            overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        chan = await category.create_text_channel(f"partner-{ign}", overwrites=overwrites)
                        await chan.send(f"Welcome {member.mention if member else doc.get('discord_user', '')}! Your partner application has been approved.")
                        db_mgr.partners.update_one({"_id": ObjectId(self.sub_id)}, {"$set": {"channel_id": chan.id}})
                except Exception:
                    pass
        except Exception:
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="partner_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await self._update(interaction, "Approved ✅", 0x34d399)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="partner_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await self._update(interaction, "Declined ❌", 0xf87171)









@bot.tree.command(name="online")
async def tester_online(interaction: discord.Interaction, gamemodes: str):
    """Set yourself online for specific gamemodes. Region detected from your roles."""
    parsed = set(normalize_mode(m.strip()) for m in gamemodes.split(","))
    parsed = {m for m in parsed if m in MODES}

    if not parsed:
        return await interaction.response.send_message(
            f"No valid gamemodes provided. Choose from: {', '.join(MODES)}",
            ephemeral=True,
        )

    parsed_list = sorted(parsed)

    region_u = None
    if interaction.guild and isinstance(interaction.user, discord.Member):
        for rcode, rid in REGION_ROLE_IDS.items():
            role = interaction.guild.get_role(rid)
            if role and role in interaction.user.roles:
                region_u = rcode
                break

    if not region_u:
        return await interaction.response.send_message(
            "You must have a region role (EU, NA, AF, AS, or OC) assigned to use this command.",
            ephemeral=True,
        )

    ign = None
    player_doc = db_mgr.players.find_one({"discord_id": interaction.user.id})
    if player_doc:
        ign = player_doc.get("username")

    db_mgr.tester_profiles.update_one(
        {"discord_id": interaction.user.id},
        {"$set": {
            "ign": ign or interaction.user.display_name,
            "region": region_u,
            "gamemodes": parsed_list,
            "online": True,
            "ts": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )

    # Auto-open the region queue when tester goes online
    tier_queue.add_tester(region_u, interaction.user.id)
    await _update_region_queue_embed(region_u)

    # Ping each gamemode role in its channel
    for gm in parsed_list:
        role_id = GAMEMODE_ROLE_IDS.get(gm)
        chan_id = GAMEMODE_QUEUE_CHANNELS.get(gm)
        if role_id and chan_id:
            gchan = bot.get_channel(chan_id)
            if gchan:
                await gchan.send(f"<@&{role_id}>", delete_after=1)

    modes_str = ", ".join(parsed_list)
    embed = discord.Embed(title="You're now online!", color=0x34d399)
    embed.add_field(name="IGN", value=ign or "Not set", inline=True)
    embed.add_field(name="Region", value=region_u, inline=True)
    embed.add_field(name="Testing", value=modes_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _update_region_queue_embed(region):
    rdata = tier_queue.regions.get(region)
    if not rdata:
        return
    embed = tier_queue.make_region_embed(region)
    chan_id = rdata["queue_channel_id"]
    if not chan_id:
        return
    channel = bot.get_channel(chan_id)
    if not channel:
        return
    msg_id = rdata.get("queue_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
        except Exception:
            pass
    else:
        try:
            msg = await channel.send(embed=embed)
            rdata["queue_message_id"] = msg.id
        except Exception:
            pass


async def _update_gamemode_queue_embed(gamemode):
    gdata = tier_queue.gamemodes.get(gamemode)
    if not gdata:
        return
    is_open = tier_queue.is_gamemode_open(gamemode)
    embed = tier_queue.make_gamemode_embed(gamemode)
    chan_id = gdata["channel_id"]
    if not chan_id:
        return
    channel = bot.get_channel(chan_id)
    if not channel:
        return
    msg_id = gdata.get("message_id")

    just_closed = not is_open and gdata["was_open"]
    if just_closed:
        gdata["closed_at"] = datetime.datetime.utcnow()
    gdata["was_open"] = is_open

    if not is_open:
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=None, embed=embed, view=EnterQueueView())
            except Exception:
                pass
        else:
            try:
                msg = await channel.send(embed=embed, view=EnterQueueView())
                gdata["message_id"] = msg.id
            except Exception:
                pass
        return

    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed, view=EnterQueueView())
        except Exception:
            pass
    else:
        try:
            msg = await channel.send(embed=embed, view=EnterQueueView())
            gdata["message_id"] = msg.id
        except Exception:
            pass


@bot.tree.command(name="offline")
async def tester_offline(interaction: discord.Interaction, gamemodes: str):
    """Go offline in specific gamemodes or all. Example: /offline Crystal,UHC"""
    existing = db_mgr.tester_profiles.find_one({"discord_id": interaction.user.id})
    if not existing:
        return await interaction.response.send_message("You're not in the tester list.", ephemeral=True)

    region_u = existing.get("region")
    if not region_u:
        region_u = None
        if interaction.guild and isinstance(interaction.user, discord.Member):
            for rcode, rid in REGION_ROLE_IDS.items():
                role = interaction.guild.get_role(rid)
                if role and role in interaction.user.roles:
                    region_u = rcode
                    break

    lowered = gamemodes.strip().lower()
    if lowered == "all":
        db_mgr.tester_profiles.update_one(
            {"discord_id": interaction.user.id},
            {"$set": {"online": False, "ts": datetime.datetime.utcnow()}},
        )
        if region_u:
            tier_queue.remove_tester(region_u, interaction.user.id)
            await _update_region_queue_embed(region_u)
        await interaction.response.send_message("You're now **offline** for all gamemodes.", ephemeral=True)
        return

    parsed = set(normalize_mode(m.strip()) for m in gamemodes.split(","))
    parsed = {m for m in parsed if m in MODES}

    if not parsed:
        return await interaction.response.send_message(
            f"No valid gamemodes provided. Use /offline all or choose from: {', '.join(MODES)}",
            ephemeral=True,
        )

    current = set(existing.get("gamemodes", []))
    updated = sorted(current - parsed)

    if not updated:
        db_mgr.tester_profiles.update_one(
            {"discord_id": interaction.user.id},
            {"$set": {"online": False, "gamemodes": [], "ts": datetime.datetime.utcnow()}},
        )
        if region_u:
            tier_queue.remove_tester(region_u, interaction.user.id)
            await _update_region_queue_embed(region_u)
        await interaction.response.send_message("All gamemodes removed. You're now **offline**.", ephemeral=True)
    else:
        db_mgr.tester_profiles.update_one(
            {"discord_id": interaction.user.id},
            {"$set": {"gamemodes": updated, "ts": datetime.datetime.utcnow()}},
        )
        await interaction.response.send_message(
            f"Went **offline** in: {', '.join(sorted(parsed))}\nStill testing: {', '.join(updated)}",
            ephemeral=True)








# --- WAITLIST (for new users) ---
class WaitlistForm(discord.ui.Modal, title="Join the Waitlist"):
    def __init__(self):
        super().__init__()
        self.ign = discord.ui.TextInput(label="Minecraft Username", placeholder="Enter your in-game name", required=True, max_length=16)
        self.region = discord.ui.TextInput(label="Region (EU, NA, AF, AS, OC)", placeholder="Enter your region", required=True, max_length=5)
        self.server = discord.ui.TextInput(label="Preferred Server", placeholder="Enter your preferred server", required=True, max_length=100)
        self.add_item(self.ign)
        self.add_item(self.region)
        self.add_item(self.server)

    async def on_submit(self, interaction: discord.Interaction):
        ign = self.ign.value.strip()
        region = self.region.value.strip().upper()
        server = self.server.value.strip()

        if region not in REGION_ROLE_IDS:
            return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_ROLE_IDS.keys())}", ephemeral=True)

        existing = db_mgr.players.find_one({"username": {"$regex": f"^{ign}$", "$options": "i"}, "discord_id": {"$ne": interaction.user.id}})
        if existing:
            return await interaction.response.send_message(f"The IGN **{ign}** is already linked to another Discord account.", ephemeral=True)

        uuid = resolve_uuid(ign)
        if not uuid:
            return await interaction.response.send_message("Could not verify Minecraft username. Make sure it exists on Mojang's API.", ephemeral=True)

        db_mgr.players.update_one(
            {"discord_id": interaction.user.id},
            {"$set": {
                "username": ign,
                "uuid": uuid,
                "region": region,
                "server": server,
                "discord_id": interaction.user.id,
                "ts": datetime.datetime.utcnow(),
            }},
            upsert=True,
        )

        region_role_id = REGION_ROLE_IDS.get(region)
        if region_role_id and interaction.guild:
            role = interaction.guild.get_role(region_role_id)
            if role and role not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(role, reason="Joined waitlist")
                except Exception:
                    pass

        queue_channel_id = REGION_QUEUE_CHANNELS.get(region)
        queue_mention = f"<#{queue_channel_id}>" if queue_channel_id else "your region's queue channel"
        embed = discord.Embed(title="Welcome to the Waitlist!", color=0x34d399)
        embed.add_field(name="IGN", value=ign, inline=True)
        embed.add_field(name="Region", value=region, inline=True)
        embed.add_field(name="Server", value=server, inline=True)
        embed.add_field(name="Next Step", value=f"Go to {queue_mention} and click **Enter Queue** when testers are online.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WaitlistButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Enter Waitlist", style=discord.ButtonStyle.primary, custom_id="waitlist_button")
    async def enter_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        player_doc = db_mgr.players.find_one({"discord_id": interaction.user.id})
        if player_doc:
            is_banned = player_doc.get("banned", False)
            if is_banned:
                return await interaction.response.send_message("You are currently restricted from testing.", ephemeral=True)
            region = player_doc.get("region", "").upper()
            if region in REGION_QUEUE_CHANNELS:
                queue_mention = f"<#{REGION_QUEUE_CHANNELS[region]}>"
                return await interaction.response.send_message(f"You're already registered! Go to {queue_mention} and click **Enter Queue** when testers are online.", ephemeral=True)
        await interaction.response.send_modal(WaitlistForm())


# --- CLOSE TICKET BUTTON ---
class CloseTicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.cancelled = False

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="close_ticket_cancel")
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cancelled = True
        await interaction.response.send_message("Ticket will stay open.", ephemeral=True)


# --- NEW COMMANDS ---

TIER_LIMIT_LT3 = get_tier_value("LT3")

def _get_tester_role(member: discord.Member):
    if HIGH_TESTER_ROLE_ID and member.get_role(HIGH_TESTER_ROLE_ID):
        return "high"
    if TESTER_ROLE_ID and member.get_role(TESTER_ROLE_ID):
        return "tester"
    if TRAINEE_ROLE_ID and member.get_role(TRAINEE_ROLE_ID):
        return "trainee"
    return None

def _can_assign_tier(member: discord.Member, tier: str) -> tuple[bool, str]:
    role = _get_tester_role(member)
    if not role:
        return False, "You do not have a tester role."
    if role == "trainee":
        return False, "Trainee testers cannot assign tiers."
    tval = get_tier_value(tier)
    if tval == 0:
        return False, f"Invalid tier: {tier}"
    if role == "tester" and tval > TIER_LIMIT_LT3:
        return False, f"Testers can only assign tiers up to LT3. **{tier}** requires a High Tester."
    return True, ""

def _ensure_player(user_id, username=None):
    doc = db_mgr.players.find_one({"discord_id": user_id})
    if not doc:
        db_mgr.players.insert_one({
            "discord_id": user_id,
            "username": username or "Unknown",
            "tier": "none",
            "banned": False,
            "ts": datetime.datetime.utcnow(),
        })
        return db_mgr.players.find_one({"discord_id": user_id})
    return doc

@bot.tree.command(name="givetier", description="Gives a tier to a user for a specific gamemode (staff only)")
async def givetier(interaction: discord.Interaction, user: discord.Member, gamemode: str, tier: str):
    if not interaction.user.guild_permissions.manage_roles and not _get_tester_role(interaction.user):
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    can_assign, msg = _can_assign_tier(interaction.user, tier)
    if not can_assign:
        return await interaction.response.send_message(msg, ephemeral=True)

    gm = normalize_mode(gamemode.strip())
    if gm not in MODES:
        return await interaction.response.send_message(f"Invalid gamemode. Choose: {', '.join(MODES)}", ephemeral=True)

    player_doc = _ensure_player(user.id, user.display_name)
    if player_doc.get("banned", False):
        return await interaction.response.send_message("User is restricted.", ephemeral=True)

    gm_tier_doc = db_mgr.players.find_one({"discord_id": user.id, "gamemode": gm})
    old_tier = gm_tier_doc.get("tier", "none") if gm_tier_doc else "none"
    username = player_doc.get("username", "Unknown")
    region = player_doc.get("region", "NA")

    uuid = resolve_uuid(username)
    embed = discord.Embed(title="Tier Result", color=0x34d399, timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Player", value=user.mention, inline=True)
    embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
    embed.add_field(name="Gamemode", value=gm, inline=True)
    embed.add_field(name="Region", value=region, inline=True)
    embed.add_field(name="IGN", value=username, inline=True)
    embed.add_field(name="Previous Tier", value=old_tier, inline=True)
    embed.add_field(name="New Tier", value=tier, inline=True)
    if uuid:
        embed.set_thumbnail(url=f"https://render.crafty.gg/3d/bust/{uuid}")

    # Save per-gamemode tier
    db_mgr.players.update_one(
        {"discord_id": user.id, "gamemode": gm},
        {"$set": {
            "gamemode": gm,
            "discord_id": user.id,
            "username": username,
            "tier": tier,
            "ts": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )
    # Also store in a results log
    db_mgr.reports.insert_one({
        "discord_id": user.id,
        "username": username,
        "gamemode": gm,
        "tester_id": interaction.user.id,
        "old_tier": old_tier,
        "new_tier": tier,
        "region": region,
        "ts": datetime.datetime.utcnow(),
    })

    # Remove old region roles
    member = interaction.guild.get_member(user.id)
    if member:
        region_roles_to_remove = [role for role in member.roles if role.id in REGION_ROLE_IDS.values()]
        if region_roles_to_remove:
            await member.remove_roles(*region_roles_to_remove, reason="Region roles removed by /givetier")

    await log_action("GIVETIER", f"{user.mention} ({username}): [{gm}] {old_tier} → {tier} in {region}", interaction)
    await interaction.response.send_message(embed=embed)
    await _update_gamemode_queue_embed(gm)


@bot.tree.command(name="closetest", description="Closes the current test ticket (staff only)")
async def closetest(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    category_ids = list(REGION_TICKET_CATEGORIES.values())
    if not interaction.channel.category or interaction.channel.category.id not in category_ids:
        return await interaction.response.send_message("This command can only be used in testing channels.", ephemeral=True)
    if interaction.channel.id in REGION_QUEUE_CHANNELS.values() or interaction.channel.id in GAMEMODE_QUEUE_CHANNELS.values():
        return await interaction.response.send_message("You cannot use this command in this channel.", ephemeral=True)

    view = CloseTicketButton()
    await interaction.response.send_message("Ticket will be closed in 10 seconds", view=view)
    await asyncio.sleep(10)
    if not view.cancelled:
        await interaction.channel.delete(reason="Ticket channel closed by command.")


@bot.tree.command(name="forceclosetest", description="Force closes the current test ticket (staff only)")
async def forceclosetest(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    category_ids = list(REGION_TICKET_CATEGORIES.values())
    if not interaction.channel.category or interaction.channel.category.id not in category_ids:
        return await interaction.response.send_message("This command can only be used in testing channels.", ephemeral=True)
    if interaction.channel.id in REGION_QUEUE_CHANNELS.values() or interaction.channel.id in GAMEMODE_QUEUE_CHANNELS.values():
        return await interaction.response.send_message("You cannot use this command in this channel.", ephemeral=True)

    await interaction.response.send_message("Ticket will be closed in 10 seconds, cannot cancel")
    await asyncio.sleep(10)
    await interaction.channel.delete(reason="Ticket channel closed by command.")


@bot.tree.command(name="updateusername", description="Updates a user's Minecraft username (staff only)")
async def updateusername(interaction: discord.Interaction, user: discord.Member, username: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    player_doc = _ensure_player(user.id, user.display_name)
    if not uuid:
        return await interaction.response.send_message("Minecraft username does not exist.", ephemeral=True)

    db_mgr.players.update_one(
        {"discord_id": user.id},
        {"$set": {"username": username, "uuid": uuid, "ts": datetime.datetime.utcnow()}},
    )
    await interaction.response.send_message("Username successfully updated.", ephemeral=True)


@bot.tree.command(name="updatetier", description="Updates a user's tier in the database (staff only)")
async def updatetier(interaction: discord.Interaction, user: discord.Member, tier: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    player_doc = db_mgr.players.find_one({"discord_id": user.id})
    if not player_doc:
        return await interaction.response.send_message("User does not exist in the database.", ephemeral=True)

    db_mgr.players.update_one(
        {"discord_id": user.id},
        {"$set": {"tier": tier, "ts": datetime.datetime.utcnow()}},
    )
    await interaction.response.send_message("Tier successfully updated in database. You will need to change their roles manually.", ephemeral=True)


@bot.tree.command(name="restrict", description="Restricts a user from queuing (staff only)")
async def restrict(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    _ensure_player(user.id, user.display_name)
    db_mgr.players.update_one(
        {"discord_id": user.id},
        {"$set": {"banned": True, "ts": datetime.datetime.utcnow()}},
    )
    await interaction.response.send_message("User has been restricted.", ephemeral=True)


@bot.tree.command(name="unrestrict", description="Unrestricts a user (staff only)")
async def unrestrict(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    _ensure_player(user.id, user.display_name)
    db_mgr.players.update_one(
        {"discord_id": user.id},
        {"$set": {"banned": False, "ts": datetime.datetime.utcnow()}},
    )
    await interaction.response.send_message("User has been unrestricted.", ephemeral=True)


@bot.tree.command(name="info", description="Shows information about a user")
async def info(interaction: discord.Interaction, user: discord.Member):
    player_doc = _ensure_player(user.id, user.display_name)

    username = player_doc.get("username", "Unknown")
    tier = player_doc.get("tier", "none")
    region = player_doc.get("region", "N/A")
    last_test = player_doc.get("ts")
    restricted = player_doc.get("banned", False)
    uuid = player_doc.get("uuid") or resolve_uuid(username)

    embed = discord.Embed(title=f"Info — {user.display_name}", color=0x5865F2)
    embed.add_field(name="IGN", value=username, inline=True)
    embed.add_field(name="Tier", value=tier, inline=True)
    embed.add_field(name="Region", value=region, inline=True)
    embed.add_field(name="Restricted", value="Yes ❌" if restricted else "No ✅", inline=True)
    if last_test:
        embed.add_field(name="Last Test", value=f"<t:{int(last_test.timestamp())}:f>", inline=True)
    if uuid:
        embed.set_thumbnail(url=f"https://render.crafty.gg/3d/bust/{uuid}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="add", description="Adds a user to the current ticket (staff only)")
async def add_to_ticket(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    category_ids = list(REGION_TICKET_CATEGORIES.values())
    if not interaction.channel.category or interaction.channel.category.id not in category_ids:
        return await interaction.response.send_message("This command can only be used in testing channels.", ephemeral=True)

    overwrite = discord.PermissionOverwrite()
    overwrite.view_channel = True
    overwrite.send_messages = True
    await interaction.channel.set_permissions(user, overwrite=overwrite)
    await interaction.response.send_message(f"{user.mention} has been added to the ticket!")


@bot.tree.command(name="remove", description="Removes a user from the current ticket (staff only)")
async def remove_from_ticket(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    category_ids = list(REGION_TICKET_CATEGORIES.values())
    if not interaction.channel.category or interaction.channel.category.id not in category_ids:
        return await interaction.response.send_message("This command can only be used in testing channels.", ephemeral=True)

    overwrite = discord.PermissionOverwrite()
    overwrite.view_channel = False
    overwrite.send_messages = False
    await interaction.channel.set_permissions(user, overwrite=overwrite)
    await interaction.response.send_message(f"{user.mention} has been removed from the ticket!")


@bot.tree.command(name="passeval", description="Marks a user as passed eval (staff only)")
async def passeval(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    category_ids = list(REGION_TICKET_CATEGORIES.values())
    if not interaction.channel.category or interaction.channel.category.id not in category_ids:
        return await interaction.response.send_message("This command can only be used in testing channels.", ephemeral=True)
    if interaction.channel.id in REGION_QUEUE_CHANNELS.values() or interaction.channel.id in GAMEMODE_QUEUE_CHANNELS.values():
        return await interaction.response.send_message("You cannot use this command in this channel.", ephemeral=True)

    await interaction.channel.edit(name=f"passeval-{user.display_name}")
    await interaction.response.send_message(f"{user.mention} has passed eval!")


@bot.tree.command(name="forceoffline", description="Force a tester offline (High Tester/Admin only)")
async def forceoffline(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles and _get_tester_role(interaction.user) != "high":
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    doc = db_mgr.tester_profiles.find_one({"discord_id": user.id})
    if not doc or not doc.get("online"):
        return await interaction.response.send_message(f"{user.mention} is not online as a tester.", ephemeral=True)

    region_u = doc.get("region")
    old_gamemodes = list(doc.get("gamemodes", []))

    db_mgr.tester_profiles.update_one(
        {"discord_id": user.id},
        {"$set": {"online": False, "gamemodes": [], "ts": datetime.datetime.utcnow()}},
    )

    if region_u:
        tier_queue.remove_tester(region_u, user.id)
        await _update_region_queue_embed(region_u)

    for gm in old_gamemodes:
        await _update_gamemode_queue_embed(gm)

    await interaction.response.send_message(
        f"{user.mention} has been forced offline by {interaction.user.mention}.", ephemeral=False
    )
    await log_action("FORCEOFFLINE", f"{user.mention} forced offline by {interaction.user.mention}", interaction)


@bot.tree.command(name="leaderboard", description="Show top testers by completed tests")
async def leaderboard(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles and not _get_tester_role(interaction.user):
        return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

    pipeline = [
        {"$group": {"_id": "$tester_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    top_testers = list(db_mgr.reports.aggregate(pipeline))
    if not top_testers:
        return await interaction.response.send_message("No test results recorded yet.", ephemeral=True)

    embed = discord.Embed(title="Test Leaderboard", color=0xffd700)
    for i, entry in enumerate(top_testers, 1):
        tid = entry["_id"]
        count = entry["count"]
        member = interaction.guild.get_member(tid) if interaction.guild else None
        if member:
            name = member.mention
        else:
            tdoc = db_mgr.tester_profiles.find_one({"discord_id": tid})
            ign = (tdoc.get("ign") or tdoc.get("username") or f"<@{tid}>") if tdoc else f"<@{tid}>"
            name = ign
        medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(i, f"**#{i}**")
        embed.add_field(name=f"{medal} {name}", value=f"{count} test{'s' if count != 1 else ''}", inline=False)

    await interaction.response.send_message(embed=embed)


class PartnerView(discord.ui.View):
    def __init__(self, sub_id, channel_id):
        super().__init__(timeout=None)
        self.sub_id = sub_id
        self.channel_id = channel_id

    async def _update(self, interaction, new_status, color):
        await interaction.response.defer()
        try:
            doc = db_mgr.partners.find_one({"_id": ObjectId(self.sub_id)})
            if not doc:
                return await interaction.followup.send("Submission not found.", ephemeral=True)
            db_mgr.partners.update_one({"_id": ObjectId(self.sub_id)}, {"$set": {"status": new_status}})
            embed = interaction.message.embeds[0]
            embed.color = color
            old_count = len(embed.fields)
            embed.remove_field(old_count - 1)
            embed.add_field(name="Status", value=new_status, inline=True)
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(embed=embed, view=self)

            if "Approved" in new_status and doc.get("discord_id"):
                try:
                    category = interaction.guild.get_channel(PARTNER_CATEGORY_ID) if interaction.guild else None
                    if category and isinstance(category, discord.CategoryChannel):
                        ign = doc.get("ign", "partner")
                        member = interaction.guild.get_member(doc["discord_id"])
                        overwrites = {
                            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                        }
                        if member:
                            overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        chan = await category.create_text_channel(f"partner-{ign}", overwrites=overwrites)
                        await chan.send(f"Welcome {member.mention if member else doc.get('discord_user', '')}! Your partner application has been approved.")
                        db_mgr.partners.update_one({"_id": ObjectId(self.sub_id)}, {"$set": {"channel_id": chan.id}})
                except Exception:
                    pass
        except Exception:
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="partner_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await self._update(interaction, "Approved ✅", 0x34d399)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="partner_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await self._update(interaction, "Declined ❌", 0xf87171)


async def _get_ip_geo(ip):
    if not ip or ip in ("unknown", "127.0.0.1", "::1", "localhost"):
        return None
    try:
        import json, urllib.request
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(f"http://ip-api.com/json/{ip}", timeout=5))
        if resp.status == 200:
            data = json.loads(resp.read())
            if data.get("status") == "success":
                return data
    except:
        pass
    return None


def _log_ip_association(discord_id, ip, username=None, source=None):
    if not ip or ip in ("unknown", "127.0.0.1", "::1", "localhost"):
        return
    db_mgr.alt_logs.update_one(
        {"discord_id": discord_id, "ip": ip},
        {"$set": {
            "discord_id": discord_id, "ip": ip,
            "username": username,
            "source": source,
            "ts": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )


async def _handle_verify(interaction: discord.Interaction, doc):
    await interaction.response.defer(ephemeral=True)
    member = interaction.user
    guild = interaction.guild
    ip = doc.get("ip", "unknown")

    member_role = None
    unverified_role = None

    if MEMBER_ROLE_ID:
        member_role = guild.get_role(MEMBER_ROLE_ID)
    if not member_role:
        member_role = discord.utils.get(guild.roles, name=MEMBER_ROLE_NAME)

    if UNVERIFIED_ROLE_ID:
        unverified_role = guild.get_role(UNVERIFIED_ROLE_ID)
    if not unverified_role:
        unverified_role = discord.utils.get(guild.roles, name=UNVERIFIED_ROLE_NAME)

    try:
        if member_role and member_role not in member.roles:
            await member.add_roles(member_role, reason="Discord verification")
        if unverified_role and unverified_role in member.roles:
            await member.remove_roles(unverified_role, reason="Discord verification")
    except Exception as e:
        await interaction.followup.send(f"Failed to update roles: {e}", ephemeral=True)
        return

    _log_ip_association(member.id, ip, source="verify")

    geo = await _get_ip_geo(ip)

    db_mgr.link_codes.update_one({"_id": doc["_id"]}, {"$set": {
        "claimed": True,
        "discord_id": interaction.user.id,
        "discord_name": str(interaction.user),
        "claimed_ts": datetime.datetime.utcnow(),
    }})

    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if channel:
        e = discord.Embed(title="New Verification", color=0x34d399, timestamp=datetime.datetime.utcnow())
        e.add_field(name="User", value=f"{member.mention} ({member})", inline=True)
        e.add_field(name="ID", value=str(member.id), inline=True)
        e.add_field(name="Created", value=member.created_at.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
        e.add_field(name="Joined", value=member.joined_at.strftime("%Y-%m-%d %H:%M UTC") if member.joined_at else "Unknown", inline=True)
        if geo:
            e.add_field(name="Country", value=geo.get("country", "?"), inline=True)
            e.add_field(name="Region", value=geo.get("regionName", "?"), inline=True)
            e.add_field(name="City", value=geo.get("city", "?"), inline=True)
            e.add_field(name="ISP", value=geo.get("isp", "?"), inline=True)
            e.add_field(name="IP", value=ip, inline=True)
        e.set_footer(text="Verified via web")
        await channel.send(embed=e)

    await interaction.followup.send(
        f"✅ You've been verified, {member.mention}!",
        ephemeral=True)


@bot.tree.command(name="link")
async def link_discord(interaction: discord.Interaction, code: str):
    """Link your Discord account using a code"""
    code = code.strip().upper()
    doc = db_mgr.link_codes.find_one({"code": code})
    if not doc:
        return await interaction.response.send_message("Invalid or expired code.", ephemeral=True)
    if doc.get("claimed"):
        return await interaction.response.send_message("This code has already been used.", ephemeral=True)

    if doc.get("type") == "verify":
        return await _handle_verify(interaction, doc)

    db_mgr.link_codes.update_one({"_id": doc["_id"]}, {"$set": {
        "claimed": True, "discord_id": interaction.user.id,
        "discord_name": str(interaction.user),
        "claimed_ts": datetime.datetime.utcnow(),
    }})
    _log_ip_association(interaction.user.id, doc.get("ip", "unknown"), source="partner_link")
    await interaction.response.send_message(
        "✅ Linked! Your Discord account is now connected. Return to the partner page to continue.",
        ephemeral=True)


@bot.tree.command(name="alts")
async def alts(interaction: discord.Interaction, user: discord.Member):
    """Look up potential alt accounts by shared IP (staff only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission", ephemeral=True)
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)

    user_ips = db_mgr.alt_logs.distinct("ip", {"discord_id": user.id})
    if not user_ips:
        return await interaction.response.send_message(f"No IP data recorded for {user.mention}.", ephemeral=True)

    alts_raw = list(db_mgr.alt_logs.find({"ip": {"$in": user_ips}, "discord_id": {"$ne": user.id}}))
    alt_map = {}
    for entry in alts_raw:
        did = entry["discord_id"]
        if did not in alt_map:
            alt_map[did] = {"ips": set(), "sources": set(), "ts": entry.get("ts")}
        alt_map[did]["ips"].add(entry["ip"])
        if entry.get("source"):
            alt_map[did]["sources"].add(entry["source"])
        if entry.get("ts") and (not alt_map[did]["ts"] or entry["ts"] > alt_map[did]["ts"]):
            alt_map[did]["ts"] = entry["ts"]

    if not alt_map:
        return await interaction.response.send_message(f"No alt accounts found for {user.mention}.", ephemeral=True)

    embed = discord.Embed(
        title=f"Alt Detection — {user.display_name}",
        description=f"**{len(alt_map)}** potential alt(s) sharing **{len(user_ips)}** IP(s)",
        color=0xff4500,
    )

    total_ips_used = len(user_ips)
    embed.add_field(name="IPs Used", value="\n".join(user_ips[:10]) + (f"\n+{total_ips_used - 10} more" if total_ips_used > 10 else ""), inline=False)

    for did, data in sorted(alt_map.items(), key=lambda x: x[1]["ts"] or datetime.datetime.min, reverse=True)[:10]:
        member = interaction.guild.get_member(did)
        label = f"{member.mention} ({member})" if member else f"<@{did}>"
        ts_str = data["ts"].strftime("%Y-%m-%d") if isinstance(data["ts"], datetime.datetime) else ""
        src_str = ", ".join(data["sources"]) if data["sources"] else "unknown"
        value = f"IPs: {', '.join(list(data['ips'])[:3])}\nSource: {src_str}"
        if ts_str:
            value += f"\nLast: {ts_str}"
        embed.add_field(name=label, value=value, inline=False)

    if len(alt_map) > 10:
        embed.set_footer(text=f"+ {len(alt_map) - 10} more alts not shown")

    await interaction.response.send_message(embed=embed, ephemeral=True)









# --- WEB UI ---
app = Flask(__name__)

@app.route('/')
def home():
    if is_web_offline():
        return "<html><head><title>MagmaTIERS</title></head><body style='font-family:Arial;background:#0b0c10;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;'><h1>Website is offline by admin.</h1></body></html>", 503
    maint = is_maintenance_active()

    if maint.get('active'):
        return f"<html><head><style>body{{background:#0b0c10;color:#f0f2f5;font-family:Arial,sans-serif;}}h1{{color:#ff4500;}}</style></head><body style='display:flex;justify-content:center;align-items:center;height:100vh;'><div class='container' style='text-align:center;'><h1>🛠️ {maint.get('reason')}</h1></div></body></html>"

    mode_q = normalize_mode(request.args.get('mode', ''))
    search_q = request.args.get('search', '').lower()

    raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    users = {}

    for r in raw:
        u = r['username']
        n_mode = normalize_mode(r.get('gamemode'))
        n_tier = normalize_tier(r.get('tier'))
        r['_normalized_gamemode'] = n_mode
        r['_normalized_tier'] = n_tier

        if u not in users:
            reg = r.get('region', 'NA').strip().upper()
            users[u] = {
                "u": u, "tiers": [], "kits": [], "reg": reg,
                "reg_c": REGION_COLORS.get(reg, "#fff"),
                "mode_tier": "N/A", "head_url": get_player_head_url(u, 32)
            }

        users[u]["kits"].append(r)

        if n_mode == mode_q and not r.get('retired'):
            cur = users[u].get("mode_tier")
            if cur == "N/A" or get_tier_value(n_tier) > get_tier_value(cur):
                users[u]["mode_tier"] = n_tier

        if not r.get('retired'):
            users[u]["tiers"].append(n_tier)

    top_mode_tiers = {}
    for data in users.values():
        for kit in data["kits"]:
            if kit.get("retired"): continue
            m_name = kit.get("_normalized_gamemode")
            if not m_name: continue
            t_val = get_tier_value(kit.get("_normalized_tier"))
            existing = top_mode_tiers.get(m_name)
            if existing is None or t_val > existing["tier_value"]:
                top_mode_tiers[m_name] = {"tier_value": t_val, "tier": kit.get("_normalized_tier")}

    processed = []
    spotlight = None

    for u, data in users.items():
        data["rank"], data["rank_c"] = get_rank_info(data["tiers"])
        data["score"] = sum(get_tier_value(t) for t in data["tiers"])
        data["best"] = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        if mode_q and data["mode_tier"] == "N/A": continue
        processed.append(data)

    players = sorted(
        processed,
        key=lambda x: (get_tier_value(x['mode_tier']), x['score']) if mode_q else x['score'],
        reverse=True
    )
    high_p = [p for p in players if p['rank'] in ["Grandmaster", "Legend", "Master"]]

    if search_q:
        for idx, p in enumerate(players, 1):
            if p['u'].lower() == search_q:
                spotlight = dict(p)
                spotlight.update({
                    "head_url": get_player_head_url(p['u'], 80),
                    "position": idx,
                    "position_label": mode_q.upper() if mode_q else "OVERALL",
                    "region_name": {
                        "NA": "North America", "EU": "Europe", "AS": "Asia",
                        "SA": "South America", "OC": "Oceania", "AF": "Africa"
                    }.get(p['reg'], p['reg']),
                    "placement_color": 'gold' if idx == 1 else 'silver' if idx == 2 else '#cd7f32' if idx == 3 else '#9ba3af'
                })

                # One entry per mode. peak_tier is persisted by /rank and never goes down.
                # Falls back to current tier for players ranked before this field existed.
                peak_by_mode = {}
                for kit_item in p.get("kits", []):
                    km = kit_item.get("_normalized_gamemode", "")
                    kt = kit_item.get("_normalized_tier", "")
                    if not km or not kt:
                        continue
                    if kit_item.get("retired", False):
                        continue
                    stored_peak = normalize_tier(kit_item.get("peak_tier") or kt)
                    kv = get_tier_value(kt)
                    if km not in peak_by_mode or kv > peak_by_mode[km]["tier_value"]:
                        peak_by_mode[km] = {
                            "gamemode": km,
                            "tier": kt,
                            "tier_value": kv,
                            "peak_tier": stored_peak,
                        }

                spotlight["kits"] = []
                for kit in peak_by_mode.values():
                    is_top = top_mode_tiers.get(kit["gamemode"], {}).get("tier_value", 0) == kit["tier_value"]
                    kit["peak_label"] = f"PEAK {kit['peak_tier']}"
                    kit["top_mode"] = is_top
                    spotlight["kits"].append(kit)
                break

    return render_template(
        "index.html", players=players, spot=spotlight, modes=MODES,
        m=mode_q, search=search_q, high_p=high_p,
        mode_icon_urls=GAMEMODE_ICON_URLS, default_icon_url=DEFAULT_GAMEMODE_ICON_URL,
    )

@app.route('/moderation')
def moderation():
    if is_web_offline():
        return "Website is offline by admin.", 503

    reps = list(db_mgr.reports.find({"status": "Pending"}))
    return render_template("moderation.html", reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_mgr.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect(url_for('moderation'))

@app.route('/partner', methods=['GET', 'POST'])
def partner():
    if is_web_offline() or is_partner_offline():
        return "Partner program is offline by admin.", 503
    if request.method == 'POST':
        ign = request.form.get('ign', '').strip()
        link_code = request.form.get('link_code', '').strip().upper()
        ptype = request.form.get('type', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        proof = request.form.get('proof', '').strip()
        ip_addr = request.remote_addr or "unknown"

        code_doc = db_mgr.link_codes.find_one({"code": link_code, "claimed": True})
        if not code_doc:
            return render_template("partner.html", submitted=False, error="Discord link required. Run /link in Discord first.")

        discord_id = code_doc.get("discord_id")
        discord_name = code_doc.get("discord_name", "Unknown#0000")

        existing = db_mgr.partners.find_one({"discord_id": discord_id, "status": "Pending Review"})
        if existing:
            return render_template("partner.html", submitted=False,
                error=f"You already have a pending application ({existing.get('title', 'Untitled')}). Please wait for staff to review it.")

        if not all([ign, ptype, title, description]):
            return render_template("partner.html", submitted=False, error="Please fill in all required fields.")

        sub = {
            "ign": ign, "discord_user": discord_name, "discord_id": discord_id,
            "link_code": link_code, "type": ptype,
            "title": title, "description": description, "proof": proof or None,
            "ip": ip_addr, "status": "pending",
            "ts": datetime.datetime.utcnow(),
        }
        result = db_mgr.partners.insert_one(sub)
        sub_id = str(result.inserted_id)

        try:
            embed = discord.Embed(title="New Partner Submission", color=0xff4500, timestamp=datetime.datetime.utcnow())
            embed.add_field(name="IGN", value=ign, inline=True)
            embed.add_field(name="Discord", value=discord_name, inline=True)
            embed.add_field(name="Type", value=ptype, inline=True)
            embed.add_field(name="Title", value=title, inline=False)
            embed.add_field(name="Description", value=description, inline=False)
            if proof:
                embed.add_field(name="Proof", value=proof, inline=False)
            embed.add_field(name="Submission ID", value=sub_id, inline=True)
            embed.add_field(name="Status", value="Pending Review", inline=True)

            channel = bot.get_channel(PARTNER_CHANNEL_ID)
            if channel:
                import asyncio
                future = asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
                msg = future.result(timeout=10)
                async def attach_view():
                    view = PartnerView(sub_id, PARTNER_CHANNEL_ID)
                    await msg.edit(view=view)
                asyncio.run_coroutine_threadsafe(attach_view(), bot.loop).result(timeout=10)
                db_mgr.partners.update_one({"_id": result.inserted_id}, {"$set": {"message_id": msg.id, "message_link": f"https://discord.com/channels/{msg.guild.id if msg.guild else 0}/{PARTNER_CHANNEL_ID}/{msg.id}"}})
        except Exception:
            pass

        return render_template("partner.html", submitted=True,
            sub_id=sub_id, status="Pending Review",
            submitted_at=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

    return render_template("partner.html", submitted=False)

@app.route('/api/link/generate', methods=['POST'])
def link_generate():
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    ip = request.remote_addr or "unknown"
    # Expire old codes for this IP
    db_mgr.link_codes.update_many({"ip": ip}, {"$set": {"expired": True}})
    db_mgr.link_codes.insert_one({
        "code": code, "ip": ip, "claimed": False,
        "discord_id": None, "discord_name": None,
        "ts": datetime.datetime.utcnow(),
    })
    return jsonify({"code": code})

@app.route('/api/link/check/<code>')
def link_check(code):
    code = code.strip().upper()
    doc = db_mgr.link_codes.find_one({"code": code})
    if not doc:
        return jsonify({"claimed": False, "error": "not_found"})
    if doc.get("claimed"):
        return jsonify({"claimed": True, "discord_name": doc.get("discord_name", "Unknown"), "discord_id": doc.get("discord_id")})
    return jsonify({"claimed": False})

@app.route('/api/partner/status/<discord_id>')
def partner_status(discord_id):
    try:
        did = int(discord_id)
    except (ValueError, TypeError):
        return jsonify({"notifications": []})
    subs = sorted(db_mgr.partners.find({"discord_id": did}), key=lambda x: x.get("ts") or datetime.datetime.min, reverse=True)[:5]
    notifs = []
    for s in subs:
        st = s.get("status", "pending")
        if st not in ("pending", "Pending Review"):
            notifs.append({
                "sub_id": str(s["_id"]),
                "title": s.get("title", ""),
                "status": st,
                "ts": s.get("ts").strftime("%Y-%m-%d %H:%M UTC") if s.get("ts") else "",
            })
    return jsonify({"notifications": notifs})

@app.route('/api/ads')
def partner_ads():
    ads = list(db_mgr.partners.find({"status": "Approved ✅"}))
    import random
    if not ads:
        return jsonify({"ad": None})
    ad = random.choice(ads)
    return jsonify({
        "ad": {
            "title": ad.get("title", ""),
            "description": ad.get("description", ""),
            "ign": ad.get("ign", ""),
            "type": ad.get("type", ""),
            "proof": ad.get("proof") or None,
        }
    })

@app.route('/verify')
def verify_page():
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    ip = request.remote_addr or "unknown"
    db_mgr.link_codes.update_many({"ip": ip, "type": "verify", "claimed": False}, {"$set": {"expired": True}})
    db_mgr.link_codes.insert_one({
        "code": code, "ip": ip, "type": "verify", "claimed": False,
        "discord_id": None, "discord_name": None,
        "ts": datetime.datetime.utcnow(),
    })
    return render_template("verify.html", code=code)

@app.route('/api/verify/generate', methods=['POST'])
def verify_generate():
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    ip = request.remote_addr or "unknown"
    db_mgr.link_codes.update_many({"ip": ip, "type": "verify", "claimed": False}, {"$set": {"expired": True}})
    db_mgr.link_codes.insert_one({
        "code": code, "ip": ip, "type": "verify", "claimed": False,
        "discord_id": None, "discord_name": None,
        "ts": datetime.datetime.utcnow(),
    })
    return jsonify({"code": code})

@app.route('/api/verify/check/<code>')
def verify_check(code):
    code = code.strip().upper()
    doc = db_mgr.link_codes.find_one({"code": code, "type": "verify"})
    if not doc:
        return jsonify({"claimed": False, "error": "not_found"})
    if doc.get("claimed"):
        return jsonify({"claimed": True, "discord_name": doc.get("discord_name", "Unknown"), "discord_id": doc.get("discord_id")})
    return jsonify({"claimed": False})

@app.route('/discord')
def discord_redirect():
    return redirect("https://dsc.gg/magmatiers")

@app.route('/old/status')
def status():
    maint = is_maintenance_active()

    # Discord bot status (best-effort): token presence + bot connection state if available.
    discord_ready = False
    try:
        discord_ready = bot.is_ready()
    except Exception:
        discord_ready = False

    return jsonify({
        "web": {"ok": True},
        "maintenance": maint.get('active', False),
        "maintenance_reason": maint.get('reason', '') if maint.get('active') else '',
        "discord_bot": {
            "token_present": bool(TOKEN),
            "ready": discord_ready
        },
        "database": {
            "configured": bool(MONGO_URI),
            "db_name": DB_NAME
        },
        "backups": {
            "enabled": bool(MONGO_URI),
            "dir": BACKUP_DIR
        }
    })


@app.route('/status')
def status_json():
    maint = is_maintenance_active()

    discord_ready = False
    try:
        discord_ready = bot.is_ready() and not is_bot_offline()
    except Exception:
        discord_ready = not is_bot_offline()

    web_ok = not is_web_offline()
    db_ok = bool(MONGO_URI) and not is_database_offline()
    backups_ok = bool(MONGO_URI)

    # maintenance revamp: show OFF/ON + estimated duration if available
    maint_active = bool(maint.get('active', False))

    maint_reason = maint.get('reason', '') if maint_active else ''

    # Attempt to estimate remaining time.
    # We expect an optional field in settings: {"_id":"maintenance_mode", "ends_at": <utc datetime iso>}
    # If missing, we display a generic message.
    ends_at = maint.get('ends_at')
    est_str = '—'
    if maint_active and ends_at:
        try:
            if isinstance(ends_at, datetime.datetime):
                ends_dt = ends_at
            else:
                ends_dt = datetime.datetime.fromisoformat(str(ends_at).replace('Z', '+00:00'))
            if ends_dt.tzinfo is None:
                ends_dt = ends_dt.replace(tzinfo=datetime.timezone.utc)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            delta = ends_dt - now_dt
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0:
                est_str = 'Ended'
            else:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                if hours > 0:
                    est_str = f'{hours}h {minutes}m'
                else:
                    est_str = f'{minutes}m'
        except Exception:
            est_str = 'Estimating…'
    elif maint_active:
        est_str = 'Unknown duration'

    # show online/offline instead of maintenance-only status
    bot_online = bool(discord_ready and TOKEN)

    return render_template("status.html", web_ok=web_ok, discord_ready=discord_ready, TOKEN=TOKEN,
        db_ok=db_ok, backups_ok=backups_ok, maint=maint, DB_NAME=DB_NAME, BACKUP_DIR=BACKUP_DIR)


@app.route('/queue-status')
def queue_status_page():
    waiting = []
    for rcode, rdata in tier_queue.regions.items():
        for entry in rdata["queue"]:
            waiting.append(entry)
    testers = []
    for rcode, rdata in tier_queue.regions.items():
        for uid in rdata["testers"]:
            testers.append({"discord_id": uid, "region": rcode})
    total_waiting = len(waiting)
    total_testers = len(testers)
    if total_testers > 0 and total_waiting > 0:
        eta = f"~{max(5, (total_waiting // total_testers) * 12)} min"
    elif total_waiting > 0:
        eta = "Waiting for testers..."
    else:
        eta = "No queue"
    region_data = {}
    for rcode, rdata in tier_queue.regions.items():
        region_data[rcode] = {
            "open": rdata["open"],
            "queue_count": len(rdata["queue"]),
            "tester_count": len(rdata["testers"]),
        }
    return render_template("queue_status.html", waiting=waiting, testers=testers, eta=eta, region_data=region_data)


@app.route('/heads')
def head_status():
    raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    seen = {}
    for r in raw:
        u = r["username"]
        if u not in seen:
            seen[u] = {
                "username": u,
                "head_url": get_player_head_url(u, 64),
                "region": r.get("region", "NA").strip().upper(),
                "tier": normalize_tier(r.get("tier")),
            }
    players = list(seen.values())[:100]
    player_count = len(players)
    return render_template("heads.html", players=players, player_count=player_count)

@app.route('/console')
def console_page():
    if is_web_offline():
        return "Website is offline by admin.", 503
    with console_logs_lock:
        logs = list(reversed(console_logs))
    return render_template("console.html", logs=logs)

@app.route('/api/console/logs')
def console_logs_api():
    with console_logs_lock:
        logs = list(reversed(console_logs))
    return jsonify(logs)

@app.route('/api/player/<username>/<mode>')
def get_player_tier(username, mode):
    n_mode = normalize_mode(mode)
    player = db_mgr.players.find_one({"username": username, "gamemode": n_mode, "banned": {"$ne": True}})
    if not player:
        return jsonify({"error": "Player or mode not found"}), 404
    tier = player.get("tier", "N/A")
    return jsonify({"username": username, "mode": n_mode, "tier": tier})

# --- RATE LIMITER ---
rate_limit_store = {}
rate_limit_lock = threading.Lock()

@app.before_request
def rate_limiter():
    ip = request.remote_addr or "unknown"
    now = datetime.datetime.utcnow().timestamp()
    with rate_limit_lock:
        window = rate_limit_store.get(ip, [])
        window = [t for t in window if now - t < 60]
        if len(window) >= 60:
            return "Too Many Requests", 429
        window.append(now)
        rate_limit_store[ip] = window

if __name__ == "__main__":
    # Start daily MongoDB backup loop.
    start_mongo_backup_loop()

    # Start Discord bot in a background thread so the Flask webserver can receive Render traffic.
    threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()

    # Render requires the app to listen on the PORT environment variable.
    port = int(os.getenv("PORT", "10000"))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
