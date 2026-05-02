"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.7.3
--------------------------------------------
- CRITICAL: Fixed PyMongo 'NotImplementedError' by using 'is None'.
- LOGIN: Discord OAuth2 Integration for Mod Panel.
- FEATURES: Decline/Dismiss, Profiles, High Results, Maintenance.
- PERFORMANCE: 15s Auto-refresh meta-tag.
"""

import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for, session
from flask_discord import DiscordOAuth2Session, requires_authorization
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

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")

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

def calculate_score(tier_list):
    return sum(get_tier_value(t) for t in tier_list)

def get_rank_name(tier_list):
    if not tier_list: return "Stone"
    score = calculate_score(tier_list)
    highest = max([get_tier_value(t) for t in tier_list]) if tier_list else 0
    if highest >= 9 and len(tier_list) >= 3: return "Grandmaster"
    if score >= 35: return "Legend"
    if score >= 25: return "Master"
    if score >= 15: return "Elite"
    return "Bronze"

def is_maintenance_active():
    if db_mgr.settings is None: return {"active": True, "reason": "Database Offline"}
    status = db_mgr.settings.find_one({"_id": "maintenance_mode"})
    if status is not None: return status
    return {"active": False, "reason": "None"}

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Update player tier")
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.manage_roles: return
    t_up = tier.upper().strip()
    db_mgr.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {"tier": t_up, "region": region, "discord_id": discord_user.id, "retired": False, "banned": False, "ts": datetime.datetime.utcnow()}},
        upsert=True
    )
    chan = HIGH_RESULTS_ID if get_tier_value(t_up) >= 5 else LOG_CHANNEL_ID
    if chan:
        c = bot.get_channel(int(chan))
        if c: await c.send(f"**{player}** updated to **{t_up}** in **{mode}**")
    await interaction.response.send_message(f"✅ Updated {player}", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

app.config["DISCORD_CLIENT_ID"] = CLIENT_ID
app.config["DISCORD_CLIENT_SECRET"] = CLIENT_SECRET
app.config["DISCORD_REDIRECT_URI"] = REDIRECT_URI
app.config["DISCORD_BOT_TOKEN"] = TOKEN

discord_oauth = DiscordOAuth2Session(app)

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
    :root { --bg: #0b0c10; --card: #14171f; --accent: #ff4500; --text: #f0f2f5; --border: #262932; }
    body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
    .header { background: #0f1117; padding: 1rem 4rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; }
    .nav-btn { padding: 6px 15px; border-radius: 8px; background: var(--card); border: 1px solid var(--border); color: white; text-decoration: none; font-size: 0.9rem; font-weight: 600; }
    .container { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 60px 50px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; }
    .badge { border: 1px solid var(--accent); color: var(--accent); font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; }
    .high-results { background: rgba(255, 69, 0, 0.05); border: 2px solid var(--accent); border-radius: 15px; padding: 20px; margin-bottom: 30px; }
    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(5px); }
    .modal { background: #11141c; width: 400px; padding: 30px; border-radius: 20px; border: 1px solid var(--border); text-align: center; }
    .retired { opacity: 0.4; text-decoration: line-through; }
</style>
"""

@app.route("/login")
def login(): return discord_oauth.create_session()

@app.route("/callback")
def callback():
    discord_oauth.callback()
    return redirect(url_for("home"))

