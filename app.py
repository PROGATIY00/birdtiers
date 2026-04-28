import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session
from pymongo import MongoClient
import os
import threading
import asyncio

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      # Public Tier Change Feed
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID") # Network Status Feed
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# --- GAMEMODE ICONS ---
# Add your PNG URLs here. If a mode isn't here, it shows the text name.
MODE_ICONS = {
    "Crystal": "https://i.imgur.com/8QO5W5M.png",
    "UHC": "https://i.imgur.com/K4zI904.png",
    "Pot": "https://i.imgur.com/example_pot.png",
    "Sword": "https://i.imgur.com/example_sword.png",
    "Axe": "https://i.imgur.com/example_axe.png",
    # Add others as needed...
}

# MongoDB
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
partners_col = db_mongo['partners']
settings_col = db_mongo['settings']

if not settings_col.find_one({"id": "maintenance"}):
    settings_col.insert_one({"id": "maintenance", "enabled": False})

# Constants
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

def get_global_rank(pts):
    if pts >= 400: return "Combat Grandmaster", "rank-grand-master"
    if pts >= 200: return "Combat Master", "rank-combat-master"
    return "Combat Ace", "rank-combat-ace"

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
        activity = discord.Activity(type=discord.ActivityType.watching, name="⚠️ MAINT" if m else "🎮 MagmaTIERS")
        await self.change_presence(status=discord.Status.dnd if m else discord.Status.online, activity=activity)

    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
async def maintenance(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator: return
    settings_col.update_one({"id": "maintenance"}, {"$set": {"enabled": enabled}})
    await bot.update_presence()
    
    if STATUS_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(STATUS_CHANNEL_ID))
            embed = discord.Embed(
                title="📡 Network Status",
                description="**Maintenance Mode Active**" if enabled else "**Systems Online**",
                color=discord.Color.red() if enabled else discord.Color.green()
            )
            await channel.send(embed=embed)
        except Exception as e: print(f"Status Error: {e}")
    await interaction.response.send_message(f"Maintenance: {enabled}", ephemeral=True)

@bot.tree.command(name="rank", description="Update a player's tier")
async def rank(interaction: discord.Interaction, name: str, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.administrator: return
    
    tier = tier.upper().strip()
    name_clean = name.strip()
    existing = players_col.find_one({"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode})
    
    old_tier = existing.get('tier', 'None') if existing else 'None'
    peak = existing.get('peak', tier) if existing else tier
    if tier in TIER_ORDER and peak in TIER_ORDER:
        if TIER_ORDER.index(tier) > TIER_ORDER.index(peak): peak = tier

    players_col.update_one(
        {"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode},
        {"$set": {"username": name_clean, "gamemode": mode, "tier": tier, "region": region.upper(), "retired": False, "peak": peak}},
        upsert=True
    )

    if LOG_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            emoji = "🔼" if (old_tier != 'None' and TIER_ORDER.index(tier) > TIER_ORDER.index(old_tier)) else "🔽"
            if old_tier == 'None': emoji = "🆕"
            await channel.send(f"{emoji} **{name_clean}** has been updated to **{tier}** in **{mode}** (Prev: {old_tier})")
        except Exception as e: print(f"Log Error: {e}")

    await interaction.response.send_message(f"Updated {name_clean}", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; }
        
        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:1001; display:flex; justify-content:center; align-items:center; }
        .profile-modal { background: #11141c; width: 420px; border-radius: 20px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .close-modal { position: absolute; top: 15px; right: 20px; font-size: 24px; color: #555; text-decoration: none; }
        .modal-avatar { width: 100px; height: 100px; border-radius: 50%; border: 3px solid #ffcc00; margin-bottom: 15px; }
        
        .modal-tier-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; background: #080a0f; padding: 20px; border-radius: 12px; margin-top: 20px; }
        .mode-item { display: flex; flex-direction: column; align-items: center; gap: 8px; }
        .mode-icon { height: 30px; width: 30px; object-fit: contain; filter: drop-shadow(0 0 5px rgba(255,69,0,0.3)); }
        .mode-text { font-size: 10px; font-weight: 800; color: var(--dim); text-transform: uppercase; }
        
        .tier-badge { background: #1c1f26; padding: 4px 8px; border-radius: 6px; color: var(--accent); font-weight: 800; font-size: 12px; position: relative; cursor: help; width: 100%; box-sizing: border-box;}
        .peak-tooltip { visibility: hidden; background: #000; color: #fff; font-size: 10px; padding: 4px; position: absolute; bottom: 125%; left: 50%; transform: translateX(-50%); border-radius: 4px; border: 1px solid var(--accent); opacity: 0; transition: 0.2s; white-space: nowrap; }
        .tier-badge:hover .peak-tooltip { visibility: visible; opacity: 1; }

        .wrapper { max-width: 900px; margin: auto; padding: 25px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 40px 50px 1fr 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .player-row:hover { border-color: var(--accent); transform: scale(1.01); }
        .global-rank { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; margin-left: 8px; border: 1px solid #ff4500; color: #ff4500; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form><input type="text" name="search" class="search-input" placeholder="Search player..." value="{{ search_query }}"></form>
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" class="close-modal">×</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1 style="margin:0;">{{ spotlight.username }}</h1>
            <div style="color: #ffcc00; font-weight: 800; font-size: 14px; margin-top: 5px;">RANK #{{ spotlight.pos }} OVERALL</div>
            
            <div class="modal-tier-grid">
                {% for r in spotlight.ranks %}
                <div class="mode-item">
                    {% if r.gamemode in icons %}
                        <img src="{{ icons[r.gamemode] }}" class="mode-icon" alt="{{ r.gamemode }}">
                    {% else %}
                        <span class="mode-text">{{ r.gamemode[:3] }}</span>
                    {% endif %}
                    <div class="tier-badge">
                        {{ r.tier }}
                        <span class="peak-tooltip">Peak: {{r.peak}}</span>
                    </div>
                </div>
                {% endfor %}
            </div>
            
            <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="display:block; margin-top:20px; color:var(--dim); text-decoration:none; font-size:12px;">View NameMC Profile</a>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div><b>{{ p.username }}</b> <span class="global-rank">{{ p.rank_name }}</span></div>
            <div class="tier-badge" style="text-align:center;">{{ p.tier }}<span class="peak-tooltip">Peak: {{p.peak}}</span></div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if is_maint(): return "<h1>Maintenance Active</h1>"
    search_q = request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    
    stats = {}
    for p in players_data:
        u, tier = p['username'], p['tier']
        val = TIER_DATA.get(tier, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": tier, "peak": p.get('peak', tier)}
        stats[u]["pts"] += val

    processed = sorted([{"username": u, "points": d["pts"], "tier": d["tier"], "peak": d["peak"], "rank_name": get_global_rank(d["pts"])[0]} for u, d in stats.items()], key=lambda x: -x["points"])

    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {"username": res[0]['username'], "ranks": res, "pos": pos}

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, icons=MODE_ICONS)

if __name__ == '__main__':
    threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
