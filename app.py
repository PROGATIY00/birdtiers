import asyncio
import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
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
TESTER_NOTIF_CHANNEL_ID = 1504206348324311131


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
        else:
            self.players = DummyCollection()
            self.settings = DummyCollection()
            self.reports = DummyCollection()
            self.console_messages = DummyCollection()
            self.queues = DummyCollection()
            self.tester_profiles = DummyCollection()

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
    ts = int(datetime.datetime.utcnow().timestamp())
    identifier = uuid or username
    return f"https://minotar.net/helm/{identifier}/{size}?t={ts}"

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

bot = MagmaBot()

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

def _build_tester_fields():
    testers = _get_tester_profiles()
    if not testers:
        return []

    by_mode = {}
    for t in testers:
        modes = t.get("gamemodes", [])
        mention = f"<@{t['discord_id']}>"
        region = t.get("region", "??")
        label = f"{mention} ({region})"
        if not modes:
            by_mode.setdefault("All", []).append(label)
        else:
            for m in modes:
                by_mode.setdefault(m, []).append(label)

    fields = []
    for mode in MODES:
        entries = by_mode.pop(mode, None)
        if entries:
            fields.append((f"\U0001f7e2 {mode}", ", ".join(entries)))
    for mode, entries in by_mode.items():
        fields.append((f"\U0001f7e2 {mode}", ", ".join(entries)))
    return fields


