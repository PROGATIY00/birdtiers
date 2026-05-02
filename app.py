"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.8.1
--------------------------------------------
- STATUS: Maintenance Mode fully preserved.
- PROFILE: Upgraded "Player Card" with kit breakdowns.
- FIX: PyMongo truth-testing compatibility (using 'is not None').
- STABILITY: Removed Discord OAuth to prevent module errors.
"""

import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
HIGH_RESULTS_ID = os.getenv("HIGH_RESULTS_ID")

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

# --- DATABASE ---
class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri) if uri else None
        self.db = self.client['magmatiers_db'] if self.client is not None else None
        self.players = self.db['players'] if self.db is not None else None
        self.settings = self.db['settings'] if self.db is not None else None
        self.reports = self.db['reports'] if self.db is not None else None

db_mgr = DatabaseManager(MONGO_URI)

# --- CORE LOGIC ---
def get_tier_value(tier_name):
    try: return TIER_ORDER.index(tier_name.upper().strip()) + 1
    except: return 0

def get_rank_name(tier_list):
    if not tier_list: return "Stone"
    score = sum(get_tier_value(t) for t in tier_list)
    highest = max([get_tier_value(t) for t in tier_list]) if tier_list else 0
    if highest >= 9 and len(tier_list) >= 3: return "Grandmaster"
    if score >= 35: return "Legend"
    if score >= 25: return "Master"
    if score >= 15: return "Elite"
    return "Bronze"

def is_maintenance_active():
    """Checks the database for the maintenance toggle."""
    if db_mgr.settings is None: 
        return {"active": False}
    status = db_mgr.settings.find_one({"_id": "maintenance_mode"})
    return status if status is not None else {"active": False}

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Update a player's tier")
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.manage_roles: return
    t_up = tier.upper().strip()
    db_mgr.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {
            "tier": t_up, 
            "region": region, 
            "discord_id": discord_user.id, 
            "retired": False, 
            "banned": False, 
            "ts": datetime.datetime.utcnow()
        }},
        upsert=True
    )
    chan = HIGH_RESULTS_ID if get_tier_value(t_up) >= 5 else LOG_CHANNEL_ID
    if chan:
        c = bot.get_channel(int(chan))
        if c: await c.send(f"**{player}** updated to **{t_up}** in **{mode}**")
    await interaction.response.send_message(f"✅ Successfully updated **{player}**", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
    :root { --bg: #0b0c10; --card: #14171f; --accent: #ff4500; --text: #f0f2f5; --border: #262932; }
    body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
    .header { background: #0f1117; padding: 1rem 4rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; }
    .container { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 60px 50px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    .player-row:hover { border-color: var(--accent); transform: translateX(5px); }
    .badge { background: rgba(255, 69, 0, 0.1); border: 1px solid var(--accent); color: var(--accent); font-size: 0.7rem; padding: 2px 8px; border-radius: 20px; text-transform: uppercase; font-weight: 800; }
    
    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(8px); }
    .profile-card { background: #11141c; width: 450px; border-radius: 24px; border: 1px solid var(--border); overflow: hidden; }
    .profile-header { background: linear-gradient(45deg, #1a1e29, #262c3a); padding: 40px 20px; text-align: center; border-bottom: 1px solid var(--border); }
    .profile-avatar { width: 80px; height: 80px; border-radius: 15px; border: 3px solid var(--accent); margin-bottom: 15px; }
    .profile-body { padding: 25px; }
    .kit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }
    .kit-item { background: var(--card); padding: 10px; border-radius: 10px; border: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 0.9rem; }
    .retired-text { color: #666; text-decoration: line-through; }
    
    .high-results { background: linear-gradient(90deg, rgba(255,69,0,0.1), transparent); border-left: 4px solid var(--accent); padding: 20px; border-radius: 0 15px 15px 0; margin-bottom: 30px; }
    input { background: var(--card); border: 1px solid var(--border); color: white; padding: 10px 15px; border-radius: 8px; outline: none; }
    .btn { background: var(--accent); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 800; cursor: pointer; text-decoration: none; }
</style>
"""

