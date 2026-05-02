"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.4
Clean Notifications | Retired (Grayed-out) | Ban System | Report & Mod Pages | LT3+ Routing
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

# --- SYSTEM LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MagmaTiers")

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
HIGH_RESULTS_ID = os.getenv("HIGH_RESULTS_ID") # Channel for LT3+ updates

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
            self.reports = self.db['reports']
            self.client.admin.command('ping')
            logger.info("✅ Database Connected")
        except Exception as e:
            logger.error(f"❌ Database Offline: {e}")
            self.db = None

db_manager = DatabaseManager(MONGO_URI)

# --- CORE LOGIC ---
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
    if db_manager.db is None: return {"active": True, "reason": "Database connection lost."}
    status = db_manager.settings.find_one({"_id": "maintenance_mode"})
    return status if status else {"active": False, "reason": "None"}

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
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str], reason: str = "Standard Testing"):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Permissions required.", ephemeral=True)
    
    if get_maintenance_status()['active']:
        return await interaction.response.send_message("🛠️ System under maintenance.", ephemeral=True)

    existing_ban = db_manager.players.find_one({"username": player, "banned": True})
    if existing_ban:
        return await interaction.response.send_message(f"❌ **{player}** is banned.", ephemeral=True)

    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message("❌ Invalid tier.", ephemeral=True)

    old_record = db_manager.players.find_one({"username": player, "gamemode": mode.value})
    action = "promoted"
    if old_record:
        action = "demoted" if get_tier_value(tier_upper) < get_tier_value(old_record['tier']) else "promoted"

    db_manager.players.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {
            "tier": tier_upper, "region": region.value, "discord_id": discord_user.id, 
            "last_updated": datetime.datetime.utcnow(), "retired": False, "banned": False
        }},
        upsert=True
    )

    # Routing: LT3 (value 5) or higher goes to HIGH_RESULTS_ID
    target_channel = HIGH_RESULTS_ID if get_tier_value(tier_upper) >= 5 else LOG_CHANNEL_ID
    log_chan = bot.get_channel(int(target_channel))
    if log_chan:
        await log_chan.send(content=f"{discord_user.mention}\n**{player}** {action} to **{tier_upper}** in **{mode.value}**\n**Reason:** {reason}")

    await interaction.response.send_message(f"✅ Updated **{player}**.", ephemeral=True)

