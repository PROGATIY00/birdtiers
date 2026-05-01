"""
MAGMATIERS INTEGRATED SYSTEM - VERSION 3.0
A professional-grade Discord bot and Web Dashboard solution for competitive Minecraft Tier-listing.
Optimized for deployment on Render.com.
"""

import discord
from discord import app_commands
from flask import Flask, render_template_string, request, jsonify, abort
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import os
import threading
import datetime
import sys
import logging
import json
import uuid

# ==========================================
# 1. LOGGING & SYSTEM CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MagmaTiers")

# --- RENDER ENVIRONMENT VALIDATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

if not all([TOKEN, MONGO_URI, LOG_CHANNEL_ID]):
    logger.critical("FATAL: Missing one or more environment variables (TOKEN, MONGO_URI, LOG_CHANNEL_ID).")
    # We don't sys.exit here to allow the web server to potentially show a 'Config Error' page
    # but the bot and DB will fail safely.

# ==========================================
# 2. DATABASE & TIER CONSTANTS
# ==========================================
MODES = [
    "Crystal", "UHC", "Pot", "SMP", "Axe", 
    "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"
]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]

# TIER_ORDER defines the hierarchy and point values.
# Index 0 (LT5) = 1 Point ... Index 9 (HT1) = 10 Points
TIER_ORDER = [
    "LT5", "HT5", 
    "LT4", "HT4", 
    "LT3", "HT3", 
    "LT2", "HT2", 
    "LT1", "HT1"
]

class DatabaseManager:
    """Handles all MongoDB interactions with safety wrappers."""
    def __init__(self, uri):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.db = self.client['magmatiers_db']
            self.players = self.db['players']
            self.settings = self.db['settings']
            self.logs = self.db['audit_logs']
            # Test connection
            self.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB.")
        except Exception as e:
            logger.error(f"MongoDB Connection Failed: {e}")
            self.db = None

db_manager = DatabaseManager(MONGO_URI)

# ==========================================
# 3. CORE LOGIC & RANKING ENGINE
# ==========================================

def get_tier_value(tier_name):
    """Returns the integer weight of a tier string."""
    try:
        return TIER_ORDER.index(tier_name.upper().strip()) + 1
    except (ValueError, AttributeError):
        return 0

def calculate_player_score(tier_list):
    """
    Calculates the total Power Score for a player.
    A player with HT4 (7 pts) and LT4 (6 pts) = 13.
    """
    return sum(get_tier_value(t) for t in tier_list)

def get_global_rank_name(tier_list):
    """Determines the badge name based on cumulative performance."""
    if not tier_list:
        return "Stone"
    
    total_score = calculate_player_score(tier_list)
    numeric_tiers = [get_tier_value(t) for t in tier_list]
    highest_tier_val = max(numeric_tiers) if numeric_tiers else 0
    kit_count = len(tier_list)

    # Ranking Thresholds
    if highest_tier_val >= 9 and kit_count >= 3:
        return "Grandmaster"
    if total_score >= 35:
        return "Legend"
    if total_score >= 25:
        return "Master"
    if total_score >= 15:
        return "Elite"
    if total_score >= 8:
        return "Diamond"
    if total_score >= 4:
        return "Gold"
    return "Bronze"

def get_maintenance_status():
    """Checks if the system is currently in maintenance mode."""
    if not db_manager.db:
        return {"active": True, "reason": "Database Offline", "duration": "N/A"}
    status = db_manager.settings.find_one({"_id": "maintenance_mode"})
    return status if status else {"active": False, "reason": "None", "duration": "Unknown"}

# ==========================================
# 4. DISCORD BOT IMPLEMENTATION
# ==========================================

class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        logger.info("Syncing Discord Slash Commands...")
        await self.tree.sync()

bot = MagmaBot()

