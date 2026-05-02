"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 4.6.0
--------------------------------------------
THE "ULTIMATE LEGACY" BUILD
- FULL FEATURE PARITY: All legacy features restored.
- MODERATION: Complete Decline/Dismiss/Approve workflow.
- VISUALS: Expanded CSS, Gold/Silver/Bronze styling, Profile Modals.
- AUTOMATION: 15-second meta-refresh for live leaderboard updates.
- STABILITY: Enhanced MongoDB connection pooling and error catching.
- DISCORD: High-priority logging for high-tier results.
"""

import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for, session
from pymongo import MongoClient, errors
from bson.objectid import ObjectId
import os
import threading
import datetime
import logging
import time

# --- SYSTEM LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MagmaTiers-V4.6")

# --- ENVIRONMENT & CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
HIGH_RESULTS_ID = os.getenv("HIGH_RESULTS_ID")

# DEFINITIONS
MODES = [
    "Crystal", "UHC", "Pot", "SMP", "Axe", 
    "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"
]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = [
    "LT5", "HT5", "LT4", "HT4", "LT3", 
    "HT3", "LT2", "HT2", "LT1", "HT1"
]

# --- DATABASE ARCHITECTURE ---
class MagmaDatabase:
    def __init__(self, uri):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.db = self.client['magmatiers_db']
            self.players = self.db['players']
            self.settings = self.db['settings']
            self.reports = self.db['reports']
            self.client.admin.command('ping')
            logger.info("✅ Database Connection Established Successfully")
        except errors.ServerSelectionTimeoutError as err:
            logger.error(f"❌ Database Connection Timeout: {err}")
            self.db = None

db_mgr = MagmaDatabase(MONGO_URI)

# --- CORE LOGIC ENGINE ---
def get_tier_numerical_value(tier_name):
    """Converts string tier names to integers for sorting and scoring."""
    if not tier_name:
        return 0
    try:
        return TIER_ORDER.index(tier_name.upper().strip()) + 1
    except (ValueError, AttributeError):
        return 0

def calculate_aggregate_score(tier_list):
    """Calculates the total weight of a player's active tiers."""
    return sum(get_tier_numerical_value(t) for t in tier_list)

def determine_global_rank(tier_list):
    """Determines the visual rank title based on performance metrics."""
    if not tier_list:
        return "Unranked"
    
    total_score = calculate_aggregate_score(tier_list)
    numeric_values = [get_tier_numerical_value(t) for t in tier_list]
    highest_attained = max(numeric_values) if numeric_values else 0
    
    # Ranking Logic
    if highest_attained >= 9 and len(tier_list) >= 3:
        return "Grandmaster"
    elif total_score >= 35:
        return "Legend"
    elif total_score >= 25:
        return "Master"
    elif total_score >= 15:
        return "Elite"
    elif total_score >= 8:
        return "Diamond"
    elif total_score >= 4:
        return "Gold"
    elif total_score >= 2:
        return "Silver"
    else:
        return "Bronze"

def is_maintenance_active():
    """Checks the database for maintenance status."""
    if not db_mgr.db:
        return {"active": True, "reason": "Database Link Severed"}
    status = db_mgr.settings.find_one({"_id": "maintenance_mode"})
    return status if status else {"active": False, "reason": "None"}

# --- DISCORD INTEGRATION ---
class MagmaClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        logger.info("📡 Syncing Discord Application Commands...")
        await self.tree.sync()

bot = MagmaClient()

