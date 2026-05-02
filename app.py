"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.5.3
- Restored: Maintenance Mode & Profile Modals
- Restored: Ban/Retire logic visibility
- Fixed: Public MOD button remains hidden
"""

import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import threading
import datetime
import logging

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
HIGH_RESULTS_ID = os.getenv("HIGH_RESULTS_ID")

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

# --- DATABASE MANAGER ---
class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri)
        self.db = self.client['magmatiers_db']
        self.players = self.db['players']
        self.settings = self.db['settings']
        self.reports = self.db['reports']

db_manager = DatabaseManager(MONGO_URI)

# --- UTILITIES ---
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
    if get_maintenance_status()['active']: return await interaction.response.send_message("🛠️ Maintenance Mode is active.", ephemeral=True)
    if not interaction.user.guild_permissions.manage_roles: return await interaction.response.send_message("❌ No perms.", ephemeral=True)
    
    tier_upper = tier.upper().strip()
    db_manager.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {"tier": tier_upper, "region": region, "discord_id": discord_user.id, "retired": False, "banned": False}},
        upsert=True
    )

    chan = HIGH_RESULTS_ID if get_tier_value(tier_upper) >= 5 else LOG_CHANNEL_ID
    log_chan = bot.get_channel(int(chan))
    if log_chan: await log_chan.send(content=f"{discord_user.mention}\n**{player}** updated to **{tier_upper}** in **{mode}**\n**Reason:** {reason}")
    await interaction.response.send_message(f"✅ Updated {player}.", ephemeral=True)

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Updating System"):
    if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    db_manager.settings.update_one({"_id": "maintenance_mode"}, {"$set": {"active": active, "reason": reason}}, upsert=True)
    await interaction.response.send_message(f"🛠️ Maintenance is now **{'ON' if active else 'OFF'}**.")

# --- WEB UI ---
app = Flask(__name__)

BASE_STYLE = """
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
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 80px 60px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    .player-row:hover { border-color: var(--accent); transform: translateY(-2px); }
    .badge { background: rgba(255, 69, 0, 0.1); color: var(--accent); font-size: 0.7rem; font-weight: 800; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--accent); text-transform: uppercase; }
    .pos-1 { color: #FFD700; font-weight: 800; }
    .pos-2 { color: #C0C0C0; font-weight: 800; }
    .pos-3 { color: #CD7F32; font-weight: 800; }
    .pos-default { color: #a19d94; font-weight: 600; }
    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(8px); }
    .modal { background: #11141c; width: 420px; padding: 40px; border-radius: 24px; border: 1px solid var(--border); text-align: center; }
    .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 25px; }
    .stat-box { background: #1a1d26; padding: 12px; border-radius: 12px; border: 1px solid var(--border); }
    .stat-retired { opacity: 0.4; filter: grayscale(1); border-style: dashed; }
    input, textarea { background: var(--card); border: 1px solid var(--border); color: white; padding: 12px; border-radius: 8px; width: 100%; margin-top: 8px; font-family: inherit; }
    .btn { background: var(--accent); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-block; margin-top: 15px; }
    .card { background: var(--card); border: 1px solid var(--border); padding: 25px; border-radius: 15px; }
</style>
"""

NAV_HTML = """
<div class="header">
    <a href="/" class="logo">Magma<span>TIERS</span></a>
    <div>
        <form action="/" method="GET" style="display:inline;">
            <input type="text" name="search" placeholder="Search player..." style="width:150px; padding:6px; margin-right:10px;">
        </form>
        <a href="/report" class="nav-btn">REPORT</a>
    </div>
</div>
"""

@app.route('/')
def index():
    m_stat = get_maintenance_status()
    if m_stat['active']: return f"<html><head>{BASE_STYLE}</head><body style='display:flex; justify-content:center; align-items:center; height:100vh;'><h1>🛠️ {m_stat['reason']}</h1></body></html>"

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

    # Profile Modal Logic
    spotlight = None
    if search_q:
        match = users.get(next((name for name in users if name.lower() == search_q), None))
        if match:
            spotlight = {
                "username": match['username'],
                "rank_name": get_global_rank_name(match['tiers']),
                "stats": [{"mode": x['gamemode'], "tier": x['tier'], "retired": x.get('retired', False)} for x in match['all_raw']]
            }

    processed = []
    for u, data in users.items():
        if not data["tiers"] and not spotlight: continue
        best = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        entry = {
            "username": u, "display_tier": data["kits"].get(mode_q, best) if mode_q else best,
            "total_score": calculate_player_score(data["tiers"]),
            "rank_name": get_global_rank_name(data["tiers"]), "region": data['region'],
            "sort_val": get_tier_value(data["kits"].get(mode_q)) if mode_q else calculate_player_score(data["tiers"])
        }
        if mode_q and mode_q not in data["kits"]: continue
        processed.append(entry)

    players = sorted(processed, key=lambda x: x['sort_val'], reverse=True)

    template = """
    <html><head><title>MagmaTIERS</title>{{ style|safe }}</head>
    <body>
        {{ nav|safe }}
        {% if spotlight %}
        <div class="modal-bg" onclick="window.location.href='/'">
            <div class="modal" onclick="event.stopPropagation()">
                <img src="https://minotar.net/helm/{{ spotlight.username }}/80.png" style="border-radius:12px; margin-bottom:15px;">
                <h2 style="margin:0;">{{ spotlight.username }}</h2>
                <span class="badge">{{ spotlight.rank_name }}</span>
                <div class="stat-grid">
                    {% for s in spotlight.stats %}
                    <div class="stat-box {% if s.retired %}stat-retired{% endif %}">
                        <div style="font-size:0.7rem; color:var(--accent);">{{ s.mode|upper }}</div>
                        <div style="font-weight:700;">{{ s.tier }}</div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endif %}
        <div class="nav-strip">
            <a href="/" class="nav-btn {% if not mode_q %}active{% endif %}">GLOBAL</a>
            {% for m in all_modes %}
            <a href="/?mode={{ m|lower }}" class="nav-btn {% if mode_q == m|lower %}active{% endif %}">{{ m|upper }}</a>
            {% endfor %}
        </div>
        <div class="container">
            {% for p in players %}
            <a href="/?search={{ p.username }}" class="player-row">
                <div class="pos-{{ '1' if loop.index == 1 else '2' if loop.index == 2 else '3' if loop.index == 3 else 'default' }}">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{ p.username }}/40.png" style="border-radius:4px;">
                <div><span style="font-weight:700;">{{ p.username }}</span> <span class="badge">{{ p.rank_name }}</span></div>
                <div style="color:var(--dim);">{{ p.region }}</div>
                <div style="text-align:right; font-weight:800; color:var(--accent);">{{ p.display_tier }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(template, style=BASE_STYLE, nav=NAV_HTML, players=players, spotlight=spotlight, all_modes=MODES, mode_q=mode_q)

@app.route('/report', methods=['GET', 'POST'])
def report_page():
    if request.method == 'POST':
        db_manager.reports.insert_one({"player": request.form.get('player'), "reason": request.form.get('reason'), "evidence": request.form.get('evidence'), "status": "Pending", "time": datetime.datetime.utcnow()})
        return render_template_string("<html><head>{{ s|safe }}</head><body>{{ n|safe }}<div class='container'><h1>Report Sent!</h1><a href='/' class='btn'>Back</a></div></body></html>", s=BASE_STYLE, n=NAV_HTML)
    return render_template_string("<html><head>{{ style|safe }}</head><body>{{ nav|safe }}<div class='container' style='max-width:500px;'><h1>Report</h1><div class='card'><form method='POST'><label>Player</label><input name='player' required><label>Reason</label><textarea name='reason' required></textarea><label>Evidence</label><input name='evidence'><button type='submit' class='btn'>Submit</button></form></div></div></body></html>", style=BASE_STYLE, nav=NAV_HTML)

@app.route('/moderation')
def moderation_page():
    reps = list(db_manager.reports.find({"status": "Pending"}))
    return render_template_string("<html><head>{{ style|safe }}</head><body>{{ nav|safe }}<div class='container'><h1>Moderation</h1>{% for r in reps %}<div class='card' style='margin-bottom:10px;'><h3>{{ r.player }}</h3><p>{{ r.reason }}</p><form action='/moderation/resolve' method='POST'><input type='hidden' name='id' value='{{ r._id }}'><button name='a' value='approve' class='btn'>Approve</button></form></div>{% endfor %}</div></body></html>", style=BASE_STYLE, nav=NAV_HTML, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve_report():
    db_manager.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": request.form.get('a')}})
    return redirect(url_for('moderation_page'))

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
