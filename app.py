import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session
from pymongo import MongoClient
import os
import threading
import time

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://discord.gg/magmatiers")

# MongoDB Setup
client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
partners_col = db_mongo['partners']
settings_col = db_mongo['settings']

# Ensure Maintenance Setting Exists
if not settings_col.find_one({"id": "maintenance"}):
    settings_col.insert_one({"id": "maintenance", "enabled": False})

# Constants
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

def get_global_rank(pts):
    if pts >= 400: return "GRAND MASTER", "rank-grand-master"
    if pts >= 200: return "COMBAT MASTER", "rank-combat-master"
    return "COMBAT ACE", "rank-combat-ace"

def is_maint():
    doc = settings_col.find_one({"id": "maintenance"})
    return doc['enabled'] if doc else False

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def update_presence(self):
        m = is_maint()
        status_text = "⚠️ MAINTENANCE" if m else "🎮 MAGMATiers LIVE"
        activity = discord.Activity(type=discord.ActivityType.watching, name=status_text)
        await self.change_presence(status=discord.Status.dnd if m else discord.Status.online, activity=activity)

    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
async def maintenance(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator: return
    settings_col.update_one({"id": "maintenance"}, {"$set": {"enabled": enabled}})
    await bot.update_presence()
    await interaction.response.send_message(f"📡 Maintenance is now {'ON' if enabled else 'OFF'}")

@bot.tree.command(name="rank", description="Set player tier and announce")
async def rank(interaction: discord.Interaction, name: str, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.administrator: return
    
    tier = tier.upper().strip()
    name_clean = name.strip()
    existing = players_col.find_one({"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode})
    
    old_tier = existing.get('tier', 'LT5') if existing else 'LT5'
    peak = existing.get('peak', tier) if existing else tier
    
    # Update Peak
    if tier in TIER_ORDER and peak in TIER_ORDER:
        if TIER_ORDER.index(tier) > TIER_ORDER.index(peak): peak = tier

    players_col.update_one(
        {"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode},
        {"$set": {"username": name_clean, "gamemode": mode, "tier": tier, "region": region.upper(), "retired": False, "peak": peak}},
        upsert=True
    )

    # Status Message
    status = "updated"
    if tier in TIER_ORDER and old_tier in TIER_ORDER:
        if TIER_ORDER.index(tier) > TIER_ORDER.index(old_tier): status = "promoted"
        elif TIER_ORDER.index(tier) < TIER_ORDER.index(old_tier): status = "demoted"

    if LOG_CHANNEL_ID:
        channel = await bot.fetch_channel(int(LOG_CHANNEL_ID))
        await channel.send(f"**{name_clean}** {status} to **{tier}** in **{mode}**")

    await interaction.response.send_message(f"🌋 Rank Set for {name_clean}", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

MAINTENANCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS - Disconnected</title>
    <style>
        body { background: #0a0b0d; color: #cfd8dc; font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .ts-modal { background: #1a1c1f; border: 1px solid #333; width: 450px; border-radius: 4px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); overflow: hidden;}
        .ts-header { background: #23272a; padding: 10px 15px; font-size: 13px; font-weight: bold; border-bottom: 1px solid #333; color: #aaa; }
        .ts-body { padding: 30px; text-align: center; }
        .progress-bg { background: #000; height: 12px; border-radius: 2px; position: relative; overflow: hidden; border: 1px solid #444; margin: 20px 0; }
        .progress-bar { background: linear-gradient(to right, #4a90e2, #357abd); width: 40%; height: 100%; animation: slide 2s infinite ease-in-out; }
        @keyframes slide { from { margin-left: -40%; } to { margin-left: 100%; } }
        .info-box { background: #000; color: #00ff00; font-family: monospace; padding: 10px; font-size: 11px; text-align: left; border: 1px solid #222; }
    </style>
</head>
<body>
    <div class="ts-modal">
        <div class="ts-header">MagmaTiers - Connection Lost</div>
        <div class="ts-body">
            <div style="color:#ff5555; font-weight:bold; font-size:14px;">SERVER MAINTENANCE IN PROGRESS</div>
            <div class="progress-bg"><div class="progress-bar"></div></div>
            <div class="info-box">
                > System: MagmaTiers Core<br>
                > Status: 503_SERVICE_UNAVAILABLE<br>
                > Reason: Optimizing Tier Calculations<br>
                > Reconnecting in: T-Minus 20m
            </div>
        </div>
    </div>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MAGMATIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; }

        /* Status Pills */
        .status-pill { font-size: 10px; padding: 4px 10px; border-radius: 20px; font-weight: 800; display: flex; align-items: center; gap: 6px; }
        .status-live { background: rgba(0, 255, 0, 0.1); color: #00ff00; border: 1px solid #00ff00; }
        .dot { width: 6px; height: 6px; border-radius: 50%; background: #00ff00; box-shadow: 0 0 5px #00ff00; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }

        /* THE INSANE HT1 ANIMATION */
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); border-radius: 14px; animation: rotate 2s linear infinite; }
        .insane-tier-text { color: #fff !important; text-shadow: 0 0 10px #ff4500; font-weight: 900; }

        /* PEAK HOVER */
        .tier-badge { position: relative; cursor: help; background: #1c1f26; padding: 6px 12px; border-radius: 6px; text-align: center; font-weight: 800; font-size: 13px; color: var(--accent); }
        .peak-tooltip {
            visibility: hidden; background: #000; color: #fff; text-align: center; border-radius: 4px; padding: 4px 8px;
            position: absolute; z-index: 10; bottom: 125%; left: 50%; transform: translateX(-50%); font-size: 10px;
            white-space: nowrap; border: 1px solid var(--accent); opacity: 0; transition: 0.2s;
        }
        .tier-badge:hover .peak-tooltip { visibility: visible; opacity: 1; }

        .global-rank { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; margin-left: 8px; vertical-align: middle; }
        .rank-grand-master { background: rgba(255, 0, 0, 0.2); color: #ff0000; border: 1px solid #ff0000; }
        .rank-combat-master { background: rgba(255, 140, 0, 0.2); color: #ff8c00; border: 1px solid #ff8c00; }

        .wrapper { max-width: 950px; margin: auto; padding: 25px; min-height: 60vh; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 45px 50px 1fr 70px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    </style>
</head>
<body>
    <div class="navbar">
        <div style="display: flex; align-items: center; gap: 20px;">
            <a href="/" class="logo">MAGMA<span>TIERS</span></a>
            <div class="status-pill status-live"><div class="dot"></div> LIVE</div>
        </div>
        <form><input type="text" name="search" class="search-input" placeholder="Search..." value="{{ search_query }}"></form>
    </div>

    <div class="mode-nav" style="display:flex; justify-content:center; gap:8px; padding:15px; background:#0f1117; border-bottom:1px solid var(--border);">
        <a href="/" class="mode-btn" style="text-decoration:none; color:var(--dim);">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn" style="text-decoration:none; color:var(--dim);">{{m|upper}}</a>{% endfor %}
    </div>

    <div class="wrapper">
        {% if spotlight %}
        <div style="background: linear-gradient(145deg, #1f1412, #14171f); border: 2px solid var(--accent); border-radius: 18px; padding: 25px; margin-bottom: 30px; display: flex; gap: 25px; align-items: center;">
            <img src="https://minotar.net/helm/{{spotlight.username}}/80.png" style="border-radius:12px;">
            <div>
                <h1 style="margin:0;">{{ spotlight.username }}</h1>
                <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="color:var(--dim); font-size:12px; text-decoration:none;">NameMC Profile</a>
            </div>
        </div>
        {% endif %}

        {% for p in players %}
        {% set is_insane = p.tier in ['HT1', 'LT1'] %}
        <a href="/?search={{p.username}}" class="player-row {% if is_insane %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div>
                <b class="{% if is_insane %}insane-tier-text{% endif %}">{{ p.username }}</b>
                <span class="global-rank {{ p.rank_id }}">{{ p.rank_name }}</span>
                <br><small style="color:var(--dim)">{{ p.points }} Pts</small>
            </div>
            <div style="font-size:13px; color:var(--dim); font-weight:800;">{{ p.region }}</div>
            <div class="tier-badge">
                {{ p.tier }}
                <span class="peak-tooltip">Peak: {{ p.peak }}</span>
            </div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if is_maint(): return render_template_string(MAINTENANCE_HTML)
    
    mode_filter, search_q = request.args.get('mode', ''), request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    
    stats = {}
    for p in players_data:
        u, gm, tier, ret = p['username'], p['gamemode'], p['tier'], p.get('retired', False)
        peak = p.get('peak', tier)
        val = TIER_DATA.get(tier, 0)
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "retired": True, "tier": "N/A", "peak": peak}
        
        if mode_filter:
            if gm.lower() == mode_filter.lower(): stats[u].update({"pts": val, "tier": tier, "retired": ret, "peak": peak})
        else:
            if not ret: (stats[u].update({"retired": False}), stats[u].update({"pts": stats[u]["pts"] + val}))
            else: stats[u]["pts"] += (val * 0.1)

    processed = []
    for u, d in stats.items():
        if d['pts'] <= 0: continue
        r_name, r_id = get_global_rank(d['pts'])
        processed.append({"username": u, "points": int(d['pts']), "region": d['region'], "retired": d['retired'], "tier": d['tier'], "peak": d['peak'], "rank_name": r_name, "rank_id": r_id})

    processed = sorted(processed, key=lambda x: (x['retired'], -x['points']))
    
    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res: spotlight = {"username": res[0]['username']}

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_filter, search_query=search_q, spotlight=spotlight)

def start_bot():
    if TOKEN: bot.run(TOKEN)

threading.Thread(target=start_bot, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.
