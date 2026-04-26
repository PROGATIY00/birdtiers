import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session, url_for
from pymongo import MongoClient
import os
import threading

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
# This looks for a setting in Render; if it doesn't find it, it defaults to False
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "False").lower() == "true" # 🟢 SET TO False TO GO PUBLIC

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_DATA = {"HT1":100, "LT1":90, "HT2":80, "LT2":70, "HT3":60, "LT3":50, "HT4":40, "LT4":30, "HT5":20, "LT5":10, "RETIRED":0}

app = Flask(__name__)
app.secret_key = "birdtiers_dev_secret_2026"

# --- DISCORD BOT ---
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()
bot = MyBot()

# --- WEB UI ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS | {% if maint %}MAINTENANCE{% else %}Rankings{% endif %}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        
        /* Gamemode Buttons */
        .mode-nav { display: flex; gap: 10px; flex-wrap: wrap; padding: 20px 50px; background: #0f1117; border-bottom: 1px solid var(--border); }
        .mode-btn { padding: 8px 16px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 14px; transition: 0.2s; }
        .mode-btn:hover, .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }

        .wrapper { max-width: 900px; margin: auto; padding: 40px; }
        .maint-screen { text-align: center; margin-top: 100px; }
        .maint-screen h1 { font-size: 48px; color: var(--accent); }
        
        .player-row { 
            background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 12px 20px; margin-bottom: 10px; 
            display: grid; grid-template-columns: 50px 50px 220px 80px 1fr; align-items: center; 
            text-decoration: none; color: inherit; transition: 0.2s;
        }
        .player-row:hover { border-color: var(--accent); transform: scale(1.01); }
        .retired-player { opacity: 0.35; filter: grayscale(1); }
        .avatar { width: 40px; height: 40px; border-radius: 8px; }
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; font-weight: 600; }
        .na { color: #e74c3c; border: 1px solid #e74c3c; padding: 2px 5px; border-radius: 4px; font-size: 10px; }
        .eu { color: #2ecc71; border: 1px solid #2ecc71; padding: 2px 5px; border-radius: 4px; font-size: 10px; }
    </style>
</head>
<body>
    <div class="navbar"><a href="/" class="logo">BIRD<span>TIERS</span></a></div>
    
    {% if maint and not session.get('admin') %}
    <div class="wrapper maint-screen">
        <h1>🛠️ UNDER MAINTENANCE</h1>
        <p>We are currently updating tiers and refining the system. Check back soon!</p>
        <p style="color:var(--dim)">Follow our Discord for updates.</p>
    </div>
    {% else %}
    
    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}
        <a href="/?mode={{m}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>
        {% endfor %}
    </div>

    <div class="wrapper">
        <h2>🏆 {{ current_mode if current_mode else 'GLOBAL' }} RANKINGS</h2>
        {% for p in players %}
        <a href="https://namemc.com/profile/{{p.username}}" target="_blank" class="player-row {% if not p.is_active %}retired-player{% endif %}">
            <div style="font-weight:800; color:{% if not p.is_active %}var(--dim){% else %}var(--accent){% endif %}">
                {% if not p.is_active %}💀{% else %}#{{ loop.index }}{% endif %}
            </div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" class="avatar">
            <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.points }} {{ 'Pts' if not current_mode else 'Tier' }}</small></div>
            <div><span class="{{ p.region.lower() }}">{{ p.region }}</span></div>
            <div class="tier-badge">{% if not p.is_active %}RETIRED{% else %}{{ p.tier if current_mode else 'ACTIVE' }}{% endif %}</div>
        </a>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    mode_filter = request.args.get('mode')
    players_data = list(players_col.find({}))
    stats = {}

    for p in players_data:
        u = p['username']
        if mode_filter:
            if p['gamemode'] == mode_filter:
                stats[u] = {"points": p['tier'], "region": p.get('region', 'NA'), "active": p['tier'] != "RETIRED", "tier": p['tier']}
        else:
            if u not in stats: stats[u] = {"points": 0, "region": p.get('region', 'NA'), "active": False}
            if p.get('tier') != "RETIRED": stats[u]["active"] = True
            stats[u]["points"] += TIER_DATA.get(p.get('tier'), 0)

    processed = sorted([{"username": u, "points": d['points'], "region": d['region'], "is_active": d['active'], "tier": d.get('tier')} for u, d in stats.items()], key=lambda x: (not x['is_active'], -x['points'] if not mode_filter else 0))
    
    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_filter, maint=MAINTENANCE_MODE)

@app.route('/login')
def login():
    session['admin'] = True # Secret way to bypass maintenance screen
    return redirect('/')

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000))), daemon=True).start()
    bot.run(TOKEN)
