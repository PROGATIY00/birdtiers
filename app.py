import discord
from discord import app_commands
from flask import Flask, render_template_string, request, jsonify
from pymongo import MongoClient
import os
import threading
import datetime

# --- CONFIG ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 5 for i, t in enumerate(TIER_ORDER)}

# --- DB SETUP ---
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']

def get_global_rank(pts):
    if pts >= 500: return "Combat Grandmaster"
    if pts >= 250: return "Combat Master"
    if pts >= 100: return "Combat Ace"
    if pts >= 50:  return "Combat Specialist"
    return "Rookie"

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Update player tier")
async def rank(interaction: discord.Interaction, player: str, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    
    tier_upper = tier.upper().strip()
    players_col.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {"username": player, "gamemode": mode, "tier": tier_upper, "region": region, "retired": False}},
        upsert=True
    )
    await interaction.response.send_message(f"✅ Updated **{player}** in **{mode}**.")

# --- WEB UI & API ---
app = Flask(__name__)

@app.route('/api/player/<username>')
def get_player_api(username):
    p_data = list(players_col.find({"username": {"$regex": f"^{username}$", "$options": "i"}}))
    if not p_data: return jsonify({"tested": False}), 404
    return jsonify({"username": p_data[0]['username'], "ranks": {d['gamemode']: d['tier'] for d in p_data}})

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        
        /* Navbar & Header */
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 3px solid var(--accent); display: flex; justify-content: space-between; align-items: center; }
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .nav-links a { color: var(--dim); text-decoration: none; font-size: 14px; margin-left: 20px; font-weight: 600; }
        
        /* Old Profile Modal */
        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:1001; display:flex; justify-content:center; align-items:center; backdrop-filter: blur(8px); }
        .profile-modal { background: #11141c; width: 400px; border-radius: 24px; border: 2px solid var(--border); padding: 40px; position: relative; text-align: center; box-shadow: 0 20px 50px rgba(0,0,0,0.5); }
        .close-btn { position: absolute; top: 20px; right: 25px; color: var(--dim); text-decoration: none; font-size: 28px; }
        .modal-avatar { width: 100px; height: 100px; border-radius: 20px; border: 4px solid var(--accent); margin-bottom: 20px; }
        
        .mode-list { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 25px; }
        .mode-item { background: #1a1d26; padding: 12px; border-radius: 12px; border: 1px solid var(--border); text-align: left; }
        .mode-item span { display: block; font-size: 10px; color: var(--dim); text-transform: uppercase; }
        .mode-item b { color: var(--accent); font-size: 15px; }

        .wrapper { max-width: 900px; margin: auto; padding: 40px 20px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 18px 25px; margin-bottom: 12px; display: grid; grid-template-columns: 50px 60px 1fr 100px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.3s; }
        .player-row:hover { border-color: var(--accent); transform: scale(1.02); background: #1c1f2b; }
        .rank-badge { font-size: 11px; padding: 3px 10px; border: 1px solid var(--accent); border-radius: 6px; margin-left: 12px; color: var(--accent); font-weight: 800; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <div class="nav-links">
            <a href="/api-docs">API MENU</a>
            <form action="/" style="display:inline; margin-left:20px;">
                <input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:10px 20px; border-radius:25px; color:white; outline:none;" placeholder="Search Player..." value="{{ search_query }}">
            </form>
        </div>
    </div>

    <!-- RESTORED OLD PROFILE MODAL -->
    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" class="close-btn">&times;</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1 style="margin:0; letter-spacing: -1px;">{{ spotlight.username }}</h1>
            <p style="color:var(--dim); margin: 5px 0;">{{ spotlight.region }} REGION | RANK #{{ spotlight.pos }}</p>
            
            <div class="mode-list">
                {% for stat in spotlight.all_stats %}
                <div class="mode-item">
                    <span>{{ stat.gamemode }}</span>
                    <b>{{ stat.tier }}</b>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        <h2 style="margin-bottom: 30px;">Global Leaderboard</h2>
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row">
            <div style="font-weight:800; color:var(--accent); font-size: 18px;">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:8px;">
            <div><b>{{ p.username }}</b> <span class="rank-badge">{{ p.rank_name }}</span></div>
            <div style="font-weight:700; color:var(--dim);">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:#ffcc00;">{{ p.points }} PTS</div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    search_q = request.args.get('search', '').strip().lower()
    raw_players = list(players_col.find({"retired": False}))
    stats = {}
    
    for p in raw_players:
        u, t, gm, reg = p['username'], p['tier'], p['gamemode'], p.get('region', 'NA')
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "region": reg}
        stats[u]["pts"] += val

    processed = sorted([
        {"username": u, "points": d["pts"], "region": d["region"], "rank_name": get_global_rank(d["pts"])} 
        for u, d in stats.items()
    ], key=lambda x: -x["points"])

    spotlight = None
    if search_q:
        p_data = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if p_data:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {
                "username": p_data[0]['username'],
                "pos": pos,
                "region": p_data[0].get('region', 'NA'),
                "all_stats": [{"gamemode": d['gamemode'], "tier": d['tier']} for d in p_data]
            }

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q)

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
