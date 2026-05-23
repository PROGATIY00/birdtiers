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
    def __init__(self):
        self.regions = {}
        self.gamemodes = {}

    def setup(self):
        for rcode in REGION_ROLE_IDS:
            self.regions[rcode] = {
                "queue": [],
                "testers": [],
                "open": False,
                "queue_channel_id": REGION_QUEUE_CHANNELS.get(rcode),
                "ticket_category_id": REGION_TICKET_CATEGORIES.get(rcode),
                "ping_role_id": REGION_ROLE_IDS[rcode],
            }
        for gm in GAMEMODE_QUEUE_CHANNELS:
            self.gamemodes[gm] = {
                "channel_id": GAMEMODE_QUEUE_CHANNELS[gm],
                "message_id": None,
            }

    def add_user(self, region, user_id, ign="Unknown", gamemode=None):
        r = self.regions.get(region)
        if not r:
            return "Region not found"
        for entry in r["queue"]:
            if entry["user_id"] == user_id:
                return "You are already in the queue"
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

    def make_region_embed(self, region):
        r = self.regions.get(region)
        if not r or not r["open"]:
            embed = discord.Embed(title=f"{region} Queue", description="Queue is closed.", color=0x525768)
            return embed
        queue_lines = [f"{i+1}. <@{e['user_id']}> ({e['ign']})" + (f" [{e['gamemode']}]" if e['gamemode'] else "") for i, e in enumerate(r["queue"])]
        tester_lines = [f"{i+1}. <@{uid}>" for i, uid in enumerate(r["testers"])]
        embed = discord.Embed(title=f"{region} Queue", color=0xff4500)
        embed.add_field(name="In Queue", value="\n".join(queue_lines) or "None", inline=True)
        embed.add_field(name="Testers", value="\n".join(tester_lines) or "None", inline=True)
        embed.set_footer(text=f"{len(r['queue'])} waiting · {len(r['testers'])} testing")
        return embed

    def make_gamemode_embed(self, gamemode):
        total_waiting = 0
        total_testers = 0
        region_lines = []
        for rcode, rdata in self.regions.items():
            count = sum(1 for e in rdata["queue"] if e["gamemode"] == gamemode or not e["gamemode"])
            testers = len(rdata["testers"])
            region_lines.append(f"{rcode}: {count} waiting, {testers} testing")
            total_waiting += count
            total_testers += testers

        if total_testers > 0 and total_waiting > 0:
            est_min = max(5, (total_waiting // total_testers) * 12)
            eta = f"~{est_min} min"
        elif total_waiting > 0:
            eta = "Waiting for testers..."
        else:
            eta = "No queue"

        embed = discord.Embed(
            title=f"{gamemode} Queue",
            description=f"**Est. Wait: {eta}**\nClick Enter to join the queue.",
            color=0x5865F2,
        )
        embed.add_field(name="Queue by Region", value="\n".join(region_lines) or "None", inline=False)
        embed.set_footer(text=f"{total_waiting} total waiting · {total_testers} testers online")
        return embed

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
    uuid = resolve_uuid(username)
    identifier = uuid or username
    # Fastest option: use minotar without per-request cache busting.
    # Server-side refresh (every 15 minutes) updates the cached URLs.
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
        for q in db_mgr.queues.find({"message_id": {"$ne": None}, "status": {"$in": ["waiting", "claimed"]}}):
            status = q.get("status", "waiting")
            claimed_by = q.get("claimed_by")
            self.add_view(QueueView(status=status, claimed_by=claimed_by), message_id=q["message_id"])
        status_doc = db_mgr.settings.find_one({"_id": "queue_status_msg"})
        if status_doc and status_doc.get("message_id"):
            self.add_view(JoinQueueView(), message_id=status_doc["message_id"])
        for p in db_mgr.partners.find({"message_id": {"$ne": None}, "status": "Pending Review"}):
            try:
                self.add_view(PartnerView(str(p["_id"]), PARTNER_CHANNEL_ID), message_id=p["message_id"])
            except Exception:
                pass
        self.add_view(EnterQueueView())
        self.add_view(VerifyIGNView())
        refresh_queue_status.start()
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

@bot.tree.command(name="gamemoderoles", description="Select your gamemode roles!")
async def gamemoderoles(interaction: discord.Interaction):
    """Send a message with all gamemodes to select roles."""
    embed = discord.Embed(title="Select Your Gamemode Roles", description="Choose one or more gamemodes from the dropdown to add/remove roles.", color=0x5865F2)
    for gm, role_id in GAMEMODE_ROLE_IDS.items():
        role_mention = f"<@&{role_id}>"
        embed.add_field(name=gm, value=role_mention, inline=True)
    await interaction.response.send_message(embed=embed, view=GamemodeRoleDropdownView(), ephemeral=True)

@tasks.loop(seconds=30)
async def refresh_queue_status():
    try:
        await _refresh_queue_channel(bot)
    except Exception:
        pass
    try:
        await _send_or_edit_status()
    except Exception:
        pass

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

@bot.tree.command(name="rank")
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str, reason: str):
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission", ephemeral=True)


    t_up = tier.upper().strip()
    existing = db_mgr.players.find_one({"username": player, "gamemode": mode})
    old_tier = existing.get("tier") if existing else None
    old_value = get_tier_value(old_tier) if old_tier else 0
    new_value = get_tier_value(t_up)

    status = "promoted" if new_value > old_value else "demoted" if new_value < old_value else "updated"

    # peak_tier only ever goes up — never replaced with a lower tier
    existing_peak = existing.get("peak_tier") if existing else None
    new_peak = t_up if (existing_peak is None or new_value > get_tier_value(existing_peak)) else existing_peak

    db_mgr.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {
            "tier": t_up,
            "peak_tier": new_peak,
            "region": region.upper(),
            "discord_id": discord_user.id,
            "tester": interaction.user.id,
            "retired": False,
            "banned": False,
            "ts": datetime.datetime.utcnow()
        }},
        upsert=True
    )

    await log_action(
        "TIER UPDATE",
        f"{discord_user.mention} {player} {status} to {t_up} {mode}",
        interaction,
        public=True,
        hide_action=True,
    )

    await interaction.response.send_message("Updated!", ephemeral=True)

