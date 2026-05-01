"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 3.2
Restored all features with updated PyMongo safety checks.
"""

import discord
from discord import app_commands
from flask import Flask, render_template_string, request, jsonify
from pymongo import MongoClient
import os
import threading
import datetime
import sys
import logging

# --- SYSTEM LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MagmaTiers")

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

# --- DATABASE MANAGER ---
class DatabaseManager:
    def __init__(self, uri):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.db = self.client['magmatiers_db']
            self.players = self.db['players']
            self.settings = self.db['settings']
            self.client.admin.command('ping')
            logger.info("✅ Database Connected")
        except Exception as e:
            logger.error(f"❌ Database Offline: {e}")
            self.db = None

db_manager = DatabaseManager(MONGO_URI)

# --- CORE RANKING LOGIC ---
def get_tier_value(tier_name):
    try:
        return TIER_ORDER.index(tier_name.upper().strip()) + 1
    except:
        return 0

def calculate_player_score(tier_list):
    return sum(get_tier_value(t) for t in tier_list)

def get_global_rank_name(tier_list):
    if not tier_list: return "Stone"
    total_score = calculate_player_score(tier_list)
    numeric_tiers = [get_tier_value(t) for t in tier_list]
    highest = max(numeric_tiers) if numeric_tiers else 0
    
    if highest >= 9 and len(tier_list) >= 3: return "Grandmaster"
    if total_score >= 35: return "Legend"
    if total_score >= 25: return "Master"
    if total_score >= 15: return "Elite"
    if total_score >= 8: return "Diamond"
    return "Bronze"

def get_maintenance_status():
    if db_manager.db is None: # FIXED: Explicit check
        return {"active": True, "reason": "Database connection lost.", "duration": "N/A"}
    status = db_manager.settings.find_one({"_id": "maintenance_mode"})
    return status if status else {"active": False, "reason": "None", "duration": "Unknown"}

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Update player tier")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str], reason: str = "Tested"):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Permissions required.", ephemeral=True)
    
    if get_maintenance_status()['active']:
        return await interaction.response.send_message("🛠️ Maintenance mode active.", ephemeral=True)

    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message("❌ Invalid tier format.", ephemeral=True)

    db_manager.players.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {
            "tier": tier_upper, 
            "region": region.value, 
            "discord_id": discord_user.id, 
            "last_updated": datetime.datetime.utcnow(),
            "retired": False
        }},
        upsert=True
    )

    log_chan = bot.get_channel(int(LOG_CHANNEL_ID))
    if log_chan:
        embed = discord.Embed(title="Tier Update", color=0xff4500, timestamp=datetime.datetime.utcnow())
        embed.description = f"**{player}** set to **{tier_upper}** in **{mode.value}**\n**Reason:** {reason}\n**Region:** {region.value}"
        embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
        await log_chan.send(embed=embed)

    await interaction.response.send_message(f"✅ Updated **{player}** to {tier_upper}.", ephemeral=True)

@bot.tree.command(name="maintenance", description="Toggle site maintenance")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Updates"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    db_manager.settings.update_one({"_id": "maintenance_mode"}, {"$set": {"active": active, "reason": reason}}, upsert=True)
    await interaction.response.send_message(f"🛠️ Maintenance is now {'ENABLED' if active else 'DISABLED'}.")

# --- WEB UI & FLASK ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS | Official Leaderboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #f0f2f5; --dim: #9ba3af; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .header { background: #0f1117; padding: 1rem 4rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 1000; }
        .logo { font-size: 1.8rem; font-weight: 800; color: white; text-decoration: none; }
        .logo span { color: var(--accent); }
        .nav-strip { background: #0f1117; padding: 10px; display: flex; justify-content: center; gap: 10px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
        .nav-btn { padding: 6px 15px; border-radius: 8px; background: var(--card); border: 1px solid var(--border); color: var(--dim); text-decoration: none; font-size: 0.9rem; }
        .nav-btn.active { border-color: var(--accent); color: white; }
        .container { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 50px 60px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .player-row:hover { border-color: var(--accent); transform: translateY(-2px); }
        .pos { font-size: 1.3rem; font-weight: 800; color: var(--accent); }
        .badge { background: rgba(255, 69, 0, 0.1); color: var(--accent); font-size: 0.7rem; font-weight: 800; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--accent); text-transform: uppercase; }
        .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(5px); }
        .modal { background: #11141c; width: 400px; padding: 40px; border-radius: 20px; border: 1px solid #2d3647; text-align: center; position: relative; }
        .close { position: absolute; top: 15px; right: 20px; font-size: 2rem; cursor: pointer; color: var(--dim); }
        .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; max-height: 200px; overflow-y: auto; }
        .stat-box { background: #1a1d26; padding: 10px; border-radius: 8px; border: 1px solid var(--border); }
    </style>
</head>
<body>
    <div class="header">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form><input type="text" name="search" placeholder="Search player..." style="background:var(--bg); border:1px solid var(--border); padding:8px 15px; border-radius:20px; color:white;" value="{{ search_q }}"></form>
    </div>
    <div class="nav-strip">
        <a href="/" class="nav-btn {% if not cur_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="nav-btn {% if cur_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>

    {% if spotlight %}
    <div class="modal-bg">
        <div class="modal">
            <span class="close" onclick="window.location.href='/'">&times;</span>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" style="margin-bottom:15px;">
            <h2 style="margin:0;">{{ spotlight.username }}</h2>
            <div style="margin: 10px 0;"><span class="badge">{{ spotlight.rank_name }}</span></div>
            <p style="color:var(--dim);">Power Score: {{ spotlight.score }}</p>
            <div class="stat-grid">
                {% for s in spotlight.all_stats %}
                <div class="stat-box">
                    <div style="font-size:0.7rem; color:var(--accent);">{{ s.mode|upper }}</div>
                    <div style="font-weight:700;">{{ s.tier }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="container">
        {% for p in players %}
        <a href="/?search={{p.username}}{% if cur_mode %}&mode={{cur_mode}}{% endif %}" class="player-row">
            <div class="pos">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/48.png" style="border-radius:6px;">
            <div>
                <span style="font-weight:700;">{{ p.username }}</span> <span class="badge" style="margin-left:5px;">{{ p.rank_name }}</span>
                <div style="font-size:0.8rem; color:var(--dim);">Score: {{ p.total_score }}</div>
            </div>
            <div style="color:#4ade80; font-weight:600;">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:var(--accent); font-size:1.4rem;">{{ p.display_tier }}</div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if db_manager.db is None: # FIXED: Explicit check
        return "Database Error. Ensure MONGO_URI is correct.", 500
    
    m_stat = get_maintenance_status()
    if m_stat['active']:
        return f"<body style='background:#0b0c10;color:white;text-align:center;padding:50px;'><h1>🛠️ Maintenance</h1><p>{m_stat['reason']}</p></body>"

    mode_q = request.args.get('mode', '').strip().lower()
    search_q = request.args.get('search', '').strip().lower()
    
    raw = list(db_manager.players.find({"retired": {"$ne": True}}))
    users = {}
    for r in raw:
        u = r['username']
        if u not in users: users[u] = {"username": u, "tiers": [], "kits": {}, "region": r.get('region', 'NA')}
        users[u]["tiers"].append(r['tier'])
        users[u]["kits"][r['gamemode'].lower()] = r['tier']

    processed = []
    for u, data in users.items():
        t_score = calculate_player_score(data["tiers"])
        r_name = get_global_rank_name(data["tiers"])
        
        if mode_q:
            if mode_q in data["kits"]:
                processed.append({
                    "username": u, "display_tier": data["kits"][mode_q],
                    "total_score": t_score, "rank_name": r_name, "region": data['region'],
                    "sort_val": get_tier_value(data["kits"][mode_q])
                })
        else:
            best = max(data["tiers"], key=lambda t: get_tier_value(t))
            processed.append({
                "username": u, "display_tier": best,
                "total_score": t_score, "rank_name": r_name, "region": data['region'],
                "sort_val": t_score
            })

    processed = sorted(processed, key=lambda x: x['sort_val'], reverse=True)
    
    spotlight = None
    if search_q:
        p_data = list(db_manager.players.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if p_data:
            stiers = [x['tier'] for x in p_data]
            spotlight = {
                "username": p_data[0]['username'], "score": calculate_player_score(stiers),
                "rank_name": get_global_rank_name(stiers),
                "all_stats": [{"mode": x['gamemode'], "tier": x['tier']} for x in p_data]
            }

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, cur_mode=mode_q, search_q=search_q, spotlight=spotlight)

# --- STARTUP ---
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000))), daemon=True).start()
    bot.run(TOKEN)