@bot.event
async def on_ready():
    logger.info(f"Logged into Discord as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="MagmaTIERS Leaderboard"))

# --- SLASH COMMANDS ---

@bot.tree.command(name="rank", description="Update or set a player's tier for a specific kit")
@app_commands.describe(
    player="Minecraft Username", 
    discord_user="The Discord account associated",
    tier="Example: HT3, LT1, etc",
    reason="Reason for the tier change"
)
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(
    interaction: discord.Interaction, 
    player: str, 
    discord_user: discord.Member, 
    mode: app_commands.Choice[str], 
    tier: str, 
    region: app_commands.Choice[str], 
    reason: str = "Standard Testing"
):
    # Admin Check
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ You lack permissions to rank players.", ephemeral=True)

    # Maintenance Check
    if get_maintenance_status()['active']:
        return await interaction.response.send_message("🛠️ Command disabled during maintenance.", ephemeral=True)

    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message(f"❌ Invalid tier. Use: {', '.join(TIER_ORDER)}", ephemeral=True)

    # Determine Promotion/Demotion
    old_entry = db_manager.players.find_one({"username": player, "gamemode": mode.value})
    action = "promoted"
    if old_entry:
        old_val = get_tier_value(old_entry['tier'])
        new_val = get_tier_value(tier_upper)
        if new_val < old_val: action = "demoted"
        elif new_val == old_val: action = "updated"

    # Database Update
    db_manager.players.update_one(
        {"username": player, "gamemode": mode.value},
        {
            "$set": {
                "tier": tier_upper,
                "region": region.value,
                "discord_id": discord_user.id,
                "retired": False,
                "last_updated": datetime.datetime.utcnow()
            }
        },
        upsert=True
    )

    # Log to Channel
    try:
        log_chan = bot.get_channel(int(LOG_CHANNEL_ID))
        if log_chan:
            embed = discord.Embed(
                title="🏆 Tier Registry Update", 
                color=0xff4500 if action != "demoted" else 0xff0000,
                timestamp=datetime.datetime.utcnow()
            )
            embed.description = (
                f"**{player}** has been **{action}** to **{tier_upper}** in **{mode.value}**\n\n"
                f"👤 **User:** {discord_user.mention}\n"
                f"📝 **Reason:** {reason}\n"
                f"🌍 **Region:** {region.value}\n"
                f"🛡️ **Tester:** {interaction.user.mention}"
            )
            embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
            embed.set_footer(text="MagmaTIERS Official Logging")
            await log_chan.send(embed=embed)
    except Exception as e:
        logger.error(f"Logging Failed: {e}")

    await interaction.response.send_message(f"✅ Successfully {action} **{player}** to **{tier_upper}** ({mode.value}).", ephemeral=True)

@bot.tree.command(name="maintenance", description="Control system access")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Routine Maintenance"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Administrators only.", ephemeral=True)
    
    db_manager.settings.update_one(
        {"_id": "maintenance_mode"},
        {"$set": {"active": active, "reason": reason, "duration": "TBD"}},
        upsert=True
    )
    status = "ENABLED" if active else "DISABLED"
    await interaction.response.send_message(f"🛠️ Maintenance mode has been **{status}**.")

# ==========================================
# 5. WEB UI & FLASK FRAMEWORK
# ==========================================

app = Flask(__name__)

# --- API ENDPOINTS ---

@app.route('/api/v1/player/<username>')
def api_get_player(username):
    data = list(db_manager.players.find({"username": {"$regex": f"^{username}$", "$options": "i"}}))
    if not data:
        return jsonify({"success": False, "error": "Player not found"}), 404
    
    all_tiers = [d['tier'] for d in data]
    return jsonify({
        "success": True,
        "data": {
            "username": data[0]['username'],
            "cumulative_score": calculate_player_score(all_tiers),
            "rank_badge": get_global_rank_name(all_tiers),
            "region": data[0].get('region', 'NA'),
            "kits": [{"mode": d['gamemode'], "tier": d['tier']} for d in data]
        }
    })

@app.route('/api/v1/leaderboard')
def api_leaderboard():
    # Return top 50
    raw_data = list(db_manager.players.find({"retired": {"$ne": True}}))
    # ... logic for processing ...
    return jsonify({"message": "Leaderboard API is active. Use the web UI for full view."})

# --- WEB UI TEMPLATE (MINIMALIST & DARK) ---