@bot.tree.command(name="check")
async def check(interaction: discord.Interaction, player: str = None):
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)

    searched_by_discord = False

    if player is None:
        records = list(db_mgr.players.find({"discord_id": interaction.user.id, "banned": {"$ne": True}}))
        if not records:
            return await interaction.response.send_message("No tiers found for your account.", ephemeral=True)
        searched_by_discord = True
    elif player.isdigit():
        records = list(db_mgr.players.find({"discord_id": int(player), "banned": {"$ne": True}}))
        searched_by_discord = True
    else:
        records = list(db_mgr.players.find({"username": player, "banned": {"$ne": True}}))

    if not records:
        return await interaction.response.send_message(f"**{player}** not found.", ephemeral=True)

    # Fetch the Discord member if we have a discord_id
    linked_discord = None
    discord_id_val = records[0].get("discord_id")
    if discord_id_val:
        guild = interaction.guild
        if guild:
            try:
                linked_discord = await guild.fetch_member(discord_id_val)
            except:
                pass

    tiers = []
    regions = set()
    peak_tier = ""
    peak_value = 0
    mode_tiers = {}

    for r in records:
        if r.get("retired"):
            continue
        t = normalize_tier(r.get("tier"))
        tiers.append(t)
        regions.add(r.get("region", "NA").strip().upper())
        p = normalize_tier(r.get("peak_tier") or t)
        pv = get_tier_value(p)
        if pv > peak_value:
            peak_value = pv
            peak_tier = p
        gm = normalize_mode(r.get("gamemode"))
        tv = get_tier_value(t)
        if gm not in mode_tiers or tv > mode_tiers[gm]["value"]:
            mode_tiers[gm] = {"tier": t, "value": tv}

    if not tiers:
        return await interaction.response.send_message(f"**{player}** has no active tiers.", ephemeral=True)

    player_score = sum(get_tier_value(t) for t in tiers)
    rank_name, rank_color = get_rank_info(tiers)

    # Calculate global position
    all_raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    user_scores = {}
    for r in all_raw:
        if r.get("retired"):
            continue
        u = r["username"]
        ut = normalize_tier(r.get("tier"))
        if u not in user_scores:
            user_scores[u] = 0
        user_scores[u] += get_tier_value(ut)

    sorted_players = sorted(user_scores.items(), key=lambda x: -x[1])
    usernames = list(dict.fromkeys(r["username"] for r in records))
    main_username = usernames[0]
    position = next((i + 1 for i, (u, _) in enumerate(sorted_players) if u.lower() == main_username.lower()), None)

    region = ", ".join(sorted(regions)) if regions else "N/A"
    best_mode = max(mode_tiers, key=lambda m: mode_tiers[m]["value"]) if mode_tiers else "N/A"
    best_tier = mode_tiers[best_mode]["tier"] if best_mode != "N/A" else "N/A"

    title = main_username
    if linked_discord:
        title += f" ({linked_discord})"
    elif searched_by_discord:
        title += " (Unknown Discord)"

    embed = discord.Embed(title=title, color=discord.Color(int(rank_color.replace("#", ""), 16)))
    position_str = f"#{position}" if position else "Unranked"
    embed.add_field(name="Global Position", value=position_str, inline=True)
    embed.add_field(name="Peak Tier", value=peak_tier or "N/A", inline=True)
    embed.add_field(name="Region", value=region, inline=True)
    embed.add_field(name=f"Best Tier ({best_mode})", value=best_tier, inline=True)

    if len(usernames) > 1:
        embed.add_field(name="Usernames", value="\n".join(usernames), inline=False)

    modes_list = "\n".join(f"{m}: {d['tier']}" for m, d in sorted(mode_tiers.items(), key=lambda x: -x[1]["value"]))
    embed.add_field(name="All Modes", value=modes_list or "N/A", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="control")
async def control(interaction: discord.Interaction, player: str):
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)

    records = list(db_mgr.players.find({"username": player, "banned": {"$ne": True}}))
    if not records:
        return await interaction.response.send_message(f"**{player}** not found.", ephemeral=True)

    lines = []
    for r in records:
        if r.get("retired"):
            continue
        gm = r.get("gamemode", "?")
        tier = r.get("tier", "?")
        tester_id = r.get("tester")
        ts = r.get("ts")
        tester_str = f"<@{tester_id}>" if tester_id else "Unknown"
        time_str = ts.strftime("%Y-%m-%d") if isinstance(ts, datetime.datetime) else "?"
        lines.append(f"{gm}: **{tier}** — tested by {tester_str} ({time_str})")

    if not lines:
        return await interaction.response.send_message(f"**{player}** has no active records.", ephemeral=True)

    embed = discord.Embed(title=f"Control — {player}", color=0xff4500)
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="maintenance")
async def maintenance(interaction: discord.Interaction, action: str, reason: str = None):
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)
    if not interaction.user.guild_permissions.manage_roles:
        return


    action_lower = action.lower()
    if action_lower == "on":
        db_mgr.settings.update_one(
            {"_id": "maintenance_mode"},
            {"$set": {"active": True, "reason": reason or "Maintenance in progress"}},
            upsert=True
        )
        await interaction.response.send_message("Maintenance mode enabled", ephemeral=True)
    elif action_lower == "off":
        db_mgr.settings.update_one(
            {"_id": "maintenance_mode"},
            {"$set": {"active": False}},
            upsert=True
        )
        await interaction.response.send_message("Maintenance mode disabled", ephemeral=True)
    else:
        await interaction.response.send_message("Use 'on' or 'off' for action", ephemeral=True)