@app.route('/')
def home():
    # --- MAINTENANCE CHECK ---
    maint = is_maintenance_active()
    if maint.get('active'):
        return f"<html><head>{STYLE}</head><body style='display:flex; justify-content:center; align-items:center; height:100vh;'><div class='container' style='text-align:center;'><h1>🛠️ Maintenance Mode</h1><p>{maint.get('reason', 'We are currently performing updates.')}</p></div></body></html>"

    if db_mgr.players is None: return "Database Error"

    search_q = request.args.get('search', '').lower()
    raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    users = {}

    for r in raw:
        u = r['username']
        if u not in users: users[u] = {"u": u, "tiers": [], "kits": [], "reg": r.get('region', 'NA'), "score": 0}
        users[u]["kits"].append(r)
        if not r.get('retired'):
            users[u]["tiers"].append(r['tier'])

    spotlight = None
    processed = []
    for u, data in users.items():
        data["rank"] = get_rank_name(data["tiers"])
        data["score"] = sum(get_tier_value(t) for t in data["tiers"])
        data["best_tier"] = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        processed.append(data)
        if search_q and u.lower() == search_q: spotlight = data

    players = sorted(processed, key=lambda x: x['score'], reverse=True)
    high_p = [p for p in players if p['rank'] in ["Grandmaster", "Legend", "Master"]]

    template = """
    <html><head><meta http-equiv="refresh" content="15"><title>MagmaTIERS</title>{{ s|safe }}</head>
    <body>
        <div class="header">
            <a href="/" style="color:white; text-decoration:none; font-weight:800; font-size:1.7rem;">Magma<span style="color:var(--accent);">TIERS</span></a>
            <form action="/" style="margin:0;"><input name="search" placeholder="Search Player..."></form>
        </div>

        {% if spot %}
        <div class="modal-bg" onclick="window.location.href='/'">
            <div class="profile-card" onclick="event.stopPropagation()">
                <div class="profile-header">
                    <img src="https://minotar.net/helm/{{ spot.u }}/100.png" class="profile-avatar">
                    <h2 style="margin:0;">{{ spot.u }}</h2>
                    <span class="badge" style="margin-top:10px; display:inline-block;">{{ spot.rank }}</span>
                </div>
                <div class="profile-body">
                    <div style="display:flex; justify-content:space-between; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:10px;">
                        <span>Region: <b>{{ spot.reg }}</b></span>
                        <span>Points: <b style="color:var(--accent)">{{ spot.score }}</b></span>
                    </div>
                    <div class="kit-grid">
                        {% for k in spot.kits %}
                        <div class="kit-item {% if k.retired %}retired-text{% endif %}">
                            <span>{{ k.gamemode }}</span>
                            <b style="color:var(--accent)">{{ k.tier }}</b>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="container">
            {% if not search and high_p %}
            <div class="high-results">
                <div style="font-weight:800; color:var(--accent); margin-bottom:15px; letter-spacing:1px;">TOP RANKED PLAYERS</div>
                {% for h in high_p[:3] %}
                <a href="/?search={{h.u}}" class="player-row" style="border-color: #ffd700;">
                    <div style="color:#ffd700; font-weight:800;">TOP</div>
                    <img src="https://minotar.net/helm/{{h.u}}/32.png">
                    <div>{{h.u}} <span class="badge">{{h.rank}}</span></div>
                    <div style="color:#9ba3af;">{{h.reg}}</div>
                    <div style="text-align:right; color:var(--accent); font-weight:800;">{{h.best_tier}}</div>
                </a>
                {% endfor %}
            </div>
            {% endif %}

            {% for p in players %}
            <a href="/?search={{ p.u }}" class="player-row">
                <div style="font-weight:800; color:rgba(255,255,255,0.2);">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{ p.u }}/32.png">
                <div>{{ p.u }} <span class="badge">{{ p.rank }}</span></div>
                <div style="color:#9ba3af;">{{ p.reg }}</div>
                <div style="text-align:right; color:var(--accent); font-weight:800;">{{ p.best_tier }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(template, s=STYLE, players=players, spot=spotlight, high_p=high_p, search=search_q)

@app.route('/moderation')
def moderation():
    reps = list(db_mgr.reports.find({"status": "Pending"}))
    return render_template_string("""
        <html><head>{{ s|safe }}</head><body><div class="container">
        <h1>Reports Queue</h1>
        {% for r in reps %}
        <div style="background:var(--card); padding:20px; border-radius:12px; margin-bottom:10px; border:1px solid var(--border);">
            <h3>{{ r.player }}</h3><p>{{ r.reason }}</p>
            <form action="/moderation/resolve" method="POST">
                <input type="hidden" name="id" value="{{ r._id }}">
                <button name="a" value="approve" class="btn">Approve</button>
                <button name="a" value="decline" class="btn" style="background:#444;">Decline</button>
            </form>
        </div>
        {% endfor %}
        </div></body></html>
    """, s=STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_mgr.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect(url_for('moderation'))

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
