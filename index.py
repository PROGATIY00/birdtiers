import asyncio
import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask, render_template, request, redirect, url_for, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import threading
import datetime
import subprocess
import shutil


# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID")) if os.getenv("LOG_CHANNEL_ID") else None
TIER_LOG_CHANNEL_ID = 1502966105940164638
QUEUE_CHANNEL_ID = 1497963555541225472
STATUS_CHANNEL_ID = 1497989003721310249
TESTER_NOTIF_CHANNEL_ID = 1504206348324311131
CLAIM_CHANNEL_ID = 1504206348324311131
PARTNER_CHANNEL_ID = 1502975682513473787
PARTNER_CATEGORY_ID = 1498359340065624165


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
    def update_one(self, *args, **kwargs): return None
    def update_many(self, *args, **kwargs): return type('obj', (object,), {'modified_count': 0})

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
        else:
            self.players = DummyCollection()
            self.settings = DummyCollection()
            self.reports = DummyCollection()
            self.console_messages = DummyCollection()
            self.queues = DummyCollection()
            self.tester_profiles = DummyCollection()
            self.partners = DummyCollection()
            self.link_codes = DummyCollection()

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

    # Public channel (LOG_CHANNEL_ID) — only when requested
    if public and LOG_CHANNEL_ID and LOG_CHANNEL_ID != TIER_LOG_CHANNEL_ID:
        pub_channel = bot.get_channel(LOG_CHANNEL_ID)
        pub_msg = f"{prefix}{details_s}"
        try:
            if pub_channel:
                await pub_channel.send(pub_msg)
        except Exception as e:
            print(f"[log_action] Failed to send public log: {e}")

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
        refresh_queue_status.start()

bot = MagmaBot()

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
        self.add_item(discord.ui.TextInput(label="IGN", placeholder="Your Minecraft username", required=True, max_length=30))
        self.add_item(discord.ui.TextInput(label="Gamemode", placeholder="e.g. Crystal, UHC, Pot", required=True, max_length=20))
        self.add_item(discord.ui.TextInput(label="Region", placeholder="NA, EU, AS, SA, OC, AF", required=True, max_length=5))
        self.add_item(discord.ui.TextInput(label="Recommended Server", placeholder="e.g. 0.0.0.0:25565", required=True, max_length=100))

    async def on_submit(self, interaction: discord.Interaction):
        ign = self.children[0].value.strip()
        gamemode = self.children[1].value.strip()
        region = self.children[2].value.strip().upper()
        server = self.children[3].value.strip()

        n_mode = normalize_mode(gamemode)
        if n_mode not in MODES:
            return await interaction.response.send_message(f"Invalid gamemode. Choose: {', '.join(MODES)}", ephemeral=True)
        if region not in REGION_COLORS:
            return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_COLORS.keys())}", ephemeral=True)
        if _is_gamemode_closed(n_mode):
            return await interaction.response.send_message(f"**{n_mode}** is currently closed in the queue.", ephemeral=True)

        cooldown = _check_queue_cooldown(interaction.user.id)
        if cooldown:
            return await interaction.response.send_message(f"You're already in queue for {cooldown}", ephemeral=True)

        entry = {
            "username": ign, "discord_id": interaction.user.id,
            "gamemode": n_mode, "region": region,
            "status": "waiting", "claimed_by": None,
            "message_id": None, "channel_id": CLAIM_CHANNEL_ID,
            "ts": datetime.datetime.utcnow(),
        }
        queue_id = db_mgr.queues.insert_one(entry).inserted_id

        # Send queue entry with buttons to claim channel
        claim_channel = interaction.client.get_channel(CLAIM_CHANNEL_ID)
        if claim_channel:
            entry_embed = _build_entry_embed(n_mode, ign, region, interaction.user.mention, server=server)
            view = QueueView(status="waiting")
            msg = await claim_channel.send(embed=entry_embed, view=view)
            db_mgr.queues.update_one({"_id": queue_id}, {"$set": {"message_id": msg.id}})

        await _refresh_queue_channel(interaction.client)
        try:
            await _send_or_edit_status()
        except Exception:
            pass
        await interaction.response.send_message(f"You've been queued for **{n_mode}** ({region})!", ephemeral=True)


class JoinQueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.primary, custom_id="join_queue")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinQueueModal())


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
    """Queue a player for testing"""
    if is_bot_offline():
        return await interaction.response.send_message("Bot is offline by admin.", ephemeral=True)
    n_mode = normalize_mode(gamemode)
    if n_mode not in MODES:
        return await interaction.response.send_message(f"Invalid gamemode. Choose: {', '.join(MODES)}", ephemeral=True)
    region_u = region.upper().strip()
    if region_u not in REGION_COLORS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_COLORS.keys())}", ephemeral=True)
    if _is_gamemode_closed(n_mode):
        return await interaction.response.send_message(f"**{n_mode}** is currently closed in the queue.", ephemeral=True)

    cooldown = _check_queue_cooldown(interaction.user.id)
    if cooldown:
        return await interaction.response.send_message(f"You're already in queue for {cooldown}", ephemeral=True)

    entry = {
        "username": player, "discord_id": interaction.user.id,
        "gamemode": n_mode, "region": region_u,
        "status": "waiting", "claimed_by": None,
        "message_id": None, "channel_id": CLAIM_CHANNEL_ID,
        "ts": datetime.datetime.utcnow(),
    }
    queue_id = db_mgr.queues.insert_one(entry).inserted_id

    # Send queue entry with buttons to claim channel
    claim_channel = bot.get_channel(CLAIM_CHANNEL_ID)
    if claim_channel:
        entry_embed = _build_entry_embed(n_mode, player, region_u, interaction.user.mention)
        view = QueueView(status="waiting")
        msg = await claim_channel.send(embed=entry_embed, view=view)
        db_mgr.queues.update_one({"_id": queue_id}, {"$set": {"message_id": msg.id}})

    await _refresh_queue_channel(bot)
    try:
        await _send_or_edit_status()
    except Exception:
        pass
    await interaction.response.send_message(f"Queued **{player}** for {n_mode} ({region_u}).", ephemeral=True)


@bot.tree.command(name="online")
async def tester_online(interaction: discord.Interaction, region: str, gamemodes: str = None):
    """Mark yourself available for testing with your gamemodes and region"""
    region_u = region.upper().strip()
    if region_u not in REGION_COLORS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_COLORS.keys())}", ephemeral=True)

    existing = db_mgr.tester_profiles.find_one({"discord_id": interaction.user.id})
    old_modes = set(existing.get("gamemodes", [])) if existing else set()

    if gamemodes:
        parsed = set(normalize_mode(m.strip()) for m in gamemodes.split(","))
        parsed = {m for m in parsed if m in MODES}
    else:
        parsed = set()

    if not parsed and not old_modes:
        parsed = set(MODES)  # Default: all modes
    elif not parsed:
        parsed = old_modes  # Keep existing
    else:
        parsed = old_modes | parsed  # Merge

    parsed_list = sorted(parsed)

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

    modes_str = ", ".join(parsed_list)
    embed = discord.Embed(title="You're now online!", color=0x34d399)
    embed.add_field(name="IGN", value=ign or "Not set", inline=True)
    embed.add_field(name="Region", value=region_u, inline=True)
    embed.add_field(name="Testing", value=modes_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await _refresh_queue_channel(interaction.client)

@bot.tree.command(name="offline")
async def tester_offline(interaction: discord.Interaction):
    """Mark yourself as unavailable for testing"""
    db_mgr.tester_profiles.update_one(
        {"discord_id": interaction.user.id},
        {"$set": {"online": False, "ts": datetime.datetime.utcnow()}},
    )
    await interaction.response.send_message("You're now **offline** for testing.", ephemeral=True)
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


@bot.tree.command(name="link")
async def link_discord(interaction: discord.Interaction, code: str):
    """Link your Discord account to the partner page using a code"""
    code = code.strip().upper()
    doc = db_mgr.link_codes.find_one({"code": code})
    if not doc:
        return await interaction.response.send_message("Invalid or expired code. Generate a new one at /partner.", ephemeral=True)
    if doc.get("claimed"):
        return await interaction.response.send_message("This code has already been linked.", ephemeral=True)
    db_mgr.link_codes.update_one({"_id": doc["_id"]}, {"$set": {
        "claimed": True, "discord_id": interaction.user.id,
        "discord_name": str(interaction.user),
        "claimed_ts": datetime.datetime.utcnow(),
    }})
    await interaction.response.send_message(
        f"✅ Linked! Your Discord account is now connected. Return to the partner page to continue.",
        ephemeral=True)


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
