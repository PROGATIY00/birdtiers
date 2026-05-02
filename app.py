"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.5
- Colored Leaderboard Positions (#1 Gold, #2 Silver, #3 Bronze, #4+ Iron)
- Full Report & Moderation System
- LT3+ Updates Routed to HIGH_RESULTS_ID
- Banned/Retired Logic (Grayed out in Profiles)
- Unified Web UI Styling
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
HIGH_RESULTS_ID = os.getenv("HIGH_RESULTS_ID")

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

# --- CORE UTILITIES ---
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
    
    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message("❌ Invalid tier format.", ephemeral=True)

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

    # LT3 is index 4 (Value 5). LT3+ = Value >= 5.
    target_channel = HIGH_RESULTS_ID if get_tier_value(tier_upper) >= 5 else LOG_CHANNEL_ID
    log_chan = bot.get_channel(int(target_channel))
    if log_chan:
        await log_chan.send(content=f"{discord_user.mention}\n**{player}** {action} to **{tier_upper}** in **{mode.value}**\n**Reason:** {reason}")

    await interaction.response.send_message(f"✅ Updated **{player}**.", ephemeral=True)

@bot.tree.command(name="retire", description="Mark a player as retired")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES])
async def retire(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Permissions required.", ephemeral=True)
    db_manager.players.update_one({"username": player, "gamemode": mode.value}, {"$set": {"retired": True}})
    log_chan = bot.get_channel(int(LOG_CHANNEL_ID))
    if log_chan: await log_chan.send(content=f"**{player}** has retired in **{mode.value}**")
    await interaction.response.send_message(f"✅ **{player}** retired from **{mode.value}**.", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a player from rankings")
async def ban(interaction: discord.Interaction, player: str, reason: str = "Violation"):
    if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    db_manager.players.update_many({"username": player}, {"$set": {"banned": True, "retired": True}})
    await interaction.response.send_message(f"🚫 Banned **{player}**. Reason: {reason}")

# --- WEB UI ---
app = Flask(__name__)

# Global CSS and Layout
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
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 80px 60px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; }
    .badge { background: rgba(255, 69, 0, 0.1); color: var(--accent); font-size: 0.7rem; font-weight: 800; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--accent); text-transform: uppercase; }
    
    /* COLORED RANKS */
    .pos-1 { color: #FFD700; font-weight: 800; } /* Gold */
    .pos-2 { color: #C0C0C0; font-weight: 800; } /* Silver */
    .pos-3 { color: #CD7F32; font-weight: 800; } /* Bronze */
    .pos-default { color: #a19d94; font-weight: 600; } /* Iron */

    input, textarea { background: var(--card); border: 1px solid var(--border); color: white; padding: 12px; border-radius: 8px; width: 100%; margin-top: 8px; }
    .btn { background: var(--accent); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-block; margin-top: 15px; }
    .card { background: var(--card); border: 1px solid var(--border); padding: 25px; border-radius: 15px; }
    .stat-retired { opacity: 0.4; filter: grayscale(1); border-style: dashed !important; }
</style>
"""

NAV_HTML = """
<div class="header">
    <a href="/" class="logo">Magma<span>TIERS</span></a>
    <div>
        <a href="/report" class="nav-btn">REPORT</a>
        <a href="/moderation" class="nav-btn" style="margin-left:5px;">MOD</a>
    </div>
</div>
"""

@app.route('/')
def index():
    m_stat = get_maintenance_status()
    mode_q = request.args.get('mode', '').lower()
    search_q = request.args.get('search', '').lower()
    
    raw = list(db_manager.players.find({"banned": {"$ne": True}}))
    users = {}
    for r in raw:
        u = r['username']
        if u not in users: users[u] = {"username": u, "tiers": [], "kits": {}, "region": r.get('region', 'NA')}
        if not r.get('retired', False):
            users[u]["tiers"].append(r['tier'])
            users[u]["kits"][r['gamemode'].lower()] = r['tier']

    processed = []
    for u, data in users.items():
        if not data["tiers"]: continue
        t_score = calculate_player_score(data["tiers"])
        r_name = get_global_rank_name(data["tiers"])
        best = max(data["tiers"], key=get_tier_value)
        
        entry = {
            "username": u, 
            "display_tier": data["kits"].get(mode_q, best) if mode_q else best,
            "total_score": t_score, "rank_name": r_name, "region": data['region'],
            "sort_val": get_tier_value(data["kits"].get(mode_q)) if mode_q else t_score
        }
        if search_q and search_q not in u.lower(): continue
        if mode_q and mode_q not in data["kits"]: continue
        processed.append(entry)

    players = sorted(processed, key=lambda x: x['sort_val'], reverse=True)

    return render_template_string(f"""
        {BASE_STYLE}
        {NAV_HTML}
        <div class="nav-strip">
            <a href="/" class="nav-btn {'active' if not mode_q else ''}">GLOBAL</a>
            {% for m in all_modes %}<a href="/?mode={{{{m.lower()}}}}" class="nav-btn {'active' if mode_q == m.lower() else ''}">{{{{m|upper}}}}</a>{% endfor %}
        </div>
        <div class="container">
            {% for p in players %}
            <div class="player-row">
                <div class="pos-{{{{ '1' if loop.index == 1 else '2' if loop.index == 2 else '3' if loop.index == 3 else 'default' }}}}">
                    #{{{{ loop.index }}}}
                </div>
                <img src="https://minotar.net/helm/{{{{p.username}}}}/40.png" style="border-radius:4px;">
                <div><span style="font-weight:700;">{{{{ p.username }}}}</span> <span class="badge">{{{{ p.rank_name }}}}</span></div>
                <div style="color:var(--dim);">{{{{ p.region }}}}</div>
                <div style="text-align:right; font-weight:800; color:var(--accent);">{{{{ p.display_tier }}}}</div>
            </div>
            {% endfor %}
        </div>
    """, players=players, all_modes=MODES, mode_q=mode_q)

@app.route('/report', methods=['GET', 'POST'])
def report_page():
    if request.method == 'POST':
        db_manager.reports.insert_one({
            "player": request.form.get('player'),
            "reason": request.form.get('reason'),
            "evidence": request.form.get('evidence'),
            "status": "Pending",
            "time": datetime.datetime.utcnow()
        })
        return render_template_string(f"{BASE_STYLE}{NAV_HTML}<div class='container'><h1>Report Submitted!</h1><a href='/' class='btn'>Return Home</a></div>")
    
    return render_template_string(f"""
        {BASE_STYLE}
        {NAV_HTML}
        <div class="container" style="max-width: 600px;">
            <h1>Report a Player</h1>
            <div class="card">
                <form method="POST">
                    <label>Username</label><br>
                    <input name="player" placeholder="Player to report" required>
                    <br><br>
                    <label>Reason</label><br>
                    <textarea name="reason" rows="4" placeholder="What happened?" required></textarea>
                    <br><br>
                    <label>Evidence Link</label><br>
                    <input name="evidence" placeholder="Video or Image link">
                    <button type="submit" class="btn">Submit</button>
                </form>
            </div>
        </div>
    """)

@app.route('/moderation')
def moderation_page():
    reps = list(db_manager.reports.find({"status": "Pending"}))
    return render_template_string(f"""
        {BASE_STYLE}
        {NAV_HTML}
        <div class="container">
            <h1>Moderation Panel</h1>
            {% for r in reps %}
            <div class="card" style="margin-bottom:15px;">
                <h3>Player: {{{{ r.player }}}}</h3>
                <p><strong>Reason:</strong> {{{{ r.reason }}}}</p>
                <a href="{{{{ r.evidence }}}}" target="_blank" style="color:var(--accent);">Link to Evidence</a>
                <form action="/moderation/resolve" method="POST" style="margin-top:15px;">
                    <input type="hidden" name="id" value="{{{{ r._id }}}}">
                    <button name="a" value="approve" class="btn" style="background:#4ade80;">Approve</button>
                    <button name="a" value="dismiss" class="btn" style="background:#f87171; margin-left:10px;">Dismiss</button>
                </form>
            </div>
            {% endfor %}
            {% if not reps %}<p>No pending reports.</p>{% endif %}
        </div>
    """, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve_report():
    db_manager.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": request.form.get('a')}})
    return redirect(url_for('moderation_page'))

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