@bot.tree.command(name="retire", description="Retire a player in a gamemode")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES])
async def retire(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ No perms.", ephemeral=True)

    res = db_manager.players.update_one({"username": player, "gamemode": mode.value}, {"$set": {"retired": True}})
    if res.matched_count > 0:
        log_chan = bot.get_channel(int(LOG_CHANNEL_ID))
        if log_chan: await log_chan.send(content=f"**{player}** has retired in **{mode.value}**")
        await interaction.response.send_message(f"✅ Retired {player} from {mode.value}.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Player/Mode not found.", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a player")
async def ban(interaction: discord.Interaction, player: str, reason: str = "Terms Violation"):
    if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    db_manager.players.update_many({"username": player}, {"$set": {"banned": True, "retired": True}})
    await interaction.response.send_message(f"🚫 Banned **{player}**. Reason: {reason}")

@bot.tree.command(name="maintenance", description="Toggle maintenance")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Routine Maintenance"):
    if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    db_manager.settings.update_one({"_id": "maintenance_mode"}, {"$set": {"active": active, "reason": reason}}, upsert=True)
    await interaction.response.send_message(f"🛠️ Maintenance **{'ENABLED' if active else 'DISABLED'}**.")

# --- WEB UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS | Leaderboard</title>
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
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 50px 60px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; cursor: pointer; }
        .player-row:hover { border-color: var(--accent); transform: translateY(-2px); }
        .badge { background: rgba(255, 69, 0, 0.1); color: var(--accent); font-size: 0.7rem; font-weight: 800; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--accent); text-transform: uppercase; }
        .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(8px); }
        .modal { background: #11141c; width: 420px; padding: 40px; border-radius: 24px; border: 1px solid var(--border); text-align: center; position: relative; }
        .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 25px; max-height: 250px; overflow-y: auto; }
        .stat-box { background: #1a1d26; padding: 12px; border-radius: 12px; border: 1px solid var(--border); }
        .stat-retired { opacity: 0.4; filter: grayscale(1); border-style: dashed !important; }
        .high-results { background: rgba(255, 69, 0, 0.05); border: 2px solid var(--accent); border-radius: 15px; padding: 20px; margin-bottom: 30px; }
        input, textarea { background: var(--bg); border: 1px solid var(--border); color: white; padding: 10px; border-radius: 8px; width: 100%; margin-top: 5px; }
        .btn { background: var(--accent); color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-block; }
    </style>
</head>
<body>
    {% if maintenance_active %}
    <div style="height:100vh; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center;">
        <h1>🛠️ Under Maintenance</h1><p>{{ maintenance_reason }}</p>
    </div>
    {% else %}
    <div class="header">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <div>
            <a href="/report" class="nav-btn">REPORT</a>
            <form style="display:inline;"><input type="text" name="search" placeholder="Search..." style="width:150px; margin-left:10px;" value="{{ search_q }}"></form>
        </div>
    </div>
    <div class="nav-strip">
        <a href="/" class="nav-btn {% if not cur_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="nav-btn {% if cur_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>

    {% if spotlight %}
    <div class="modal-bg" onclick="window.location.href='/'">
        <div class="modal" onclick="event.stopPropagation()">
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" style="border-radius:15px; border: 3px solid var(--accent); margin-bottom:15px;">
            <h2 style="margin:0;">{{ spotlight.username }}</h2>
            <div style="margin: 10px 0;"><span class="badge">{{ spotlight.rank_name }}</span></div>
            <div class="stat-grid">
                {% for s in spotlight.all_stats %}
                <div class="stat-box {% if s.retired %}stat-retired{% endif %}">
                    <div style="font-size:0.7rem; color:var(--accent); font-weight:800;">{{ s.mode|upper }} {% if s.retired %}(RETIRED){% endif %}</div>
                    <div style="font-weight:700;">{{ s.tier }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="container">
        {% if high_results and not cur_mode and not search_q %}
        <div class="high-results">
            <div style="color:var(--accent); font-weight:800; margin-bottom:15px;">🔥 HIGH RESULTS</div>
            {% for p in high_results %}
            <a href="/?search={{p.username}}" class="player-row" style="border-color: gold;">
                <div style="color:gold;">⭐</div>
                <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:4px;">
                <div><span style="font-weight:700;">{{ p.username }}</span> <span class="badge">{{ p.rank_name }}</span></div>
                <div style="color:var(--dim);">{{ p.region }}</div>
                <div style="text-align:right; font-weight:800; color:var(--accent);">{{ p.display_tier }}</div>
            </a>
            {% endfor %}
        </div>
        {% endif %}

        {% for p in players %}
        <a href="/?search={{p.username}}{% if cur_mode %}&mode={{cur_mode}}{% endif %}" class="player-row">
            <div style="color:var(--dim);">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:4px;">
            <div><span style="font-weight:700;">{{ p.username }}</span> <span class="badge">{{ p.rank_name }}</span></div>
            <div style="color:var(--dim);">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:var(--accent);">{{ p.display_tier }}</div>
        </a>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    m_stat = get_maintenance_status()
    mode_q, search_q = request.args.get('mode', '').lower(), request.args.get('search', '').lower()
    raw = list(db_manager.players.find({"banned": {"$ne": True}}))
    users = {}
    for r in raw:
        u = r['username']
        if u not in users: users[u] = {"username": u, "tiers": [], "kits": {}, "region": r.get('region', 'NA')}
        if not r.get('retired', False):
            users[u]["tiers"].append(r['tier']); users[u]["kits"][r['gamemode'].lower()] = r['tier']

    processed, high_results, spotlight = [], [], None
    if search_q:
        p_data = list(db_manager.players.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}, "banned": {"$ne": True}}))
        if p_data:
            act = [x['tier'] for x in p_data if not x.get('retired', False)]
            spotlight = {"username": p_data[0]['username'], "rank_name": get_global_rank_name(act), "all_stats": [{"mode": x['gamemode'], "tier": x['tier'], "retired": x.get('retired', False)} for x in p_data]}

    for u, data in users.items():
        if not data["tiers"]: continue
        t_score, r_name = calculate_player_score(data["tiers"]), get_global_rank_name(data["tiers"])
        best = max(data["tiers"], key=get_tier_value)
        entry = {"username": u, "display_tier": data["kits"].get(mode_q, best) if mode_q else best, "total_score": t_score, "rank_name": r_name, "region": data['region'], "sort_val": get_tier_value(data["kits"].get(mode_q)) if mode_q else t_score}
        if search_q and search_q not in u.lower(): continue
        if mode_q and mode_q not in data["kits"]: continue
        processed.append(entry)
        if r_name in ["Grandmaster", "Legend"]: high_results.append(entry)

    return render_template_string(HTML_TEMPLATE, players=sorted(processed, key=lambda x: x['sort_val'], reverse=True), high_results=sorted(high_results, key=lambda x: x['total_score'], reverse=True), spotlight=spotlight, all_modes=MODES, cur_mode=mode_q, search_q=search_q, maintenance_active=m_stat['active'], maintenance_reason=m_stat['reason'])

@app.route('/report', methods=['GET', 'POST'])
def report_page():
    if request.method == 'POST':
        db_manager.reports.insert_one({"player": request.form.get('player'), "reason": request.form.get('reason'), "evidence": request.form.get('evidence'), "status": "Pending", "time": datetime.datetime.utcnow()})
        return "<h1>Report Sent!</h1><a href='/'>Back</a>"
    return render_template_string(f"{HTML_TEMPLATE[:500]}<div class='container'><form method='POST' class='modal' style='position:relative; margin:auto;'><h2>Report Player</h2><input name='player' placeholder='Username' required><textarea name='reason' placeholder='Reason' required></textarea><input name='evidence' placeholder='Evidence Link'><br><br><button class='btn'>Submit</button></form></div>")

@app.route('/moderation')
def moderation_page():
    reps = list(db_manager.reports.find({"status": "Pending"}))
    return render_template_string(f"{HTML_TEMPLATE[:500]}<div class='container'><h1>Pending Reports</h1>" + "".join([f"<div class='player-row'><div>{r['player']}</div><div>{r['reason']}</div><form action='/moderation/resolve' method='POST'><input type='hidden' name='id' value='{r['_id']}'><button name='a' value='approve' class='btn'>Approve</button></form></div>" for r in reps]) + "</div>")

@app.route('/moderation/resolve', methods=['POST'])
def resolve_report():
    db_manager.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": request.form.get('a')}})
    return redirect(url_for('moderation_page'))

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
