"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.5.7
- RESTORED: Report Decline/Dismiss System (Mod Panel)
- RESTORED: High Results (LT3+) Spotlight on Home
- RESTORED: Detailed Player Profile Modals (Search/Click)
- RESTORED: Maintenance Mode & Ban/Retire Logic
- RESTORED: Region tracking & Tier sorting
- SPEED: Optimized 15s Auto-Refresh
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
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri)
        self.db = self.client['magmatiers_db']
        self.players = self.db['players']
        self.settings = self.db['settings']
        self.reports = self.db['reports']

db_manager = DatabaseManager(MONGO_URI)

# --- CORE LOGIC ---
def get_tier_value(tier_name):
    try: return TIER_ORDER.index(tier_name.upper().strip()) + 1
    except: return 0

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
    status = db_manager.settings.find_one({"_id": "maintenance_mode"})
    return status if status else {"active": False, "reason": "None"}

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Update player tier")
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str, reason: str = "Standard Testing"):
    if get_maintenance_status()['active']: return await interaction.response.send_message("🛠️ Maintenance.", ephemeral=True)
    if not interaction.user.guild_permissions.manage_roles: return await interaction.response.send_message("❌ No perms.", ephemeral=True)
    
    tier_upper = tier.upper().strip()
    db_manager.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {"tier": tier_upper, "region": region, "discord_id": discord_user.id, "retired": False, "banned": False, "last_updated": datetime.datetime.utcnow()}},
        upsert=True
    )

    chan = HIGH_RESULTS_ID if get_tier_value(tier_upper) >= 5 else LOG_CHANNEL_ID
    log_chan = bot.get_channel(int(chan))
    if log_chan: await log_chan.send(content=f"{discord_user.mention}\n**{player}** updated to **{tier_upper}** in **{mode}**")
    await interaction.response.send_message(f"✅ Updated {player}.", ephemeral=True)

@bot.tree.command(name="maintenance")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "System Update"):
    if not interaction.user.guild_permissions.administrator: return
    db_manager.settings.update_one({"_id": "maintenance_mode"}, {"$set": {"active": active, "reason": reason}}, upsert=True)
    await interaction.response.send_message(f"🛠️ Maintenance: {active}")

