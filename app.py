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
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "False").lower() == "true"

# MongoDB Setup
client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
partners_col = db_mongo['partners']

# Constants
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"] 
TIER_DATA = {"HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10}

def get_global_rank(pts):
    if pts >= 400: return "GRAND MASTER", "rank-grand-master"
    if pts >= 200: return "COMBAT MASTER", "rank-combat-master"
    return "COMBAT ACE", "rank-combat-ace"

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()
bot = MagmaBot()

# Commands: /rank, /retire, /partner
@bot.tree.command(name="rank", description="Set a player's tier")
async def rank(interaction: discord.Interaction, name: str, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.administrator: return
    players_col.update_one(
        {"username": {"$regex": f"^{name}$", "$options": "i"}, "gamemode": mode},
        {"$set": {"username": name, "gamemode": mode, "tier": tier.upper(), "region": region.upper(), "retired": False}},
        upsert=True
    )
    await interaction.response.send_message(f"🌋 Updated **{name}**", ephemeral=True)

@bot.tree.command(name="partner", description="Manage partners")
async def partner(interaction: discord.Interaction, action: str, name: str, img: str = None, link: str = "#"):
    if not interaction.user.guild_permissions.administrator: return
    if action.lower() == "add":
        partners_col.update_one({"name": name}, {"$set": {"img": img, "link": link}}, upsert=True)
        await interaction.response.send_message(f"🤝 Added {name}")
    else:
        partners_col.delete_one({"name": name})
        await interaction.response.send_message(f"🗑️ Removed {name}")

# --- WEB UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MAGMATIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        
        /* NAVBAR */
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; letter-spacing: 1px; }
        .logo span { color: var(--accent); }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; }

        /* MODE NAV */
        .mode-nav { display: flex; gap: 8px; flex-wrap: wrap; padding: 15px 50px; background: #0f1117; border-bottom: 1px solid var(--border); justify-content: center; }
        .mode-btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 12px; font-weight: 600; }
        .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }

        /* THE INSANE HT1 ANIMATION */
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); border-radius: 14px; animation: rotate 2s linear infinite; }
        .insane-tier { color: #fff !important; text-shadow: 0 0 10px #ff4500; font-weight: 900; }

        /* GLOBAL RANKS */
        .global-rank { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; margin-left: 8px; }
        .rank-grand-master { background: rgba(255, 0, 0, 0.2); color: #ff0000; border: 1px solid #ff0000; box-shadow: 0 0 10px rgba(255,0,0,0.2); }
        .rank-combat-master { background: rgba(255, 140, 0, 0.2); color: #ff8c00; border: 1px solid #ff8c00; }

        /* PROFILE SPOTLIGHT */
        .profile-card { background: linear-gradient(145deg, #1f1412, #14171f); border: 2px solid var(--accent); border-radius: 18px; padding: 25px; margin-bottom: 30px; display: flex; gap: 25px; align-items: center; }
        .tier-box { background: rgba(0,0,0,0.4); padding: 10px; border-radius: 8px; font-size: 11px; border: 1px solid var(--border); text-align: center; }
        .legacy-tier { text-decoration: line-through; opacity: 0.5; font-style: italic; }

        /* PARTNERS */
        .partners-section { margin-top: 50px; padding: 40px; border-top: 1px solid var(--border); background: #0f1117; text-align: center; }
        .partner-img { height: 45px; filter: grayscale(1); opacity: 0.6; transition: 0.3s; margin: 0 20px; }
        .partner-img:hover { filter: grayscale(0); opacity: 1; transform: scale(1.1); }

        .wrapper { max-width: 950px; margin: auto; padding: 25px; min-height: 60vh; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 45px 50px 1fr 70px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 6px; text-align: center; font-weight: 800; font-size: 13px; color: var(--accent); }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">MAGMA<span>TIERS</span></a>
        <form><input type="text" name="search" class="search-input" placeholder="Find player..." value="{{ search_query }}"></form>
    </div>

    {% if maint %}<div class="wrapper" style="text-align:center;"><h1>🛠️ Maintenance</h1></div>
    {% else %}
    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn {% if current_mode.lower() == m.lower() %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>

    <div class="wrapper">
        {% if spotlight %}
        <div class="profile-card">
            <div style="text-align:center;">
                <img src="https://minotar.net/helm/{{spotlight.username}}/80.png" style="border-radius:12px;">
                <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="display:block; font-size:10px; color:var(--dim); margin-top:5px; text-decoration:none;">NameMC</a>
            </div>
            <div style="flex-grow:1;">
                <h1 style="margin:0;">{{ spotlight.username }}</h1>
                <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap:10px; margin-top:10px;">
                    {% for r in spotlight.ranks %}<div class="tier-box"><span>{{r.gamemode}}</span><br><b class="{% if r.retired %}legacy-tier{% endif %}">{{r.tier}}</b></div>{% endfor %}
                </div>
            </div>
        </div>
        {% endif %}

        {% for p in players %}
        {% set is_insane = p.tier in ['HT1', 'LT1'] %}
        <a href="/?search={{p.username}}" class="player-row {% if is_insane %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div>
                <b class="{% if is_insane %}insane-tier{% endif %}">{{ p.username }}</b>
                <span class="global-rank {{ p.rank_id }}">{{ p.rank_name }}</span>
                <br><small style="color:var(--dim)">{{ p.points }} Pts</small>
            </div>
            <div style="font-size:13px; color:var(--dim); font-weight:800;">{{ p.region }}</div>
            <div class="tier-badge {% if is_insane %}insane-tier{% endif %}">{{ p.tier }}</div>
        </a>
        {% endfor %}
    </div>

    <div class="partners-section">
        <div style="color:var(--dim); font-size:12px; margin-bottom:20px; text-transform:uppercase;">Official Partners</div>
        {% for partner in partners %}
        <a href="{{ partner.link }}" target="_blank"><img src="{{ partner.img }}" class="partner-img"></a>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    mode_filter, search_q = request.args.get('mode', ''), request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    partners_data = list(partners_col.find({}))
    
    stats = {}
    for p in players_data:
        u, gm, tier, ret = p['username'], p['gamemode'], p['tier'], p.get('retired', False)
        val = TIER_DATA.get(tier, 0)
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "retired": True, "tier": "N/A"}
        if mode_filter:
            if gm.lower() == mode_filter.lower(): stats[u].update({"pts": val, "tier": tier, "retired": ret})
        else:
            if not ret: (stats[u].update({"retired": False}), stats[u].update({"pts": stats[u]["pts"] + val}))
            else: stats[u]["pts"] += (val * 0.1)

    processed = []
    for u, d in stats.items():
        if d['pts'] <= 0: continue
        r_name, r_id = get_global_rank(d['pts'])
        processed.append({"username": u, "points": int(d['pts']), "region": d['region'], "retired": d['retired'], "tier": d['tier'], "rank_name": r_name, "rank_id": r_id})

    processed = sorted(processed, key=lambda x: (x['retired'], -x['points']))
    
    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res: spotlight = {"username": res[0]['username'], "ranks": res}

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_filter, search_query=search_q, partners=partners_data, maint=MAINTENANCE_MODE, spotlight=spotlight)

# Start Bot in background
threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