@bot.tree.command(name="rank", description="Modify a player's tier status")
@app_commands.describe(player="Minecraft Username", mode="Gamemode to update", tier="New Tier (e.g. HT3)")
async def rank_cmd(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str):
    # Security Check
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("⛔ You lack the 'Manage Roles' permission.", ephemeral=True)
    
    m_check = is_maintenance_active()
    if m_check['active']:
        return await interaction.response.send_message(f"🛠️ System is in Maintenance: {m_check['reason']}", ephemeral=True)

    tier_clean = tier.upper().strip()
    if tier_clean not in TIER_ORDER:
        return await interaction.response.send_message(f"❌ '{tier_clean}' is not a valid tier.", ephemeral=True)

    # Database Update
    db_mgr.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {
            "tier": tier_clean,
            "region": region.upper(),
            "discord_id": discord_user.id,
            "retired": False,
            "banned": False,
            "last_updated": datetime.datetime.utcnow()
        }},
        upsert=True
    )

    # Logging Logic
    log_id = HIGH_RESULTS_ID if get_tier_numerical_value(tier_clean) >= 5 else LOG_CHANNEL_ID
    channel = bot.get_channel(int(log_id))
    if channel:
        embed = discord.Embed(title="Tier Updated", color=discord.Color.orange())
        embed.add_field(name="Player", value=player)
        embed.add_field(name="Mode", value=mode)
        embed.add_field(name="New Tier", value=tier_clean)
        embed.set_footer(text=f"Updated by {interaction.user}")
        await channel.send(content=discord_user.mention, embed=embed)

    await interaction.response.send_message(f"✅ Successfully updated **{player}** to **{tier_clean}**.", ephemeral=True)