class QueueView(discord.ui.View):
    def __init__(self, status="waiting", claimed_by=None):
        super().__init__(timeout=None)
        self._status = status
        self._claimed_by = claimed_by
        for child in self.children:
            if child.custom_id == "queue_claim":
                child.disabled = (status != "waiting")
            elif child.custom_id == "queue_done":
                child.disabled = (status != "claimed")

    def _get_gamemode_from_embed(self, embed):
        title = embed.title or ""
        for mode in MODES:
            if title.startswith(f"{mode} Queue"):
                return mode
        return None

    @discord.ui.button(label="Claim Queue", style=discord.ButtonStyle.primary, custom_id="queue_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        gamemode = self._get_gamemode_from_embed(interaction.message.embeds[0])
        if not gamemode:
            return await interaction.response.send_message("Could not determine gamemode.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("No permission.", ephemeral=True)

        q = next(db_mgr.queues.find({"gamemode": gamemode, "status": "waiting"}).sort("ts", 1).limit(1), None)
        if not q:
            return await interaction.response.send_message("No waiting entries in this queue.", ephemeral=True)

        db_mgr.queues.update_one({"_id": q["_id"]}, {"$set": {"status": "claimed", "claimed_by": interaction.user.id}})

        remaining = db_mgr.queues.count_documents({"gamemode": gamemode, "status": "waiting"})
        embed, _ = _build_queue_embed(gamemode)
        if remaining > 0:
            new_view = QueueView(status="waiting")
            await interaction.response.edit_message(embed=embed, view=new_view)
        else:
            new_view = QueueView(status="claimed", claimed_by=interaction.user.id)
            embed.color = 0x34d399
            embed.clear_fields()
            embed.add_field(name="Player", value=q["username"], inline=True)
            embed.add_field(name="Gamemode", value=q["gamemode"], inline=True)
            embed.add_field(name="Region", value=q["region"], inline=True)
            embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
            embed.add_field(name="Status", value="Claimed ✅", inline=True)
            embed.set_footer(text=f"Claimed by {interaction.user}")
            await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="queue_done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        gamemode = self._get_gamemode_from_embed(interaction.message.embeds[0])
        if not gamemode:
            return await interaction.response.send_message("Could not determine gamemode.", ephemeral=True)

        q = next(db_mgr.queues.find({"gamemode": gamemode, "status": "claimed"}).sort("ts", 1).limit(1), None)
        if not q:
            return await interaction.response.send_message("No claimed entries in this queue.", ephemeral=True)
        if interaction.user.id != q.get("claimed_by") and not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("Only the claiming tester can mark as done.", ephemeral=True)

        db_mgr.queues.update_one({"_id": q["_id"]}, {"$set": {"status": "completed"}})

        remaining = db_mgr.queues.count_documents({"gamemode": gamemode, "status": "waiting"})
        if remaining > 0:
            embed, _ = _build_queue_embed(gamemode)
            new_view = QueueView(status="waiting")
            await interaction.response.edit_message(embed=embed, view=new_view)
        else:
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

    @discord.ui.button(label="More Info", style=discord.ButtonStyle.secondary, custom_id="queue_info")
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = db_mgr.queues.find_one({"message_id": interaction.message.id, "channel_id": interaction.channel_id})
        if not q:
            return await interaction.response.send_message("Queue entry not found.", ephemeral=True)

        player = q["username"]
        records = list(db_mgr.players.find({"username": player, "banned": {"$ne": True}}))
        if not records:
            return await interaction.response.send_message(f"No tier data for **{player}**.", ephemeral=True)

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

        rank_name, rank_color = get_rank_info(tiers)
        e = discord.Embed(title=f"Info — {player}", color=discord.Color(int(rank_color.replace("#", ""), 16)))
        e.add_field(name="Rank", value=rank_name, inline=True)
        e.add_field(name="Peak Tier", value=peak_tier or "N/A", inline=True)
        e.add_field(name="Region", value=", ".join(sorted(regions)) or "N/A", inline=True)
        modes_list = "\n".join(f"{m}: {d['tier']}" for m, d in sorted(mode_tiers.items(), key=lambda x: -x[1]["value"]))
        e.add_field(name="Tiers", value=modes_list or "N/A", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


def _build_queue_embed(n_mode):
    waiting = list(db_mgr.queues.find({"gamemode": n_mode, "status": "waiting"}).sort("ts", 1))
    count = len(waiting)

    active = list(db_mgr.queues.find({"status": "waiting"}))
    mode_counts = {}
    region_counts = {}
    for q in active:
        mode_counts[q["gamemode"]] = mode_counts.get(q["gamemode"], 0) + 1
        region_counts[q["region"]] = region_counts.get(q["region"], 0) + 1
    active_modes_str = ", ".join(f"{gm} ({n})" for gm, n in sorted(mode_counts.items())) or "None"
    active_regions_str = ", ".join(f"{r} ({n})" for r, n in sorted(region_counts.items())) or "None"

    embed = discord.Embed(title=f"{n_mode} Queue", color=0xff4500)
    if waiting:
        lines = []
        for idx, q in enumerate(waiting, 1):
            lines.append(f"{idx}. {q['username']} ({q['region']})")
        embed.add_field(name=f"In Queue ({count})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="In Queue", value="Empty", inline=False)

    embed.add_field(name="Active Gamemodes", value=active_modes_str, inline=False)
    embed.add_field(name="Active Regions", value=active_regions_str, inline=False)

    closed_doc = db_mgr.settings.find_one({"_id": "closed_gamemodes"})
    closed_modes = closed_doc.get("modes", []) if closed_doc else []
    if closed_modes:
        embed.add_field(name="Closed Gamemodes", value=", ".join(closed_modes), inline=False)

    for f_name, f_val in _build_tester_fields():
        embed.add_field(name=f_name, value=f_val, inline=False)

    embed.set_footer(text=f"Updated just now | {count} waiting")
    return embed, waiting


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

    entry = {
        "username": player,
        "discord_id": interaction.user.id,
        "gamemode": n_mode,
        "region": region_u,
        "status": "waiting",
        "claimed_by": None,
        "message_id": None,
        "channel_id": QUEUE_CHANNEL_ID,
        "ts": datetime.datetime.utcnow(),
    }
    result = db_mgr.queues.insert_one(entry)
    queue_id = result.inserted_id

    embed, waiting = _build_queue_embed(n_mode)

    channel = bot.get_channel(QUEUE_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("Queue channel not found.", ephemeral=True)

    first_cursor = db_mgr.queues.find({"gamemode": n_mode, "status": "waiting", "message_id": {"$ne": None}}).sort("ts", 1).limit(1)
    first = next(first_cursor, None)
    if first:
        try:
            msg = await channel.fetch_message(first["message_id"])
            await msg.edit(embed=embed)
            db_mgr.queues.update_one({"_id": queue_id}, {"$set": {"message_id": first["message_id"]}})
        except Exception:
            first = None

    if not first:
        view = QueueView()
        msg = await channel.send(embed=embed, view=view)
        db_mgr.queues.update_one({"_id": queue_id}, {"$set": {"message_id": msg.id}})
        for q in waiting:
            db_mgr.queues.update_one({"_id": q["_id"]}, {"$set": {"message_id": msg.id}})

    notif_channel = bot.get_channel(TESTER_NOTIF_CHANNEL_ID)
    if notif_channel and QUEUE_CHANNEL_ID != TESTER_NOTIF_CHANNEL_ID:
        online_testers = _get_tester_profiles()
        notif_embed = discord.Embed(
            title="New Queue Entry",
            description=f"**{player}** queued for **{n_mode}** ({region_u})",
            color=0xffa500,
        )
        notif_embed.add_field(name="Queue Position", value=f"#{len(waiting)} in line", inline=True)
        notif_embed.add_field(name="Online Testers", value=str(len(online_testers)), inline=True)
        notif_embed.set_footer(text="Use /queue to join")
        await notif_channel.send(embed=notif_embed)

    await interaction.response.send_message(f"Queued **{player}** for {n_mode} ({region_u}). Position: #{len(waiting)}", ephemeral=True)


@bot.tree.command(name="online")
async def tester_online(interaction: discord.Interaction, gamemodes: str, region: str):
    """Mark yourself available for testing with your gamemodes and region"""
    parsed = [normalize_mode(m.strip()) for m in gamemodes.split(",")]
    parsed = [m for m in parsed if m in MODES]
    if not parsed:
        return await interaction.response.send_message(f"No valid gamemodes. Choose from: {', '.join(MODES)}", ephemeral=True)
    region_u = region.upper().strip()
    if region_u not in REGION_COLORS:
        return await interaction.response.send_message(f"Invalid region. Choose: {', '.join(REGION_COLORS.keys())}", ephemeral=True)

    ign = None
    player_doc = db_mgr.players.find_one({"discord_id": interaction.user.id})
    if player_doc:
        ign = player_doc.get("username")

    db_mgr.tester_profiles.update_one(
        {"discord_id": interaction.user.id},
        {"$set": {
            "ign": ign or interaction.user.display_name,
            "region": region_u,
            "gamemodes": parsed,
            "online": True,
            "ts": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )

    modes_str = ", ".join(parsed)
    embed = discord.Embed(title="You're now online!", color=0x34d399)
    embed.add_field(name="IGN", value=ign or "Not set", inline=True)
    embed.add_field(name="Region", value=region_u, inline=True)
    embed.add_field(name="Testing", value=modes_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="offline")
async def tester_offline(interaction: discord.Interaction):
    """Mark yourself as unavailable for testing"""
    db_mgr.tester_profiles.update_one(
        {"discord_id": interaction.user.id},
        {"$set": {"online": False, "ts": datetime.datetime.utcnow()}},
    )
    await interaction.response.send_message("You're now **offline** for testing.", ephemeral=True)


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

@bot.tree.command(name="offline")
async def offline_toggle(
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
    }

    if service_l not in service_map:
        return await interaction.response.send_message(
            "Invalid service. Use one of: web, bot, database",
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

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
    :root { --bg: #0b0c10; --card: #14171f; --accent: #ff4500; --text: #f0f2f5; --border: #262932; }
    body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
    .header { background: #0f1117; padding: 1rem 2rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }
    .nav-links { display: flex; gap: 15px; align-items: center; }
    .nav-links a { color: #9ba3af; text-decoration: none; font-weight: 600; font-size: 0.9rem; transition: 0.2s; }
    .nav-links a:hover, .nav-links a.active { color: var(--accent); }
    .container { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 50px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    .player-row:hover { border-color: var(--accent); transform: scale(1.01); }
    .player-row.top-player { border-color: gold; box-shadow: 0 0 20px rgba(255, 215, 0, 0.18); background: linear-gradient(135deg, rgba(255,215,0,0.08), rgba(17,23,34,0.96)); }
    .badge { padding: 2px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase; border: 1px solid currentColor; }
    .top-badge { margin-left: 0.75rem; color: #ffd700; font-size: 0.75rem; font-weight: 800; background: rgba(255,215,0,0.12); padding: 3px 8px; border-radius: 999px; }
    .reg-tag { font-weight: 800; font-size: 0.85rem; }
    .high-results { background: rgba(255, 69, 0, 0.05); border-left: 5px solid var(--accent); padding: 20px; border-radius: 0 15px 15px 0; margin-bottom: 30px; }
    input { background: var(--card); border: 1px solid var(--border); color: white; padding: 8px 15px; border-radius: 8px; outline: none; }

    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(10px); }
    .profile-card { background: #11141c; width: 460px; border-radius: 24px; border: 1px solid var(--border); overflow: hidden; }
    .profile-header { background: linear-gradient(180deg, #1a1e29 0%, #11141c 100%); padding: 35px 20px 25px; text-align: center; }
    .profile-avatar-wrapper { width: 120px; height: 120px; border-radius: 50%; border: 4px solid #f5c06d; display: inline-flex; justify-content: center; align-items: center; margin: 0 auto 15px; background: radial-gradient(circle at top, rgba(255,255,255,0.12), transparent 55%); }
    .profile-avatar { width: 104px; height: 104px; border-radius: 50%; border: 3px solid rgba(255,255,255,0.12); object-fit: cover; }
    .profile-name { margin: 0; font-size: 2rem; font-weight: 800; color: #ffffff; }
    .profile-rank { display: inline-flex; align-items: center; gap: 8px; margin-top: 10px; padding: 8px 16px; border-radius: 999px; background: rgba(255, 192, 100, 0.12); color: #f5c06d; border: 1px solid rgba(245,192,100,0.25); font-weight: 800; font-size: 0.9rem; }
    .profile-region { color: #8f9bb3; margin-top: 8px; font-size: 0.95rem; }
    .name-mc-button { display: inline-flex; align-items: center; gap: 8px; margin: 14px auto 0; padding: 10px 16px; border-radius: 999px; background: #0f1117; color: #d8dde7; text-decoration: none; border: 1px solid rgba(255,255,255,0.08); font-size: 0.9rem; }
    .profile-body { padding: 25px; background: #14171f; }
    .profile-section { margin-bottom: 18px; }
    .profile-section h3 { margin: 0 0 12px; font-size: 0.8rem; letter-spacing: 0.15em; color: #9ba3af; }
    .position-box { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 18px; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 12px; }
    .position-number { font-size: 1.4rem; font-weight: 800; color: #f5c06d; }
    .tier-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 12px; }

    /* Tier card */
    .tier-card { background: #0f1117; border: 1px solid var(--border); border-radius: 16px; padding: 14px 10px; text-align: center; transition: 0.2s; position: relative; cursor: default; }
    .tier-card:hover { border-color: var(--accent); transform: translateY(-2px); }
    .tier-card.retired { opacity: 0.45; filter: grayscale(100%); }
    .tier-card.top-mode { border-color: #ffd700; box-shadow: 0 0 10px rgba(255,215,0,0.2); }
    .discord {
    background: #7289da;
    color: white;
    border: none;
    
    padding: 8px 15px;
    border-radius: 20px;
    font-weight: 600;
    cursor: pointer;
    }
    /* Peak tooltip — appears above card on hover */
    .tier-card .peak-tooltip {
        display: none;
        position: absolute;
        bottom: calc(100% + 8px);
        left: 50%;
        transform: translateX(-50%);
        background: #1e2230;
        border: 1px solid var(--accent);
        color: #f0f2f5;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        padding: 5px 10px;
        border-radius: 8px;
        white-space: nowrap;
        z-index: 10;
        pointer-events: none;
    }
    .tier-card .peak-tooltip::after {
        content: '';
        position: absolute;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        border: 5px solid transparent;
        border-top-color: var(--accent);
    }
    .tier-card:hover .peak-tooltip { display: block; }

    .tier-icon-img { width: 38px; height: 38px; margin: 0 auto 8px; border-radius: 12px; display: block; object-fit: contain; }
    .tier-label { color: #d8dde7; font-size: 0.85rem; font-weight: 800; }
    .tier-subtext { color: #9ba3af; font-size: 0.75rem; margin-top: 6px; }

    .hamburger { display:none; background:none; border:none; color:var(--text); font-size:1.8rem; cursor:pointer; padding:0 8px; line-height:1; }
    .sidebar-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:999; }
    .sidebar { position:fixed; top:0; left:-280px; width:260px; height:100%; background:#0f1117; border-right:2px solid var(--border); z-index:1000; transition:left 0.25s ease; overflow-y:auto; padding:20px 0; display:flex; flex-direction:column; }
    .sidebar.open { left:0; }
    .sidebar-overlay.open { display:block; }
    .sidebar a { display:block; color:#9ba3af; text-decoration:none; font-weight:600; font-size:0.95rem; padding:12px 24px; transition:0.2s; border-left:3px solid transparent; }
    .sidebar a:hover, .sidebar a.active { color:var(--accent); background:rgba(255,69,0,0.06); border-left-color:var(--accent); }
    .sidebar .sidebar-logo { padding:12px 24px 20px; font-size:1.3rem; font-weight:800; color:white; border-bottom:1px solid var(--border); margin-bottom:8px; }
    .sidebar .sidebar-logo span { color:var(--accent); }
    @media (max-width:768px) {
        .hamburger { display:block; }
        .nav-links { display:none !important; }
        .hide-mobile { display:none !important; }
    }
</style>
"""

@app.route('/')
def home():
    if is_web_offline():
        return "<html><head><title>MagmaTIERS</title></head><body style='font-family:Arial;background:#0b0c10;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;'><h1>Website is offline by admin.</h1></body></html>", 503
    maint = is_maintenance_active()

    if maint.get('active'):
        return f"<html><head>{STYLE}</head><body style='display:flex;justify-content:center;align-items:center;height:100vh;'><div class='container' style='text-align:center;'><h1>🛠️ {maint.get('reason')}</h1></div></body></html>"

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

    template = """
<html><head><meta http-equiv="refresh" content="300"><title>MagmaTIERS</title>{{ s|safe }}</head>
    <script>
      // Force-refresh Minecraft heads every 15s
      setInterval(() => {
        document.querySelectorAll('img[src*="minotar.net"]').forEach(img => {
          const clean = img.src.split('?')[0];
          if (img.src !== clean + '?t=' + Date.now()) img.src = clean + '?t=' + Date.now();
        });
      }, 15000);
    </script>
    <body>
        <div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>
        <div class="sidebar" id="sidebar">
            <div class="sidebar-logo">Magma<span>TIERS</span></div>
            <a href="/" class="{% if not m %}active{% endif %}" onclick="toggleSidebar()">Global</a>
            {% for gm in modes %}<a href="/?mode={{gm}}" class="{% if m == gm %}active{% endif %}" onclick="toggleSidebar()">{{gm}}</a>{% endfor %}
            <div style="margin-top:auto;padding:16px 24px;border-top:1px solid var(--border);">
                <button class="discord" style="width:100%;padding:10px;display:flex;align-items:center;justify-content:center;gap:8px;" onclick='window.location.href="https://magmatiers.onrender.com/discord"'>
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="#ffffff"><path d="M20 4.5a19.8 19.8 0 0 0-4-1.5l-.2.4a18.5 18.5 0 0 0-5.6 0l-.2-.4a19.8 19.8 0 0 0-4 1.5C2 8 1.5 11.5 1.7 15c1.2.9 2.4 1.5 3.7 2l.5-.7c-.5-.2-1-.5-1.5-.9l.4-.3c2.7 1.3 5.6 1.3 8.3 0l.4.3c-.5.4-1 .7-1.5.9l.5.7c1.3-.5 2.5-1.1 3.7-2 .2-3.5-.3-7-2.1-10.5ZM8.5 14.4c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm7 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>
                    Discord
                </button>
            </div>
        </div>
        <div class="header">
            <div style="display:flex;align-items:center;gap:8px;">
                <button class="hamburger" onclick="toggleSidebar()">☰</button>
                <a href="/" style="color:white;text-decoration:none;font-weight:800;font-size:1.6rem;">Magma<span style="color:var(--accent);">TIERS</span></a>
            </div>
            <div class="nav-links">
                <a href="/" class="{% if not m %}active{% endif %}">Global</a>
                {% for gm in modes %}<a href="/?mode={{gm}}" class="{% if m == gm %}active{% endif %}">{{gm}}</a>{% endfor %}
            </div>
            <button class="discord hide-mobile" aria-label="Discord" title="Discord" onclick='window.location.href="https://magmatiers.onrender.com/discord"'>
                <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#ffffff"><path d="M20 4.5a19.8 19.8 0 0 0-4-1.5l-.2.4a18.5 18.5 0 0 0-5.6 0l-.2-.4a19.8 19.8 0 0 0-4 1.5C2 8 1.5 11.5 1.7 15c1.2.9 2.4 1.5 3.7 2l.5-.7c-.5-.2-1-.5-1.5-.9l.4-.3c2.7 1.3 5.6 1.3 8.3 0l.4.3c-.5.4-1 .7-1.5.9l.5.7c1.3-.5 2.5-1.1 3.7-2 .2-3.5-.3-7-2.1-10.5ZM8.5 14.4c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm7 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>
            </button>
            <form action="/" style="margin:0;"><input name="search" placeholder="Search..."></form>
        </div>
        <script>
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('open');
            document.getElementById('sidebarOverlay').classList.toggle('open');
        }
        </script>

        {% if spot %}
        <div class="modal-bg" onclick="window.location.href='/?mode={{m}}'">
            <div class="profile-card" onclick="event.stopPropagation()">
                <div class="profile-header">
                    <div class="profile-avatar-wrapper" style="border-color:{{ spot.placement_color }};">
                        <img src="{{ spot.head_url }}" class="profile-avatar">
                    </div>
                    <h2 class="profile-name">{{ spot.u }}</h2>
                    <div class="profile-rank">🏆 {{ spot.rank }}</div>
                    <div class="profile-region">{{ spot.region_name }}</div>
                    <a class="name-mc-button" href="https://namemc.com/profile/{{ spot.u }}" target="_blank">NameMC</a>
                </div>
                <div class="profile-body">
                    <div class="profile-section">
                        <h3>POSITION</h3>
                        <div class="position-box">
                            <div class="position-number" style="color:{{ spot.placement_color }};">#{{ spot.position }}</div>
                            <div style="font-weight:800;">{{ spot.position_label }} · {{ spot.best }}</div>
                            <div style="color:#9ba3af;">({{ spot.score }} pts)</div>
                        </div>
                    </div>
                    <div class="profile-section">
                        <h3>TIERS</h3>
                        <div class="tier-grid">
                            {% for k in spot.kits %}
                            <div class="tier-card{% if k.retired %} retired{% endif %}{% if k.top_mode %} top-mode{% endif %}">
                                <div class="peak-tooltip">{{ k.peak_label }}</div>
                                <img src="{{ mode_icon_urls.get(k.gamemode, default_icon_url) }}" class="tier-icon-img" onerror="this.onerror=null;this.src='{{ default_icon_url }}';">
                                <div class="tier-label">{{ k.gamemode }}</div>
                                <div class="tier-subtext">{{ k.tier }}</div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        {% if high_p and not spot %}
        <div class="container">
            <div class="high-results">
                <h2 style="margin:0 0 12px;font-size:1.2rem;">🏆 Top Players</h2>
                {% for p in high_p[:5] %}
                <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                    <span class="badge" style="color:{{ p.rank_c }};">{{ p.rank }}</span>
                    <span style="font-weight:600;">{{ p.u }}</span>
                    <span style="color:#9ba3af;margin-left:auto;">{{ p.best }} · {{ p.score }} pts</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="container">
            {% for p in players %}

            {% set pc = 'gold' if loop.index == 1 else 'silver' if loop.index == 2 else '#cd7f32' if loop.index == 3 else '#9ba3af' %}
            <a href="/?search={{ p.u }}&mode={{m}}" class="player-row{% if m and loop.index == 1 %} top-player{% endif %}">
                <div style="font-weight:800;color:{{ pc }};">#{{ loop.index }}</div>
                <img src="{{ p.head_url }}" onerror="this.src='https://minotar.net/helm/Steve/32?t='+Date.now();">
                <div>{{ p.u }} <span class="badge" style="color:{{ p.rank_c }};margin-left:10px;">{{ p.rank }}</span></div>
                <div class="reg-tag" style="color:{{ p.reg_c }}">{{ p.reg }}</div>
                <div style="text-align:right;color:var(--accent);font-weight:800;">{{ p.mode_tier if m else p.best }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(
        template, s=STYLE, players=players, spot=spotlight, modes=MODES,
        m=mode_q, search=search_q, high_p=high_p,
        mode_icon_urls=GAMEMODE_ICON_URLS, default_icon_url=DEFAULT_GAMEMODE_ICON_URL,
    )

@app.route('/moderation')
def moderation():
    if is_web_offline():
        return "Website is offline by admin.", 503

    reps = list(db_mgr.reports.find({"status": "Pending"}))
    return render_template_string("""
        <html><head>{{ s|safe }}</head><body><div class="container">
        <h1>Reports Queue</h1>
        {% for r in reps %}
        <div style="background:var(--card);padding:20px;border-radius:12px;margin-bottom:10px;border:1px solid var(--border);">
            <h3>{{ r.player }}</h3><p>{{ r.reason }}</p>
            <form action="/moderation/resolve" method="POST">
                <input type="hidden" name="id" value="{{ r._id }}">
                <button name="a" value="approve" style="background:green;color:white;border:none;padding:10px;border-radius:5px;cursor:pointer;">Approve</button>
                <button name="a" value="decline" style="background:#444;color:white;border:none;padding:10px;border-radius:5px;cursor:pointer;">Decline</button>
            </form>
        </div>
        {% endfor %}
        <a href="/" style="color:var(--accent);text-decoration:none;">← Back Home</a>
        </div></body></html>
    """, s=STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_mgr.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect(url_for('moderation'))
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

    return render_template_string(f"""

    <html>
      <head>
        <title>Status - MagmaTIERS</title>
        <meta name='viewport' content='width=device-width, initial-scale=1.0'/>
        <style>
          body {{ margin:0; font-family: Arial, Helvetica, sans-serif; background:#0b0c10; color:#f0f2f5; }}
          .wrap {{ max-width: 900px; margin: 40px auto; padding: 0 16px; }}
          .card {{ background:#14171f; border:1px solid #262932; border-radius:16px; padding:16px; margin-bottom:14px; }}
          h1 {{ margin:0 0 6px; font-size: 28px; }}
          h2 {{ margin:0 0 12px; font-size: 18px; color:#ff4500; }}
          .row {{ display:flex; justify-content:space-between; gap:16px; padding:10px 0; border-bottom:1px solid rgba(255,255,255,0.06); }}
          .row:last-child {{ border-bottom:none; }}
          .k {{ color:#9ba3af; font-weight:700; }}
          .v {{ font-weight:800; text-align:right; }}
          .pill {{ display:inline-block; padding:3px 10px; border-radius:999px; font-weight:800; border:1px solid rgba(255,255,255,0.12); }}
          .ok {{ color:#34d399; border-color: rgba(52,211,153,0.35); background: rgba(52,211,153,0.08); }}
          .bad {{ color:#f87171; border-color: rgba(248,113,113,0.35); background: rgba(248,113,113,0.08); }}
          .muted {{ color:#9ba3af; }}
          a {{ color:#ff4500; text-decoration:none; font-weight:800; }}
          .top {{ display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom:14px; }}
          .btn {{ padding:10px 14px; background:#ff4500; color:white; border-radius:12px; font-weight:900; }}
        </style>
      </head>
      <body>
        <div class='wrap'>
          <div class='top'>
            <div>
              <h1>MagmaTIERS Status</h1>
              <div class='muted'>Updated just now</div>
            </div>
            <div class='muted'>API JSON: <a href='/status'>/status</a></div>
          </div>

          <div class='card'>
            <h2>Services</h2>
            <div class='row'>
              <div class='k'>Website</div>
              <div class='v'><span class='pill {'ok' if web_ok else 'bad'}'>{'Online' if web_ok else 'Offline'}</span></div>
            </div>
            <div class='row'>
              <div class='k'>Discord bot</div>
              <div class='v'><span class='pill {'ok' if discord_ready and TOKEN else 'bad'}'>{'Online' if discord_ready and TOKEN else 'Offline'}</span></div>
            </div>
            <div class='row'>
              <div class='k'>Database</div>
              <div class='v'><span class='pill {'ok' if db_ok else 'bad'}'>{'Online' if db_ok else 'Offline'}</span></div>
            </div>
            <div class='row'>
              <div class='k'>Backups</div>
              <div class='v'><span class='pill {'ok' if backups_ok else 'bad'}'>{'ENABLED' if backups_ok else 'DISABLED'}</span></div>
            </div>
          </div>

          <div class='card'>
            <h2>Details</h2>
            <div class='row'>
              <div class='k'>Maintenance</div>
              <div class='v'>
                <span class='pill {'ok' if not maint.get('active') else 'bad'}'>{'OFF' if not maint.get('active') else 'ON'}</span>
              </div>
            </div>
            <div class='row'>
              <div class='k'>Maintenance reason</div>
              <div class='v'>{(maint.get('reason', '') if maint.get('active') else '') or '—'}</div>
            </div>
            <div class='row'>
              <div class='k'>Database name</div>
              <div class='v'>{DB_NAME}</div>
            </div>
            <div class='row'>
              <div class='k'>Backup dir</div>
              <div class='v'>{BACKUP_DIR}</div>
            </div>
          </div>

          <div style='text-align:center; margin-top:12px;' class='muted'>
            <a href='/'>← Back to website</a>
          </div>
        </div>
      </body>
    </html>
    """,)


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
    return render_template_string(f"""
    <html><head>
      <title>Heads - MagmaTIERS</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
      <style>
        body {{ margin:0; font-family:Arial,Helvetica,sans-serif; background:#0b0c10; color:#f0f2f5; }}
        .wrap {{ max-width:1000px; margin:0 auto; padding:16px; }}
        h1 {{ font-size:24px; }}
        .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(80px,1fr)); gap:12px; }}
        .card {{ background:#14171f; border:1px solid #262932; border-radius:12px; padding:12px; text-align:center; }}
        .card img {{ width:64px; height:64px; border-radius:8px; image-rendering:pixelated; }}
        .card .name {{ font-size:11px; color:#9ba3af; margin-top:6px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
        .nav {{ display:flex; gap:16px; align-items:center; margin-bottom:16px; }}
        .nav a {{ color:#ff4500; text-decoration:none; font-weight:800; }}
      </style>
      <script>
        setInterval(() => {{
          document.querySelectorAll('img[src*="minotar.net"]').forEach(img => {{
            img.src = img.src.split('?')[0] + '?t=' + Date.now();
          }});
        }}, 5000);
      </script>
    </head><body>
      <div class="wrap">
        <div class="nav">
          <a href="/">← Home</a>
          <h1>Head Status</h1>
        </div>
        <p style="color:#9ba3af;margin-bottom:16px;">Heads refresh every 5s. {len(players)} unique players shown.</p>
        <div class="grid">
          {"".join(f'<div class="card"><img src="{p["head_url"]}" onerror="this.onerror=null;this.src=this.src.split(\'?\')[0]+\'?t=\'+Date.now();"><div class="name">{p["username"]}</div><div style="font-size:10px;color:#525768;">{p["region"]} · {p["tier"]}</div></div>' for p in players)}
        </div>
      </div>
    </body></html>
    """)

STYLE_CONSOLE = """
body{margin:0;font-family:'Courier New',monospace;background:#0a0a0a;color:#00ff41;padding:16px;}
h1{font-size:18px;margin:0 0 12px;color:#00ff41;}
.log{font-size:13px;line-height:1.6;white-space:pre-wrap;word-break:break-all;}
.log div:hover{background:#0f0f0f;}
.ts{color:#525768;}
.act{color:#ff4500;font-weight:800;}
.run{color:#888;}
.det{color:#9ba3af;}
.nav{margin-bottom:16px;}
.nav a{color:#ff4500;text-decoration:none;font-weight:800;margin-right:12px;}
"""

@app.route('/console')
def console_page():
    if is_web_offline():
        return "Website is offline by admin.", 503
    with console_logs_lock:
        logs = list(reversed(console_logs))
    return render_template_string("""<html><head><title>Console - MagmaTIERS</title><meta name="viewport" content="width=device-width,initial-scale=1.0"><style>""" + STYLE_CONSOLE + """</style></head><body>
<div class="nav"><a href="/">← Home</a><span style="color:#525768;font-size:13px;"> Live console — auto-refresh every 3s</span></div>
<h1>📡 Console <span id="count" style="font-size:13px;color:#525768;">0 entries</span></h1>
<div id="log" class="log">""" + "".join(
    '<div><span class="ts">[{}]</span> <span class="act">{}</span>{} <span class="det">{}</span></div>'.format(
        e["ts"][:19].replace("T", " "), e["action"], f' <span class="run">({e["runner"]})</span>' if e["runner"] else "", e["details"]
    ) for e in logs
) + """</div>
<script>
async function poll(){try{const r=await fetch('/api/console/logs');if(!r.ok)return;const d=await r.json();const el=document.getElementById('log');el.innerHTML='';d.forEach(e=>{const div=document.createElement('div');const r=e.runner?' <span class="run">('+e.runner+')</span>':'';div.innerHTML='<span class="ts">['+e.ts.slice(0,19).replace('T',' ')+']</span> <span class="act">'+e.action+'</span>'+r+' <span class="det">'+e.details+'</span>';el.appendChild(div);});document.getElementById('count').textContent=d.length+' entries';}catch(e){}}
setInterval(poll,3000);poll();
</script></body></html>""")

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