# --- WEB UI ---
app = Flask(__name__)

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
    :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #f0f2f5; --dim: #9ba3af; }
    body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
    .header { background: #0f1117; padding: 1rem 4rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; }
    .nav-btn { padding: 6px 15px; border-radius: 8px; background: var(--card); border: 1px solid var(--border); color: white; text-decoration: none; font-size: 0.9rem; }
    .container { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 60px 50px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    .pos-1 { color: #FFD700; font-weight: 800; }
    .badge { border: 1px solid var(--accent); color: var(--accent); font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; }
    .high-results { background: rgba(255, 69, 0, 0.05); border: 2px solid var(--accent); border-radius: 15px; padding: 20px; margin-bottom: 30px; }
    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(5px); }
    .modal { background: #11141c; width: 400px; padding: 30px; border-radius: 20px; border: 1px solid var(--border); text-align: center; }
    .stat-retired { opacity: 0.4; text-decoration: line-through; }
</style>
"""

@app.route('/')
def index():
    m_stat = get_maintenance_status()
    if m_stat['active']: return f"<html><head>{STYLE}</head><body style='display:flex; justify-content:center; align-items:center; height:100vh;'><h1>🛠️ {m_stat['reason']}</h1></body></html>"

    mode_q = request.args.get('mode', '').lower()
    search_q = request.args.get('search', '').lower()
    
    raw = list(db_manager.players.find({"banned": {"$ne": True}}))
    users = {}
    for r in raw:
        u = r['username']
        if u not in users: users[u] = {"username": u, "tiers": [], "kits": {}, "region": r.get('region', 'NA'), "all_raw": []}
        users[u]["all_raw"].append(r)
        if not r.get('retired', False):
            users[u]["tiers"].append(r['tier'])
            users[u]["kits"][r['gamemode'].lower()] = r['tier']

    spotlight = None
    if search_q:
        match = users.get(next((n for n in users if n.lower() == search_q), None))
        if match: spotlight = {"username": match['username'], "rank_name": get_global_rank_name(match['tiers']), "stats": match['all_raw']}

    processed = []
    for u, data in users.items():
        if not data["tiers"] and not spotlight: continue
        best = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        entry = {"username": u, "display_tier": data["kits"].get(mode_q, best), "rank_name": get_global_rank_name(data["tiers"]), "region": data['region'], "score": calculate_player_score(data["tiers"])}
        if mode_q and mode_q not in data["kits"]: continue
        processed.append(entry)

    players = sorted(processed, key=lambda x: x['score'], reverse=True)
    high_p = [p for p in players if p['rank_name'] in ["Grandmaster", "Legend"]]

    template = """
    <html><head><meta http-equiv="refresh" content="15"><title>MagmaTIERS</title>{{ style|safe }}</head>
    <body>
        <div class="header">
            <a href="/" class="logo">Magma<span>TIERS</span></a>
            <form action="/"><input name="search" placeholder="Search..."></form>
            <a href="/report" class="nav-btn">REPORT</a>
        </div>
        {% if spotlight %}
        <div class="modal-bg" onclick="window.location.href='/'"><div class="modal" onclick="event.stopPropagation()">
            <img src="https://minotar.net/helm/{{ spotlight.username }}/64.png" style="margin-bottom:10px;">
            <h2>{{ spotlight.username }}</h2><span class="badge">{{ spotlight.rank_name }}</span>
            <div style="margin-top:20px;">
                {% for s in spotlight.stats %}<div class="{% if s.retired %}stat-retired{% endif %}">{{ s.gamemode }}: <b>{{ s.tier }}</b></div>{% endfor %}
            </div>
        </div></div>
        {% endif %}
        <div class="container">
            {% if not mode_q and not search_q and high_p %}
            <div class="high-results"><b>🔥 HIGH RESULTS</b>
                {% for h in high_p[:3] %}<a href="/?search={{h.username}}" class="player-row" style="border-color:gold;"><div>⭐</div><img src="https://minotar.net/helm/{{h.username}}/32.png"><div>{{h.username}}</div><div>{{h.region}}</div><div style="color:var(--accent)">{{h.display_tier}}</div></a>{% endfor %}
            </div>
            {% endif %}
            {% for p in players %}
            <a href="/?search={{ p.username }}" class="player-row">
                <div class="pos-{{ loop.index }}">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{ p.username }}/32.png">
                <div>{{ p.username }} <span class="badge">{{ p.rank_name }}</span></div>
                <div style="color:var(--dim);">{{ p.region }}</div>
                <div style="text-align:right; color:var(--accent); font-weight:800;">{{ p.display_tier }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(template, style=STYLE, players=players, spotlight=spotlight, high_p=high_p)

@app.route('/report', methods=['GET', 'POST'])
def report():
    if request.method == 'POST':
        db_manager.reports.insert_one({"player": request.form.get('player'), "reason": request.form.get('reason'), "status": "Pending"})
        return redirect('/')
    return render_template_string("<html><head>{{s|safe}}</head><body><div class='container'><form method='POST'><h1>Report</h1><input name='player' placeholder='User'><br><textarea name='reason'></textarea><br><button class='nav-btn'>Send</button></form></div></body></html>", s=STYLE)

@app.route('/moderation')
def moderation():
    reps = list(db_manager.reports.find({"status": "Pending"}))
    template = """
    <html><head>{{s|safe}}</head><body><div class="container"><h1>Moderation Panel</h1>
        {% for r in reps %}
        <div style="background:var(--card); padding:20px; border-radius:12px; margin-bottom:10px; border:1px solid var(--border);">
            <h3>{{ r.player }}</h3><p>{{ r.reason }}</p>
            <form action="/moderation/resolve" method="POST">
                <input type="hidden" name="id" value="{{ r._id }}">
                <button name="a" value="approve" class="nav-btn" style="background:#22c55e; border:none;">Approve</button>
                <button name="a" value="decline" class="nav-btn" style="background:#ef4444; border:none;">Decline</button>
            </form>
        </div>
        {% endfor %}
    </div></body></html>
    """
    return render_template_string(template, s=STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_manager.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect('/moderation')

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