@bot.tree.command(name="retire")
async def retire(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles: return
    result = db_mgr.players.update_many(
        {"username": player},
        {"$set": {"retired": True, "ts": datetime.datetime.utcnow()}}
    )
    msg = f"Retired {player}" if result.modified_count > 0 else f"Player {player} not found"
    await log_action("RETIRE", f"Player: {player}\nResult: {'Retired' if result.modified_count > 0 else 'Not found'}", interaction)
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles: return
    result = db_mgr.players.update_many(
        {"username": player},
        {"$set": {"banned": True, "ts": datetime.datetime.utcnow()}}
    )
    msg = f"Banned {player}" if result.modified_count > 0 else f"Player {player} not found"
    await log_action("BAN", f"Player: {player}\nResult: {'Banned' if result.modified_count > 0 else 'Not found'}", interaction)
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="fail")
async def fail(interaction: discord.Interaction, player: str, tier: str, mode: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission", ephemeral=True)
    await log_action(
        "FAIL",
        f"**{player}** failed {tier.upper().strip()} {mode}",
        interaction,
        public=True,
        hide_action=True,
    )
    await interaction.response.send_message("Logged!", ephemeral=True)

# --- QUEUE SYSTEM ---
def _get_tester_profiles():
    return list(db_mgr.tester_profiles.find({"online": True}))

def _build_entry_embed(n_mode, player, region_u, queued_by, server=None):
    embed = discord.Embed(title=n_mode, color=0xff4500)
    embed.add_field(name="Player", value=player, inline=True)
    embed.add_field(name="Region", value=region_u, inline=True)
    embed.add_field(name="Queued By", value=queued_by, inline=True)
    if server:
        embed.add_field(name="Recommended Server", value=server, inline=True)
    embed.set_footer(text="1 in queue")
    return embed


class ClaimModal(discord.ui.Modal, title="Claim Queue"):
    def __init__(self, queue_entry):
        super().__init__()
        self.queue_entry = queue_entry
        self.server = discord.ui.TextInput(label="Recommended Server", placeholder="e.g. 0.0.0.0:25565", required=True, max_length=100)
        self.add_item(self.server)
        self.add_item(discord.ui.TextInput(label="Gamemode", default=queue_entry["gamemode"], required=True, max_length=20))
        self.add_item(discord.ui.TextInput(label="Region", default=queue_entry["region"], required=True, max_length=5))

    async def on_submit(self, interaction: discord.Interaction):
        server = self.children[0].value
        gamemode = self.children[1].value
        region = self.children[2].value
        q = self.queue_entry
        db_mgr.queues.update_one({"_id": q["_id"]}, {"$set": {"status": "claimed", "claimed_by": interaction.user.id}})

        player_doc = db_mgr.players.find_one({"username": q["username"]})
        dm_ok = False
        if player_doc and player_doc.get("discord_id"):
            try:
                member = interaction.guild.get_member(player_doc["discord_id"]) if interaction.guild else None
                if member:
                    dm_embed = discord.Embed(title="Your queue has been claimed!", color=0x34d399)
                    dm_embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
                    dm_embed.add_field(name="Gamemode", value=gamemode, inline=True)
                    dm_embed.add_field(name="Region", value=region, inline=True)
                    dm_embed.add_field(name="Server", value=server, inline=False)
                    await member.send(embed=dm_embed)
                    dm_ok = True
            except discord.Forbidden:
                pass
            except Exception:
                pass

        embed = interaction.message.embeds[0]
        embed.color = 0x34d399
        embed.clear_fields()
        embed.add_field(name="Player", value=q["username"], inline=True)
        embed.add_field(name="Gamemode", value=gamemode, inline=True)
        embed.add_field(name="Region", value=region, inline=True)
        embed.add_field(name="Server", value=server, inline=True)
        embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
        embed.add_field(name="Status", value="Claimed ✅", inline=True)
        embed.set_footer(text=f"Claimed by {interaction.user}")
        new_view = QueueView(status="claimed", claimed_by=interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=new_view)

        try:
            category = interaction.guild.get_channel(PARTNER_CATEGORY_ID) if interaction.guild else None
            if category and isinstance(category, discord.CategoryChannel):
                player_discord_id = None
                if player_doc and player_doc.get("discord_id"):
                    player_discord_id = player_doc["discord_id"]
                elif q.get("discord_id"):
                    player_discord_id = q["discord_id"]
                player_member = interaction.guild.get_member(player_discord_id) if player_discord_id else None
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                }
                if player_member:
                    overwrites[player_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                overwrites[interaction.user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                safe_name = q["username"].replace(" ", "-").lower()[:20]
                chan = await category.create_text_channel(f"test-{safe_name}-{gamemode.lower()[:5]}", overwrites=overwrites)
                await chan.send(
                    f"**Test Session**\nPlayer: {q['username']} {player_member.mention if player_member else ''}\n"
                    f"Tester: {interaction.user.mention}\nGamemode: {gamemode}\nRegion: {region}\nServer: {server}"
                )
                db_mgr.queues.update_one({"_id": q["_id"]}, {"$set": {"test_channel_id": chan.id}})
        except Exception:
            pass

        await _refresh_queue_channel(interaction.client)
        try:
            await _send_or_edit_status()
        except Exception:
            pass
        notif = interaction.client.get_channel(TESTER_NOTIF_CHANNEL_ID)
        if notif:
            n_embed = discord.Embed(title="Claimed", color=0x34d399)
            n_embed.add_field(name="Player", value=q["username"], inline=True)
            n_embed.add_field(name="Gamemode", value=gamemode, inline=True)
            n_embed.add_field(name="Region", value=region, inline=True)
            n_embed.add_field(name="Server", value=server, inline=True)
            n_embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
            await notif.send(embed=n_embed)

        msg = f"Claimed **{q['username']}** for {gamemode} on {server}."
        if not dm_ok:
            msg += " ⚠️ Could not DM the player (DMs closed or no Discord linked)."
        await interaction.followup.send(msg, ephemeral=True)


class QueueView(discord.ui.View):
    def __init__(self, status="waiting", claimed_by=None):
        super().__init__(timeout=None)
        for child in self.children:
            if child.custom_id == "queue_claim":
                child.disabled = (status != "waiting")
            elif child.custom_id == "queue_tier":
                child.disabled = (status != "claimed")
            elif child.custom_id == "queue_done":
                child.disabled = (status != "claimed")

    @discord.ui.button(label="Claim Queue", style=discord.ButtonStyle.primary, custom_id="queue_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = db_mgr.queues.find_one({"message_id": interaction.message.id, "channel_id": interaction.channel_id})
        if not q or q["status"] != "waiting":
            return await interaction.response.send_message("Already claimed or not found.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_modal(ClaimModal(q))

    @discord.ui.button(label="Tier", style=discord.ButtonStyle.secondary, custom_id="queue_tier")
    async def tier(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = db_mgr.queues.find_one({"message_id": interaction.message.id, "channel_id": interaction.channel_id})
        if not q or q["status"] != "claimed":
            return await interaction.response.send_message("Claim the queue first.", ephemeral=True)
        await interaction.response.send_modal(TierModal(q))

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="queue_done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = db_mgr.queues.find_one({"message_id": interaction.message.id, "channel_id": interaction.channel_id})
        if not q or q["status"] != "claimed":
            return await interaction.response.send_message("Not in claimed state.", ephemeral=True)
        if interaction.user.id != q.get("claimed_by") and not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("Only the claiming tester can mark as done.", ephemeral=True)
        db_mgr.queues.update_one({"_id": q["_id"]}, {"$set": {"status": "completed"}})
        embed = interaction.message.embeds[0]
        embed.color = 0x6b7280
        embed.clear_fields()
        embed.add_field(name="Player", value=q["username"], inline=True)
        embed.add_field(name="Gamemode", value=q["gamemode"], inline=True)
        embed.add_field(name="Region", value=q["region"], inline=True)
        embed.add_field(name="Tester", value=f"<@{q['claimed_by']}>", inline=True)
        embed.add_field(name="Status", value="Completed ✅", inline=True)
        embed.set_footer(text="")
        new_view = QueueView(status="completed")
        for child in new_view.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=new_view)
        await _refresh_queue_channel(interaction.client)
        try:
            await _send_or_edit_status()
        except Exception:
            pass

    @discord.ui.button(label="More Info", style=discord.ButtonStyle.secondary, custom_id="queue_info")
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = db_mgr.queues.find_one({"message_id": interaction.message.id, "channel_id": interaction.channel_id})
        if not q:
            return await interaction.response.send_message("Queue entry not found.", ephemeral=True)
        player = q["username"]
        records = list(db_mgr.players.find({"username": player, "banned": {"$ne": True}}))
        if not records:
            return await interaction.response.send_message(f"No tier data for **{player}**.", ephemeral=True)
        tiers, regions, peak_tier, peak_value, mode_tiers = [], set(), "", 0, {}
        for r in records:
            if r.get("retired"): continue
            t = normalize_tier(r.get("tier"))
            tiers.append(t); regions.add(r.get("region", "NA").strip().upper())
            p = normalize_tier(r.get("peak_tier") or t)
            pv = get_tier_value(p)
            if pv > peak_value: peak_value, peak_tier = pv, p
            gm = normalize_mode(r.get("gamemode")); tv = get_tier_value(t)
            if gm not in mode_tiers or tv > mode_tiers[gm]["value"]:
                mode_tiers[gm] = {"tier": t, "value": tv}
        rank_name, rank_color = get_rank_info(tiers)
        e = discord.Embed(title=f"Info — {player}", color=discord.Color(int(rank_color.replace("#", ""), 16)))
        e.add_field(name="Rank", value=rank_name, inline=True)
        e.add_field(name="Peak Tier", value=peak_tier or "N/A", inline=True)
        e.add_field(name="Region", value=", ".join(sorted(regions)) or "N/A", inline=True)
        modes_list = "\n".join(f"{m}: {d['tier']}" for m, d in sorted(mode_tiers.items(), key=lambda x: -x[1]["value"]))
        e.add_field(name="Tiers", value=modes_list or "N/A", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


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
        db_mgr.players.update_one(
            {"discord_id": interaction.user.id},
            {"$set": {
                "username": ign,
                "discord_id": interaction.user.id,
                "ts": datetime.datetime.utcnow(),
            }},
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

        detected_region = None
        if interaction.guild and isinstance(interaction.user, discord.Member):
            for rcode, rid in REGION_ROLE_IDS.items():
                role = interaction.guild.get_role(rid)
                if role and role in interaction.user.roles:
                    detected_region = rcode
                    break

        player_doc = db_mgr.players.find_one({"discord_id": interaction.user.id})
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
async def next_in_queue(interaction: discord.Interaction, region: str):
    """Claim the next player from the queue and create a ticket channel (staff only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    region_u = region.upper().strip()
    if region_u not in REGION_ROLE_IDS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_ROLE_IDS.keys())}", ephemeral=True)

    rdata = tier_queue.regions.get(region_u)
    if not rdata or not rdata["open"]:
        return await interaction.response.send_message(f"The {region_u} queue is not open.", ephemeral=True)
    if interaction.user.id not in rdata["testers"]:
        return await interaction.response.send_message("You must be a tester for this region to claim the next user. Use /openqueue first.", ephemeral=True)

    entry = tier_queue.next_user(region_u)
    if not entry:
        return await interaction.response.send_message(f"No users in the {region_u} queue.", ephemeral=True)

    user_id = entry["user_id"]
    player_name = entry.get("ign", "Unknown")
    player_mention = f"<@{user_id}>"
    tester_mention = interaction.user.mention
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


def _update_queue_channel():
    testers = _get_tester_profiles()
    waiting = sorted(db_mgr.queues.find({"status": "waiting"}), key=lambda x: x.get("ts") or datetime.datetime.min)

    embed = discord.Embed(title="Magmatiers Testing Queue", color=0xff4500)
    for mode in MODES:
        online = [t for t in testers if mode in t.get("gamemodes", [])]
        if online:
            names = ", ".join(f"<@{t['discord_id']}>" for t in online)
            embed.add_field(name=f"\U0001f7e2 {mode}", value=names, inline=True)
        else:
            embed.add_field(name=f"\U0001f534 {mode}", value="No testers online", inline=True)

    lines = []
    for w in waiting[:10]:
        lines.append(f"• {w['username']} — {w['gamemode']} ({w['region']})")
    if len(waiting) > 10:
        lines.append(f"• +{len(waiting) - 10} more")
    if not lines:
        lines = ["• None"]

    embed.add_field(name=f"Waiting ({len(waiting)})", value="\n".join(lines), inline=True)

    if not testers:
        eta = "No testers available"
    elif not waiting:
        eta = "No queue"
    else:
        mins = max(5, (len(waiting) // max(len(testers), 1)) * 12)
        eta = f"~{mins} min"
    embed.add_field(name="Est. Wait", value=eta, inline=True)
    embed.set_footer(text=f"{len(testers)} tester{'s' if len(testers) != 1 else ''} online")
    return embed

async def _refresh_queue_channel(bot_client):
    try:
        q_embed = _update_queue_channel()
        channel = bot_client.get_channel(QUEUE_CHANNEL_ID)
        if not channel:
            return
        doc = db_mgr.settings.find_one({"_id": "queue_status_msg"})
        if doc and doc.get("message_id"):
            try:
                msg = await channel.fetch_message(doc["message_id"])
                await msg.edit(embed=q_embed)
                return
            except Exception:
                pass
        # Delete any old status messages and send fresh
        async for old in channel.history(limit=30):
            if old.author.id == bot_client.user.id and old.embeds and old.embeds[0].title == "Magmatiers Testing Queue":
                await old.delete()
        msg = await channel.send(embed=q_embed, view=JoinQueueView())
        db_mgr.settings.update_one({"_id": "queue_status_msg"}, {"$set": {"message_id": msg.id}}, upsert=True)
    except Exception:
        pass

def _update_status_channel():
    waiting = sorted(db_mgr.queues.find({"status": "waiting"}), key=lambda x: x.get("ts") or datetime.datetime.min)
    total = len(waiting)
    mode_counts = {}
    for q in waiting:
        mode_counts[q["gamemode"]] = mode_counts.get(q["gamemode"], 0) + 1
    modes_str = ", ".join(f"{gm}: {n}" for gm, n in sorted(mode_counts.items())) or "None"

    closed = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
    closed_modes = closed.get("modes", []) if closed else []

    lines = []
    for q in waiting[:15]:
        lines.append(f"• {q['username']} — {q['gamemode']} ({q['region']})")
    if len(waiting) > 15:
        lines.append(f"• +{len(waiting) - 15} more")
    if not lines:
        lines = ["• None"]

    testers = _get_tester_profiles()
    embed = discord.Embed(title="Queue Status", color=0xf59e0b)
    embed.add_field(name="Active Queues", value=modes_str, inline=True)
    embed.add_field(name="Total Waiting", value=str(total), inline=True)
    embed.add_field(name="Online Testers", value=str(len(testers)), inline=True)
    if closed_modes:
        embed.add_field(name="Closed", value=", ".join(closed_modes), inline=True)
    embed.add_field(name="Waiting List", value="\n".join(lines), inline=True)

    # Service status
    status_doc = db_mgr.settings.find_one({"_id": "offline_mode"})
    service_status = status_doc.get("services", {}) if status_doc else {}
    status_lines = []
    for service in ["web", "bot", "database", "partner"]:
        state = service_status.get(service, False)
        status_lines.append(f"{service.title()}: {'❌ Down' if state else '✅ Up'}")
    embed.add_field(name="Service Status", value="\n".join(status_lines), inline=False)

    embed.set_footer(text=f"Updated just now")
    return embed

async def _send_or_edit_status():
    embed = _update_status_channel()
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if not channel:
        return
    doc = db_mgr.settings.find_one({"_id": "status_msg_id"})
    if doc and doc.get("message_id"):
        try:
            msg = await channel.fetch_message(doc["message_id"])
            await msg.edit(embed=embed)
            return
        except Exception:
            pass
    msg = await channel.send(embed=embed)
    db_mgr.settings.update_one({"_id": "status_msg_id"}, {"$set": {"message_id": msg.id}}, upsert=True)



class JoinQueueModal(discord.ui.Modal, title="Join Queue"):
    def __init__(self):
        super().__init__()
        self.ign_input = discord.ui.TextInput(label="IGN", placeholder="Your Minecraft username", required=False, max_length=30)
        self.gamemode_input = discord.ui.TextInput(label="Gamemode", placeholder="e.g. Crystal, UHC, Pot", required=True, max_length=20)
        self.server_input = discord.ui.TextInput(label="Server IP (optional)", placeholder="e.g. 0.0.0.0:25565", required=False, max_length=100)
        self.add_item(self.ign_input)
        self.add_item(self.gamemode_input)
        self.add_item(self.server_input)

    @property
    def selected_gamemode(self):
        # Helper to get the selected gamemode (for dropdown pre-fill)
        return self.gamemode_input.default or self.gamemode_input.value

    async def on_submit(self, interaction: discord.Interaction):
        gamemode = self.gamemode_input.value.strip()
        server = self.server_input.value.strip() or None

        n_mode = normalize_mode(gamemode)
        if n_mode not in MODES:
            return await interaction.response.send_message(f"Invalid gamemode. Choose: {', '.join(MODES)}", ephemeral=True)
        if _is_gamemode_closed(n_mode):
            return await interaction.response.send_message(f"**{n_mode}** is currently closed in the queue.", ephemeral=True)

        cooldown = _check_queue_cooldown(interaction.user.id)
        if cooldown:
            return await interaction.response.send_message(f"You're already in queue for {cooldown}", ephemeral=True)

        # Detect region from roles
        region = None
        if interaction.guild and isinstance(interaction.user, discord.Member):
            for rcode, rid in REGION_ROLE_IDS.items():
                role = interaction.guild.get_role(rid)
                if role and role in interaction.user.roles:
                    region = rcode
                    break
        if not region:
            return await interaction.response.send_message(
                "You need a region role (EU, NA, AF, AS, OC) to queue. Ask a staff member to assign one.",
                ephemeral=True,
            )

        # Only ask for IGN if not tested before
        ign = self.ign_input.value.strip()
        player_doc = db_mgr.players.find_one({"discord_id": interaction.user.id})
        if not ign and player_doc:
            ign = player_doc.get("username", "")
        if not ign:
            return await interaction.response.send_message("IGN required (not found in your previous records)", ephemeral=True)

        # Block banned IGNs
        banned_doc = db_mgr.players.find_one({"username": ign, "banned": True})
        if banned_doc:
            return await interaction.response.send_message("This IGN is banned from queuing.", ephemeral=True)

        # Assign region role to user
        region_role_id = REGION_ROLE_IDS.get(region)
        if region_role_id:
            guild = interaction.guild
            if guild:
                region_role = guild.get_role(region_role_id)
                if region_role and region_role not in interaction.user.roles:
                    try:
                        await interaction.user.add_roles(region_role, reason="Queued for region")
                    except Exception:
                        pass

        # Assign gamemode role to user
        gamemode_role_id = GAMEMODE_ROLE_IDS.get(n_mode)
        if gamemode_role_id:
            guild = interaction.guild
            if guild:
                gm_role = guild.get_role(gamemode_role_id)
                if gm_role and gm_role not in interaction.user.roles:
                    try:
                        await interaction.user.add_roles(gm_role, reason="Queued for gamemode")
                    except Exception:
                        pass

        entry = {
            "username": ign, "discord_id": interaction.user.id,
            "gamemode": n_mode, "region": region,
            "status": "waiting", "claimed_by": None,
            "message_id": None, "channel_id": CLAIM_CHANNEL_ID,
            "ts": datetime.datetime.utcnow(),
        }
        queue_id = db_mgr.queues.insert_one(entry).inserted_id

        # Calculate queue position
        position = db_mgr.queues.count_documents({
            "gamemode": n_mode, "status": "waiting", "ts": {"$lt": entry["ts"]}
        }) + 1

        # Send queue entry with buttons to claim channel
        channel_id = GAMEMODE_REGION_CHANNEL_IDS.get((n_mode, region)) or CLAIM_CHANNEL_ID
        claim_channel = interaction.client.get_channel(channel_id)
        if claim_channel:
            entry_embed = _build_entry_embed(n_mode, ign, region, interaction.user.mention, server=server)
            view = QueueView(status="waiting")
            ping_str = f"<@&{gamemode_role_id}>" if gamemode_role_id else ""
            msg = await claim_channel.send(content=ping_str, embed=entry_embed, view=view)
            db_mgr.queues.update_one({"_id": queue_id}, {"$set": {"message_id": msg.id}})

        await _refresh_queue_channel(interaction.client)
        try:
            await _send_or_edit_status()
        except Exception:
            pass

        await interaction.response.send_message(
            f"Queued **{ign}** for {n_mode} ({region}). Position: **#{position}**" + (f"\nServer: {server}" if server else ""),
            ephemeral=True,
        )



# --- GAMEMODE DROPDOWN FOR QUEUE ---
class QueueGamemodeDropdown(discord.ui.Select):
    def __init__(self, closed_modes=None):
        closed_modes = closed_modes or []
        options = [
            discord.SelectOption(
                label=mode,
                value=mode,
                description=("Closed" if mode in closed_modes else None),
                default=False,
                emoji=None,
                ) for mode in MODES
        ]
        super().__init__(
            placeholder="Select gamemode...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="queue_gamemode_dropdown"
        )
        self.closed_modes = closed_modes

    async def callback(self, interaction: discord.Interaction):
        selected_mode = self.values[0]
        if selected_mode in self.closed_modes:
            await interaction.response.send_message(f"**{selected_mode}** is currently closed in the queue.", ephemeral=True)
            return
        # Open the modal with the selected gamemode pre-filled
        modal = JoinQueueModal()
        modal.gamemode_input.default = selected_mode
        await interaction.response.send_modal(modal)


class JoinQueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Get closed gamemodes from DB
        closed_doc = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
        closed_modes = closed_doc.get("modes", []) if closed_doc else []
        self.add_item(QueueGamemodeDropdown(closed_modes=closed_modes))
        # Add a disabled join button for visual clarity (not used for action)
        self.add_item(discord.ui.Button(
            label="Join Queue",
            style=discord.ButtonStyle.primary,
            custom_id="join_queue_disabled",
            disabled=True
        ))


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


@bot.tree.command(name="partner")
async def partner_cmd(interaction: discord.Interaction, action: str, submission_id: str):
    """Review partner submissions (staff only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    action = action.lower().strip()
    if action not in ("accept", "approve", "decline", "deny"):
        return await interaction.response.send_message("Use: accept or decline", ephemeral=True)
    doc = db_mgr.partners.find_one({"_id": ObjectId(submission_id)})
    if not doc:
        return await interaction.response.send_message("Submission not found.", ephemeral=True)
    new_status = "Approved ✅" if action in ("accept", "approve") else "Declined ❌"
    color = 0x34d399 if action in ("accept", "approve") else 0xf87171
    db_mgr.partners.update_one({"_id": ObjectId(submission_id)}, {"$set": {"status": new_status}})
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
                db_mgr.partners.update_one({"_id": ObjectId(submission_id)}, {"$set": {"channel_id": chan.id}})
        except Exception:
            pass
    await interaction.response.send_message(f"Submission **{submission_id}** → {new_status}", ephemeral=True)



@bot.tree.command(name="queue")
async def queue_cmd(interaction: discord.Interaction, player: str, gamemode: str, region: str):
    """Queue a player for testing (uses roles for region/gamemode)"""
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)
    n_mode = normalize_mode(gamemode)
    if n_mode not in MODES:
        return await interaction.response.send_message(f"Invalid gamemode. Choose: {', '.join(MODES)}", ephemeral=True)
    region_u = region.upper().strip()
    if region_u not in REGION_ROLE_IDS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_ROLE_IDS.keys())}", ephemeral=True)
    if _is_gamemode_closed(n_mode):
        return await interaction.response.send_message(f"**{n_mode}** is currently closed in the queue.", ephemeral=True)

    cooldown = _check_queue_cooldown(interaction.user.id)
    if cooldown:
        return await interaction.response.send_message(f"You're already in queue for {cooldown}", ephemeral=True)

    # Block banned IGNs
    banned_doc = db_mgr.players.find_one({"username": player, "banned": True})
    if banned_doc:
        return await interaction.response.send_message("This IGN is banned from queuing.", ephemeral=True)

    # Assign region role to user
    region_role_id = REGION_ROLE_IDS.get(region_u)
    if region_role_id:
        guild = interaction.guild
        if guild:
            region_role = guild.get_role(region_role_id)
            if region_role and region_role not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(region_role, reason="Queued for region")
                except Exception:
                    pass

    # Assign gamemode role to user (optional)
    gamemode_role_id = GAMEMODE_ROLE_IDS.get(n_mode)
    if gamemode_role_id:
        guild = interaction.guild
        if guild:
            gm_role = guild.get_role(gamemode_role_id)
            if gm_role and gm_role not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(gm_role, reason="Queued for gamemode")
                except Exception:
                    pass

    entry = {
        "username": player, "discord_id": interaction.user.id,
        "gamemode": n_mode, "region": region_u,
        "status": "waiting", "claimed_by": None,
        "message_id": None, "channel_id": CLAIM_CHANNEL_ID,
        "ts": datetime.datetime.utcnow(),
    }
    queue_id = db_mgr.queues.insert_one(entry).inserted_id

    # Send queue entry with buttons to claim channel
    channel_id = GAMEMODE_REGION_CHANNEL_IDS.get((n_mode, region_u)) or CLAIM_CHANNEL_ID
    claim_channel = bot.get_channel(channel_id)
    if claim_channel:
        entry_embed = _build_entry_embed(n_mode, player, region_u, interaction.user.mention)
        # Disable claim button if gamemode is closed
        closed_doc = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
        closed_modes = closed_doc.get("modes", []) if closed_doc else []
        view = QueueView(status="waiting" if n_mode not in closed_modes else "closed")
        ping_str = f"<@&{gamemode_role_id}>" if gamemode_role_id else ""
        msg = await claim_channel.send(content=ping_str, embed=entry_embed, view=view)
        db_mgr.queues.update_one({"_id": queue_id}, {"$set": {"message_id": msg.id}})

    await _refresh_queue_channel(bot)
    try:
        await _send_or_edit_status()
    except Exception:
        pass
    await interaction.response.send_message(f"Queued **{player}** for {n_mode} ({region_u}).", ephemeral=True)


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

    modes_str = ", ".join(parsed_list)
    embed = discord.Embed(title="You're now online!", color=0x34d399)
    embed.add_field(name="IGN", value=ign or "Not set", inline=True)
    embed.add_field(name="Region", value=region_u, inline=True)
    embed.add_field(name="Testing", value=modes_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await _refresh_queue_channel(interaction.client)


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
    embed = tier_queue.make_gamemode_embed(gamemode)
    chan_id = gdata["channel_id"]
    if not chan_id:
        return
    channel = bot.get_channel(chan_id)
    if not channel:
        return
    msg_id = gdata.get("message_id")
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
        await _refresh_queue_channel(interaction.client)
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

    await _refresh_queue_channel(interaction.client)


def _check_queue_cooldown(discord_id):
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    entry = db_mgr.queues.find_one({
        "discord_id": discord_id,
        "status": {"$in": ["waiting", "claimed"]},
        "ts": {"$gte": cutoff}
    })
    if entry:
        remaining = (entry["ts"] + datetime.timedelta(hours=3)) - datetime.datetime.utcnow()
        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
        minutes = remainder // 60
        return f"**{entry['gamemode']}** — try again in {hours}h {minutes}m"
    return None

def _is_gamemode_closed(gamemode):
    doc = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
    return gamemode in doc.get("modes", []) if doc else False


@bot.tree.command(name="close")
async def close_gamemode(interaction: discord.Interaction, gamemode: str):
    """Close a gamemode from the queue (manage_roles only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    n_mode = normalize_mode(gamemode)
    if n_mode not in MODES:
        return await interaction.response.send_message(f"Invalid gamemode. Choose: {', '.join(MODES)}", ephemeral=True)

    doc = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
    closed = set(doc.get("modes", [])) if doc else set()
    if n_mode in closed:
        return await interaction.response.send_message(f"**{n_mode}** is already closed.", ephemeral=True)
    closed.add(n_mode)
    db_mgr.settings.update_one(
        {"_id": "closed_gamemodes"},
        {"$set": {"modes": list(closed)}},
        upsert=True,
    )

    removed = db_mgr.queues.delete_many({"gamemode": n_mode, "status": "waiting"})
    await log_action("QUEUE CLOSE", f"Closed **{n_mode}** (removed {removed.deleted_count} waiting entries)", interaction)
    await interaction.response.send_message(f"Closed **{n_mode}** from queue. Removed {removed.deleted_count} pending entries.", ephemeral=True)
    await _refresh_queue_channel(bot)

@bot.tree.command(name="open")
async def open_gamemode(interaction: discord.Interaction, gamemode: str):
    """Re-open a gamemode in the queue (manage_roles only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    n_mode = normalize_mode(gamemode)
    doc = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
    closed = set(doc.get("modes", [])) if doc else set()
    if n_mode not in closed:
        return await interaction.response.send_message(f"**{n_mode}** is not closed.", ephemeral=True)
    closed.discard(n_mode)
    db_mgr.settings.update_one(
        {"_id": "closed_gamemodes"},
        {"$set": {"modes": list(closed)}},
        upsert=True,
    )
    await log_action("QUEUE OPEN", f"Re-opened **{n_mode}** in queue", interaction)
    await interaction.response.send_message(f"Re-opened **{n_mode}** in queue.", ephemeral=True)
    await _refresh_queue_channel(bot)


@bot.tree.command(name="resetqueue")
async def resetqueue(interaction: discord.Interaction, user: discord.Member):
    """Reset queue cooldown for a user (manage_roles only)"""
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    result = db_mgr.queues.delete_many({
        "discord_id": user.id,
        "status": {"$in": ["waiting", "claimed"]},
        "ts": {"$gte": cutoff}
    })
    if result.deleted_count == 0:
        return await interaction.response.send_message(f"**{user.display_name}** has no active queue entries.", ephemeral=True)
    await _refresh_queue_channel(bot)
    await interaction.response.send_message(f"Reset queue for **{user.display_name}** (removed {result.deleted_count} entries).", ephemeral=True)


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


async def _create_automod_rule(guild_id, name, keyword_filter):
    from discord.http import Route
    route = Route("POST", "/guilds/{guild_id}/auto-moderation/rules", guild_id=guild_id)
    data = {
        "name": name,
        "event_type": 1,
        "trigger_type": 1,
        "trigger_metadata": {"keyword_filter": keyword_filter},
        "actions": [{"type": 1, "metadata": {}}],
        "enabled": True,
    }
    return await bot.http.request(route, json=data)

async def _delete_automod_rule(guild_id, rule_id):
    from discord.http import Route
    route = Route("DELETE", "/guilds/{guild_id}/auto-moderation/rules/{rule_id}", guild_id=guild_id, rule_id=rule_id)
    return await bot.http.request(route)

@bot.tree.command(name="busy")
async def busy(interaction: discord.Interaction):
    user = interaction.user
    guild = interaction.guild
    key = f"busy_rule_{user.id}"

    existing = db_mgr.settings.find_one({"_id": key})
    if existing:
        try:
            await _delete_automod_rule(guild.id, existing["rule_id"])
        except Exception:
            pass
        db_mgr.settings.delete_one({"_id": key})
        await interaction.response.send_message("Busy mode disabled.", ephemeral=True)
    else:
        try:
            result = await _create_automod_rule(
                guild.id,
                f"Busy - {user.display_name}",
                [f"<@{user.id}>", f"<@!{user.id}>"],
            )
            db_mgr.settings.update_one(
                {"_id": key},
                {"$set": {"rule_id": result["id"], "user_id": user.id}},
                upsert=True,
            )
            await interaction.response.send_message("Busy mode enabled. Pings to you will be blocked.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to enable busy mode: {e}", ephemeral=True)

@bot.tree.command(name="svc")
async def service_toggle(
    interaction: discord.Interaction,
    service: str,
    state: str,
    reason: str = None,
):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission", ephemeral=True)

    service_l = (service or "").lower().strip()
    state_l = (state or "").lower().strip()

    service_map = {
        "web": "web",
        "site": "web",
        "bot": "bot",
        "discord": "bot",
        "database": "database",
        "db": "database",
        "partner": "partner",
        "partners": "partner",
    }

    if service_l not in service_map:
        return await interaction.response.send_message(
            "Invalid service. Use one of: web, bot, database, partner",
            ephemeral=True,
        )

    if state_l not in ["on", "off", "true", "false", "1", "0"]:
        return await interaction.response.send_message(
            "Invalid state. Use: on/off",
            ephemeral=True,
        )

    turn_off = state_l in ["on", "true", "1"]

    try:
        db_mgr.settings.update_one(
            {"_id": "offline_mode"},
            {
                "$set": {
                    f"services.{service_map[service_l]}": bool(turn_off),
                    "reason": (reason or "")[:500],
                    "ts": datetime.datetime.utcnow(),
                }
            },
            upsert=True,
        )
    except Exception as e:
        return await interaction.response.send_message(f"Failed: {e}", ephemeral=True)

    human_state = "OFFLINE" if turn_off else "ONLINE"
    return await interaction.response.send_message(
        f"Set {service_map[service_l]} to {human_state}.",
        ephemeral=True,
    )


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
    waiting = list(db_mgr.queues.find({"status": "waiting"}))
    testers = _get_tester_profiles()
    try:
        q_embed = _update_queue_channel()
        embed_data = {"title": q_embed.title, "fields": [{"name": f.name, "value": f.value} for f in q_embed.fields], "footer": q_embed.footer.text if q_embed.footer else ""}
    except Exception:
        embed_data = None
    return render_template("queue_status.html", waiting=waiting, testers=testers, embed=embed_data)


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