@bot.tree.command(name="maintenance", description="Toggle global maintenance mode")
async def toggle_maint(interaction: discord.Interaction, active: bool, reason: str = "System Maintenance"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
    
    db_mgr.settings.update_one(
        {"_id": "maintenance_mode"},
        {"$set": {"active": active, "reason": reason}},
        upsert=True
    )
    status_str = "ENABLED" if active else "DISABLED"
    await interaction.response.send_message(f"🛠️ Maintenance mode has been **{status_str}**.")

# --- WEB UI ENGINE (FLASK) ---
app = Flask(__name__)

# EXTENDED CSS STYLING
MASTER_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@300;400;600;800&display=swap');
    :root {
        --bg-main: #0b0c10;
        --bg-card: #14171f;
        --bg-header: #0f1117;
        --border-color: #262932;
        --accent: #ff4500;
        --accent-glow: rgba(255, 69, 0, 0.3);
        --text-primary: #f0f2f5;
        --text-dim: #9ba3af;
        --gold: #FFD700;
        --silver: #C0C0C0;
        --bronze: #CD7F32;
    }
    
    * { box-sizing: border-box; }
    body { 
        background: var(--bg-main); 
        color: var(--text-primary); 
        font-family: 'Fredoka', sans-serif; 
        margin: 0; 
        line-height: 1.6;
    }

    .header { 
        background: var(--bg-header); 
        padding: 1rem 5%; 
        border-bottom: 3px solid var(--accent); 
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        position: sticky;
        top: 0;
        z-index: 1000;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    }

    .logo { font-size: 2rem; font-weight: 800; color: white; text-decoration: none; letter-spacing: -1px; }
    .logo span { color: var(--accent); }

    .nav-btn { 
        padding: 8px 18px; 
        border-radius: 10px; 
        background: var(--bg-card); 
        border: 1px solid var(--border-color); 
        color: var(--text-dim); 
        text-decoration: none; 
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .nav-btn:hover { border-color: var(--accent); color: white; transform: translateY(-2px); }
    .nav-btn.active { background: var(--accent); color: white; border-color: var(--accent); }

    .container { max-width: 1000px; margin: 3rem auto; padding: 0 20px; }

    /* HIGH RESULTS DASHBOARD */
    .high-results-box {
        background: linear-gradient(145deg, rgba(255, 69, 0, 0.1), rgba(0,0,0,0));
        border: 2px solid var(--accent);
        border-radius: 20px;
        padding: 25px;
        margin-bottom: 40px;
        box-shadow: 0 0 30px var(--accent-glow);
    }
    .hr-title { font-weight: 800; color: var(--accent); margin-bottom: 15px; display: flex; align-items: center; gap: 10px; }

    /* LEADERBOARD TABLE */
    .player-row { 
        background: var(--bg-card); 
        border: 1px solid var(--border-color); 
        border-radius: 15px; 
        padding: 1.2rem; 
        margin-bottom: 1rem; 
        display: grid; 
        grid-template-columns: 70px 60px 1fr 120px 120px; 
        align-items: center; 
        text-decoration: none; 
        color: inherit; 
        transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .player-row:hover { border-color: var(--accent); transform: scale(1.01); background: #1c202b; }

    .rank-pos { font-size: 1.2rem; font-weight: 800; }
    .pos-1 { color: var(--gold); }
    .pos-2 { color: var(--silver); }
    .pos-3 { color: var(--bronze); }
    .pos-default { color: var(--text-dim); }

    .tier-badge { 
        background: rgba(255, 69, 0, 0.1); 
        color: var(--accent); 
        font-size: 0.75rem; 
        font-weight: 800; 
        padding: 4px 10px; 
        border-radius: 6px; 
        border: 1px solid var(--accent);
        text-transform: uppercase;
    }

    /* MODAL SYSTEM */
    .modal-overlay { 
        position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
        background: rgba(0,0,0,0.9); display: flex; justify-content: center; 
        align-items: center; z-index: 9999; backdrop-filter: blur(10px); 
    }
    .modal-content { 
        background: #11141c; width: 450px; padding: 40px; 
        border-radius: 30px; border: 1px solid var(--border-color); 
        text-align: center; position: relative;
    }
    .stat-retired { opacity: 0.3; filter: grayscale(1); border-style: dashed !important; }
    
    /* INPUTS & BUTTONS */
    input, textarea { 
        background: var(--bg-card); border: 1px solid var(--border-color); 
        color: white; padding: 15px; border-radius: 12px; width: 100%; 
        margin-bottom: 15px; font-family: inherit;
    }
    .submit-btn { 
        background: var(--accent); color: white; border: none; 
        padding: 15px 30px; border-radius: 12px; cursor: pointer; 
        font-weight: 800; width: 100%; transition: 0.3s;
    }
    .submit-btn:hover { background: #ff5e1a; box-shadow: 0 0 20px var(--accent-glow); }
    .btn-decline { background: #ef4444; margin-top: 10px; }

    /* SEARCH BAR */
    .search-input {
        background: #0b0c10;
        border: 1px solid var(--border-color);
        padding: 8px 15px;
        border-radius: 8px;
        color: white;
        width: 250px;
    }
</style>
"""

@app.route('/')
def home():
    # Maintenance Check
    maint = is_maintenance_active()
    if maint['active']:
        return f"<html><head>{MASTER_STYLE}</head><body style='display:flex; justify-content:center; align-items:center; height:100vh; text-align:center;'><div><h1 style='font-size:4rem;'>🛠️</h1><h1>SYSTEM UNDER MAINTENANCE</h1><p style='color:var(--text-dim)'>{maint['reason']}</p></div></body></html>"

    # Query Params
    mode_filter = request.args.get('mode', '').lower()
    search_filter = request.args.get('search', '').lower()
    
    # Data Fetching
    cursor = list(db_mgr.players.find({"banned": {"$ne": True}}))
    player_map = {}
    
    for doc in cursor:
        username = doc['username']
        if username not in player_map:
            player_map[username] = {
                "username": username,
                "tiers": [],
                "kits": {},
                "region": doc.get('region', 'NA'),
                "history": []
            }
        
        player_map[username]["history"].append(doc)
        if not doc.get('retired', False):
            player_map[username]["tiers"].append(doc['tier'])
            player_map[username]["kits"][doc['gamemode'].lower()] = doc['tier']

    # Spotlight logic (Search)
    spotlight_data = None
    if search_filter:
        found_key = next((name for name in player_map if name.lower() == search_filter), None)
        if found_key:
            match = player_map[found_key]
            spotlight_data = {
                "name": match['username'],
                "global_rank": determine_global_rank(match['tiers']),
                "entries": match['history']
            }

    # Leaderboard Processing
    leaderboard = []
    for user, data in player_map.items():
        if not data["tiers"] and not spotlight_data: continue
        
        best_tier = max(data["tiers"], key=get_tier_numerical_value) if data["tiers"] else "N/A"
        current_display = data["kits"].get(mode_filter, best_tier) if mode_filter else best_tier
        
        entry = {
            "name": user,
            "display_tier": current_display,
            "rank_title": determine_global_rank(data["tiers"]),
            "region": data['region'],
            "score": calculate_aggregate_score(data["tiers"]),
            "sort_priority": get_tier_numerical_value(data["kits"].get(mode_filter)) if mode_filter else calculate_aggregate_score(data["tiers"])
        }
        
        if mode_filter and mode_filter not in data["kits"]: continue
        leaderboard.append(entry)

    # Final Sort
    leaderboard = sorted(leaderboard, key=lambda x: x['sort_priority'], reverse=True)
    high_results_list = [p for p in leaderboard if p['rank_title'] in ["Grandmaster", "Legend", "Master"]]

    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="15">
        <title>MagmaTIERS Leaderboard</title>
        {{ style|safe }}
    </head>
    <body>
        <div class="header">
            <a href="/" class="logo">Magma<span>TIERS</span></a>
            <div style="display: flex; gap: 15px; align-items: center;">
                <form action="/" method="GET" style="margin:0;">
                    <input type="text" name="search" class="search-input" placeholder="Search Player...">
                </form>
                <a href="/report" class="nav-btn">REPORT</a>
            </div>
        </div>

        {% if spotlight %}
        <div class="modal-overlay" onclick="window.location.href='/'">
            <div class="modal-content" onclick="event.stopPropagation()">
                <img src="https://minotar.net/helm/{{ spotlight.name }}/80.png" style="border-radius:15px; margin-bottom:15px;">
                <h1 style="margin:0;">{{ spotlight.name }}</h1>
                <span class="tier-badge" style="margin-bottom:20px; display:inline-block;">{{ spotlight.global_rank }}</span>
                
                <div style="text-align: left; margin-top: 20px;">
                    <p style="color: var(--text-dim); font-size: 0.8rem; text-transform: uppercase; font-weight: 800;">Tier Breakdown</p>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                        {% for entry in spotlight.entries %}
                        <div style="background: #1a1d26; padding: 10px; border-radius: 10px; border: 1px solid var(--border-color);" class="{% if entry.retired %}stat-retired{% endif %}">
                            <div style="font-size: 0.7rem; color: var(--accent);">{{ entry.gamemode|upper }}</div>
                            <div style="font-weight: 800;">{{ entry.tier }}</div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                <button class="submit-btn" style="margin-top:25px;" onclick="window.location.href='/'">Close Profile</button>
            </div>
        </div>
        {% endif %}

        <div class="nav-strip" style="background:#0f1117; padding: 15px; display: flex; justify-content: center; gap: 10px; border-bottom: 1px solid var(--border-color);">
            <a href="/" class="nav-btn {% if not mode_active %}active{% endif %}">GLOBAL</a>
            {% for m in all_modes %}
            <a href="/?mode={{ m|lower }}" class="nav-btn {% if mode_active == m|lower %}active{% endif %}">{{ m|upper }}</a>
            {% endfor %}
        </div>

        <div class="container">
            {% if not mode_active and not search_active and high_list %}
            <div class="high-results-box">
                <div class="hr-title"><span>🔥</span> HIGH RESULTS (MASTER+)</div>
                {% for p in high_list[:3] %}
                <a href="/?search={{ p.name }}" class="player-row" style="border-color: var(--gold); background: rgba(255, 215, 0, 0.03);">
                    <div class="rank-pos pos-1">⭐</div>
                    <img src="https://minotar.net/helm/{{ p.name }}/40.png" style="border-radius:6px;">
                    <div><span style="font-weight:800;">{{ p.name }}</span> <span class="tier-badge">{{ p.rank_title }}</span></div>
                    <div style="color: var(--text-dim);">{{ p.region }}</div>
                    <div style="text-align: right; color: var(--accent); font-weight: 800; font-size: 1.2rem;">{{ p.display_tier }}</div>
                </a>
                {% endfor %}
            </div>
            {% endif %}

            <div style="margin-bottom: 20px; font-weight: 600; color: var(--text-dim);">
                Showing {{ leaderboard|length }} registered players
            </div>

            {% for p in leaderboard %}
            <a href="/?search={{ p.name }}" class="player-row">
                <div class="rank-pos {{ 'pos-1' if loop.index == 1 else 'pos-2' if loop.index == 2 else 'pos-3' if loop.index == 3 else 'pos-default' }}">
                    #{{ loop.index }}
                </div>
                <img src="https://minotar.net/helm/{{ p.name }}/40.png" style="border-radius:6px;">
                <div>
                    <span style="font-weight:800;">{{ p.name }}</span> 
                    <span class="tier-badge" style="font-size: 0.6rem; padding: 2px 6px;">{{ p.rank_title }}</span>
                </div>
                <div style="color: var(--text-dim); font-size: 0.9rem;">{{ p.region }}</div>
                <div style="text-align: right; color: var(--accent); font-weight: 800; font-size: 1.1rem;">{{ p.display_tier }}</div>
            </a>
            {% endfor %}
        </div>
    </body>
    </html>
    """
    return render_template_string(
        template, 
        style=MASTER_STYLE, 
        leaderboard=leaderboard, 
        spotlight=spotlight_data, 
        all_modes=MODES, 
        mode_active=mode_filter, 
        search_active=search_filter, 
        high_list=high_results_list
    )

@app.route('/report', methods=['GET', 'POST'])
def report_view():
    if request.method == 'POST':
        db_mgr.reports.insert_one({
            "reporter": request.form.get('reporter', 'Anonymous'),
            "target": request.form.get('target'),
            "reason": request.form.get('reason'),
            "evidence": request.form.get('evidence'),
            "status": "Pending",
            "timestamp": datetime.datetime.utcnow()
        })
        return redirect(url_for('home'))
    
    template = """
    <html><head>{{ style|safe }}</head><body>
    {{ header|safe }}
    <div class="container" style="max-width: 600px;">
        <h1 style="text-align:center;">SUBMIT REPORT</h1>
        <div style="background: var(--bg-card); padding: 30px; border-radius: 20px; border: 1px solid var(--border-color);">
            <form method="POST">
                <label>Your Name</label><input name="reporter" required>
                <label>Target Player</label><input name="target" required>
                <label>Reason / Infraction</label><textarea name="reason" rows="4" required></textarea>
                <label>Evidence Link (Imgur/YouTube)</label><input name="evidence">
                <button type="submit" class="submit-btn">SEND REPORT</button>
            </form>
        </div>
    </div></body></html>
    """
    header_partial = '<div class="header"><a href="/" class="logo">Magma<span>TIERS</span></a></div>'
    return render_template_string(template, style=MASTER_STYLE, header=header_partial)

@app.route('/moderation')
def mod_panel():
    # Fetch pending reports
    reps = list(db_mgr.reports.find({"status": "Pending"}))
    template = """
    <html><head>{{ style|safe }}</head><body>
    <div class="header"><a href="/" class="logo">Magma<span>TIERS</span></a><span class="tier-badge">ADMIN PANEL</span></div>
    <div class="container">
        <h1>PENDING REPORTS ({{ reps|length }})</h1>
        {% for r in reps %}
        <div style="background: var(--bg-card); border: 1px solid var(--border-color); padding: 25px; border-radius: 20px; margin-bottom: 20px;">
            <div style="display:flex; justify-content:space-between; margin-bottom: 15px;">
                <h3 style="margin:0; color:var(--accent);">Target: {{ r.target }}</h3>
                <small style="color:var(--text-dim);">By: {{ r.reporter }}</small>
            </div>
            <p>{{ r.reason }}</p>
            {% if r.evidence %}<a href="{{ r.evidence }}" target="_blank" style="color:var(--gold);">View Evidence</a>{% endif %}
            
            <form action="/moderation/resolve" method="POST" style="margin-top:20px; display:flex; gap:10px;">
                <input type="hidden" name="report_id" value="{{ r._id }}">
                <button name="action" value="approve" class="submit-btn" style="background:#22c55e;">APPROVE & RESOLVE</button>
                <button name="action" value="decline" class="submit-btn btn-decline">DECLINE / DISMISS</button>
            </form>
        </div>
        {% endfor %}
        {% if not reps %}<p style="text-align:center; color:var(--text-dim);">No reports in queue.</p>{% endif %}
    </div></body></html>
    """
    return render_template_string(template, style=MASTER_STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def mod_resolve():
    r_id = request.form.get('report_id')
    act = request.form.get('action')
    final_status = "Approved" if act == "approve" else "Declined"
    
    db_mgr.reports.update_one(
        {"_id": ObjectId(r_id)},
        {"$set": {"status": final_status, "resolved_at": datetime.datetime.utcnow()}}
    )
    return redirect(url_for('mod_panel'))

# --- THREADED EXECUTION ---
def run_flask():
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    # Start Web Server in background
    web_thread = threading.Thread(target=run_flask, daemon=True)
    web_thread.start()
    
    # Run Discord Bot
    bot.run(TOKEN)