@app.route('/')
def home():
    maint = is_maintenance_active()
    if maint.get('active'): return f"<html><head>{STYLE}</head><body><div class='container'><h1>🛠️ {maint.get('reason')}</h1></div></body></html>"

    if db_mgr.players is None: return "DB Offline"

    mode_q = request.args.get('mode', '').lower()
    search_q = request.args.get('search', '').lower()
    
    raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    users = {}
    for r in raw:
        u = r['username']
        if u not in users: users[u] = {"u": u, "tiers": [], "kits": {}, "reg": r.get('region', 'NA'), "all": []}
        users[u]["all"].append(r)
        if not r.get('retired'):
            users[u]["tiers"].append(r['tier'])
            users[u]["kits"][r['gamemode'].lower()] = r['tier']

    spotlight = None
    if search_q:
        match = users.get(next((n for n in users if n.lower() == search_q), None))
        if match:
            match['rn'] = get_rank_name(match['tiers'])
            spotlight = match

    processed = []
    for u, data in users.items():
        best = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        entry = {"u": u, "t": data["kits"].get(mode_q, best), "rn": get_rank_name(data["tiers"]), "reg": data['reg'], "score": calculate_score(data["tiers"])}
        if mode_q and mode_q not in data["kits"]: continue
        processed.append(entry)

    players = sorted(processed, key=lambda x: x['score'], reverse=True)
    high_p = [p for p in players if p['rn'] in ["Grandmaster", "Legend", "Master"]]

    template = """
    <html><head><meta http-equiv="refresh" content="15"><title>MagmaTIERS</title>{{ s|safe }}</head>
    <body>
        <div class="header">
            <a href="/" style="color:white; text-decoration:none; font-weight:800; font-size:1.5rem;">Magma<span style="color:var(--accent);">TIERS</span></a>
            <div style="display:flex; gap:10px;">
                <form action="/"><input name="search" placeholder="Search..." style="background:var(--card); border:1px solid var(--border); color:white; padding:5px; border-radius:5px;"></form>
                <a href="/moderation" class="nav-btn">MODERATION</a>
            </div>
        </div>
        {% if spot %}
        <div class="modal-bg" onclick="window.location.href='/'"><div class="modal" onclick="event.stopPropagation()">
            <img src="https://minotar.net/helm/{{ spot.u }}/64.png" style="margin-bottom:10px;">
            <h2>{{ spot.u }}</h2><span class="badge">{{ spot.rn }}</span>
            <div style="margin-top:20px;">
                {% for entry in spot.all %}<div class="{% if entry.retired %}retired{% endif %}">{{ entry.gamemode }}: <b>{{ entry.tier }}</b></div>{% endfor %}
            </div>
        </div></div>
        {% endif %}
        <div class="container">
            {% if not mode and not search and high %}
            <div class="high-results"><b>🔥 HIGH RESULTS</b>
                {% for h in high[:3] %}<div class="player-row" style="border-color: gold;"><div>⭐</div><img src="https://minotar.net/helm/{{h.u}}/32.png"><div>{{h.u}}</div><div>{{h.reg}}</div><div style="color:var(--accent)">{{h.t}}</div></div>{% endfor %}
            </div>
            {% endif %}
            {% for p in players %}
            <a href="/?search={{ p.u }}" class="player-row">
                <div style="font-weight:800; color:var(--accent);">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{ p.u }}/32.png">
                <div>{{ p.u }} <span class="badge">{{ p.rn }}</span></div>
                <div style="color:#9ba3af;">{{ p.reg }}</div>
                <div style="text-align:right; color:var(--accent); font-weight:800;">{{ p.t }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(template, s=STYLE, players=players, spot=spotlight, high=high_p, mode=mode_q, search=search_q)

@app.route('/moderation')
@requires_authorization
def moderation():
    reps = list(db_mgr.reports.find({"status": "Pending"}))
    template = """
    <html><head>{{ s|safe }}</head><body>
    <div class="header"><a href="/" style="color:white; text-decoration:none;">MagmaTIERS</a> <a href="/logout" class="nav-btn">LOGOUT</a></div>
    <div class="container">
        <h1>Reports Queue</h1>
        {% for r in reps %}
        <div style="background:var(--card); padding:20px; border-radius:12px; margin-bottom:10px; border:1px solid var(--border);">
            <h3>{{ r.player }}</h3><p>{{ r.reason }}</p>
            <form action="/moderation/resolve" method="POST">
                <input type="hidden" name="id" value="{{ r._id }}">
                <button name="a" value="approve" class="nav-btn" style="background:#22c55e; border:none; cursor:pointer;">Approve</button>
                <button name="a" value="decline" class="nav-btn" style="background:#ef4444; border:none; cursor:pointer;">Decline</button>
            </form>
        </div>
        {% endfor %}
    </div></body></html>
    """
    return render_template_string(template, s=STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
@requires_authorization
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_mgr.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect(url_for('moderation'))

@app.route("/logout")
def logout():
    discord_oauth.revoke()
    return redirect(url_for("home"))

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