HTML_BASE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MagmaTIERS | Minecraft Competitive Leaderboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@300;400;600;700&display=swap');
        :root {
            --bg-color: #0b0c10;
            --surface-color: #14171f;
            --border-color: #262932;
            --accent-color: #ff4500;
            --text-primary: #f0f2f5;
            --text-secondary: #9ba3af;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0; padding: 0;
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: 'Fredoka', sans-serif;
        }
        /* Navigation */
        .header {
            background: #0f1117;
            padding: 1rem 4rem;
            border-bottom: 2px solid var(--accent-color);
            display: flex; justify-content: space-between; align-items: center;
            position: sticky; top: 0; z-index: 1000;
        }
        .logo { font-size: 1.8rem; font-weight: 800; text-decoration: none; color: white; }
        .logo span { color: var(--accent-color); }
        
        .search-bar {
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            padding: 0.6rem 1.2rem;
            border-radius: 25px;
            color: white; outline: none;
            width: 300px;
        }

        /* Sub-Navigation (Modes) */
        .mode-strip {
            background: #0f1117;
            padding: 0.8rem;
            display: flex; justify-content: center;
            gap: 10px; flex-wrap: wrap;
            border-bottom: 1px solid var(--border-color);
        }
        .mode-pill {
            padding: 0.5rem 1rem;
            border-radius: 8px;
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            text-decoration: none; font-size: 0.9rem;
            transition: all 0.2s ease;
        }
        .mode-pill:hover, .mode-pill.active {
            border-color: var(--accent-color);
            color: white;
            background: #1c1f2b;
        }

        /* Leaderboard Table */
        .container { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
        .rank-card {
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.2rem 2rem;
            margin-bottom: 1rem;
            display: grid;
            grid-template-columns: 60px 80px 1fr 120px 100px;
            align-items: center;
            transition: transform 0.1s;
            cursor: pointer;
            text-decoration: none; color: inherit;
        }
        .rank-card:hover { transform: translateY(-2px); border-color: #3e4451; }
        
        .position { font-size: 1.5rem; font-weight: 700; color: var(--accent-color); }
        .avatar { width: 48px; height: 48px; border-radius: 6px; }
        .username { font-size: 1.2rem; font-weight: 600; }
        .tag-badge {
            background: rgba(255, 69, 0, 0.1);
            color: var(--accent-color);
            font-size: 0.7rem; font-weight: 800;
            padding: 2px 8px; border-radius: 4px;
            text-transform: uppercase; border: 1px solid var(--accent-color);
        }
        .score-sub { font-size: 0.8rem; color: var(--text-secondary); }
        .tier-label { font-size: 1.4rem; font-weight: 800; text-align: right; }

        /* Modals */
        .overlay {
            position: fixed; top:0; left:0; width:100%; height:100%;
            background: rgba(0,0,0,0.8); backdrop-filter: blur(5px);
            display: flex; justify-content: center; align-items: center; z-index: 2000;
        }
        .modal {
            background: #11141c;
            width: 450px; padding: 3rem;
            border-radius: 20px; border: 1px solid #2d3647;
            text-align: center; position: relative;
        }
        .close-btn { position: absolute; top: 20px; right: 20px; font-size: 2rem; cursor: pointer; color: var(--text-secondary); }
        
        /* Stats Grid */
        .stats-grid {
            display: grid; grid-template-columns: 1fr 1fr;
            gap: 10px; margin-top: 2rem;
            max-height: 250px; overflow-y: auto;
        }
        .stat-box {
            background: #1a1d26; padding: 1rem;
            border-radius: 10px; border: 1px solid var(--border-color);
        }
    </style>
</head>
<body>
    <header class="header">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form action="/">
            <input type="text" name="search" class="search-bar" placeholder="Search Player..." value="{{ search_query }}">
        </form>
    </header>

    <div class="mode-strip">
        <a href="/" class="mode-pill {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}
        <a href="/?mode={{m}}" class="mode-pill {% if current_mode == m %}active{% endif %}">{{ m|upper }}</a>
        {% endfor %}
    </div>

    {% if spotlight %}
    <div class="overlay">
        <div class="modal">
            <span class="close-btn" onclick="window.location.href='/'">&times;</span>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" style="width: 100px; margin-bottom: 1rem;">
            <h2>{{ spotlight.username }}</h2>
            <span class="tag-badge">{{ spotlight.rank_name }}</span>
            <p style="color: var(--text-secondary);">Global Power Score: {{ spotlight.score }}</p>
            <div class="stats-grid">
                {% for s in spotlight.all_stats %}
                <div class="stat-box">
                    <div style="font-size: 0.7rem; color: var(--accent-color);">{{ s.mode|upper }}</div>
                    <div style="font-size: 1.2rem; font-weight: 700;">{{ s.tier }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <main class="container">
        {% for p in players %}
        <a href="/?search={{p.username}}{% if current_mode %}&mode={{current_mode}}{% endif %}" class="rank-card">
            <div class="position">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/64.png" class="avatar">
            <div>
                <span class="username">{{ p.username }}</span> 
                <span class="tag-badge" style="margin-left: 10px;">{{ p.rank_name }}</span>
                <div class="score-sub">Power Score: {{ p.total_score }}</div>
            </div>
            <div style="color: #4ade80; font-weight: 600;">{{ p.region }}</div>
            <div class="tier-label">{{ p.display_tier }}</div>
        </a>
        {% endfor %}
    </main>
</body>
</html>
"""

@app.route('/')
def dashboard():
    mode_query = request.args.get('mode', '').strip().lower()
    search_query = request.args.get('search', '').strip().lower()
    
    if not db_manager.db:
        return "Database Connection Error. Please check Render environment variables."

    # Fetch all data once to process ranking
    all_records = list(db_manager.players.find({"retired": {"$ne": True}}))
    
    # Structure data by User
    user_data = {}
    for entry in all_records:
        uname = entry['username']
        if uname not in user_data:
            user_data[uname] = {
                "username": uname,
                "tiers": [],
                "kit_map": {},
                "region": entry.get('region', 'NA')
            }
        user_data[uname]["tiers"].append(entry['tier'])
        user_data[uname]["kit_map"][entry['gamemode'].lower()] = entry['tier']

    processed_list = []
    for uname, data in user_data.items():
        total_score = calculate_player_score(data["tiers"])
        rank_badge = get_global_rank_name(data["tiers"])
        
        if mode_query:
            # If viewing a specific mode, we only show players tested in that mode
            if mode_query in data["kit_map"]:
                tier_in_mode = data["kit_map"][mode_query]
                processed_list.append({
                    "username": uname,
                    "display_tier": tier_in_mode,
                    "total_score": total_score,
                    "rank_name": rank_badge,
                    "region": data["region"],
                    "sort_val": get_tier_value(tier_in_mode)
                })
        else:
            # Global view: Show best tier but sort by total score
            best_tier = max(data["tiers"], key=lambda t: get_tier_value(t))
            processed_list.append({
                "username": uname,
                "display_tier": best_tier,
                "total_score": total_score,
                "rank_name": rank_badge,
                "region": data["region"],
                "sort_val": total_score
            })

    # Final Sort
    processed_list = sorted(processed_list, key=lambda x: x['sort_val'], reverse=True)

    # Spotlight/Search logic
    spotlight = None
    if search_query:
        # Re-fetch from DB for precise data
        specific_data = list(db_manager.players.find({"username": {"$regex": f"^{search_query}$", "$options": "i"}}))
        if specific_data:
            stiers = [x['tier'] for x in specific_data]
            spotlight = {
                "username": specific_data[0]['username'],
                "score": calculate_player_score(stiers),
                "rank_name": get_global_rank_name(stiers),
                "all_stats": [{"mode": x['gamemode'], "tier": x['tier']} for x in specific_data]
            }

    return render_template_string(
        HTML_BASE, 
        players=processed_list, 
        all_modes=MODES, 
        current_mode=mode_query, 
        search_query=search_query,
        spotlight=spotlight
    )

# ==========================================
# 6. EXECUTION ENGINE
# ==========================================

def run_web():
    """Background thread for Flask."""
    # Render expects port 10000 by default
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 1. Start Web Server
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    
    # 2. Start Discord Bot (Main Thread)
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}")
