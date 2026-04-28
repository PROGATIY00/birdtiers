import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session
from pymongo import MongoClient
import os
import threading
import time

# --- CONFIGURATION (Render Environment Variables) ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      # Private Staff Audit Feed
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID") # Public Network Status (Embeds)
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# MongoDB Setup
# Required packages: requirements.txt -> discord.py flask pymongo[srv] gunicorn
try:
    client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db_mongo = client_db['magmatiers_db']
    players_col = db_mongo['players']
    partners_col = db_mongo['partners']
    settings_col = db_mongo['settings']

    # Ensure Maintenance Setting Exists in DB
    if not settings_col.find_one({"id": "maintenance"}):
        settings_col.insert_one({"id": "maintenance", "enabled": False})
except Exception as e:
    print(f"❌ DATABASE CONNECTION ERROR: {e}")
    exit(1)

# Constants
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

# Global Rank Definitions
def get_global_rank(pts):
    if pts >= 400: return "Combat Grandmaster", "rank-grand-master", "400 points required"
    if pts >= 200: return "Combat Master", "rank-combat-master", "200 points required"
    return "Combat Ace", "rank-combat-ace", "< 200 points"

# Maintenance DB Helper
def is_maint():
    doc = settings_col.find_one({"id": "maintenance"})
    return doc['enabled'] if doc else False

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def update_presence(self):
        m = is_maint()
        status_text = "⚠️ MAINTENANCE" if m else "🎮 MagmaTIERS LIVE"
        activity = discord.Activity(type=discord.ActivityType.watching, name=status_text)
        await self.change_presence(status=discord.Status.dnd if m else discord.Status.online, activity=activity)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"🌋 Bot Synced as {self.user}")

bot = MagmaBot()

# Commands: /rank, /retire, /maintenance, /partner
@bot.tree.command(name="maintenance", description="Toggle portal maintenance mode")
async def maintenance(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator: return
    settings_col.update_one({"id": "maintenance"}, {"$set": {"enabled": enabled}})
    await bot.update_presence()
    
    # 1. Public Status Embed
    if STATUS_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(STATUS_CHANNEL_ID))
            color = discord.Color.red() if enabled else discord.Color.green()
            status_text = "OFFLINE / MAINTENANCE" if enabled else "ONLINE / LIVE"
            desc = "Atechnical update is in progress. The web portal is temporarily offline." if enabled else "All systems functional. The portal is now fully operational."
            
            embed = discord.Embed(title="📡 Network Status Update", description=desc, color=color, timestamp=discord.utils.utcnow())
            embed.set_author(name="MagmaTiers Systems")
            embed.add_field(name="Current State", value=f"**{status_text}**")
            embed.set_footer(text="Broadcast Audit")
            await channel.send(embed=embed)
        except Exception as e: print(f"Status Channel Error: {e}")

    # 2. Private Staff Log
    if LOG_CHANNEL_ID:
        try:
            log_ch = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            await log_ch.send(f"🛠️ **Staff Audit:** {interaction.user.name} toggled maintenance to `{enabled}`.")
        except: pass

    await interaction.response.send_message(f"📡 Broadcast successful. Maintenance: {'ENABLED' if enabled else 'DISABLED'}", ephemeral=True)

@bot.tree.command(name="rank", description="Set a player's tier for a mode")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, name: str, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator: return
    
    tier = tier.upper().strip()
    name_clean = name.strip()
    existing = players_col.find_one({"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode.value})
    
    old_tier = existing.get('tier', 'LT5') if existing else 'LT5'
    peak = existing.get('peak', tier) if existing else tier
    
    # Update Peak Tier Logic
    if tier in TIER_ORDER and peak in TIER_ORDER:
        if TIER_ORDER.index(tier) > TIER_ORDER.index(peak): peak = tier

    # Database Update
    players_col.update_one(
        {"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode.value},
        {"$set": {"username": name_clean, "gamemode": mode.value, "tier": tier, "region": region.value.upper(), "retired": False, "peak": peak}},
        upsert=True
    )

    # Status Announcement Logic
    status = "updated"
    if tier in TIER_ORDER and old_tier in TIER_ORDER:
        if TIER_ORDER.index(tier) > TIER_ORDER.index(old_tier): status = "promoted"
        elif TIER_ORDER.index(tier) < TIER_ORDER.index(old_tier): status = "demoted"

    # Send to Private Log Channel
    if LOG_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            await channel.send(f"**{name_clean}** {status} to **{tier}** in **{mode.value}**")
        except Exception as e: print(f"Log Channel Error: {e}")

    await interaction.response.send_message(f"🌋 Rank Set for {name_clean} in {mode.value}.", ephemeral=True)

@bot.tree.command(name="retire", description="Retire a player from a gamemode or globally")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES] + [app_commands.Choice(name="Global", value="all")])
async def retire(interaction: discord.Interaction, name: str, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator: return
    name_clean = name.strip()
    query = {"username": {"$regex": f"^{name_clean}$", "$options": "i"}}
    if mode.value != "all": query["gamemode"] = mode.value
    
    players_col.update_many(query, {"$set": {"retired": True}})
    
    if LOG_CHANNEL_ID:
        try:
            log_ch = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            await log_ch.send(f"💀 **Retired:** {name_clean} from **{mode.value}**.")
        except: pass

    await interaction.response.send_message(f"💀 Retired {name_clean}.", ephemeral=True)

@bot.tree.command(name="partner", description="Manage web portal partners")
@app_commands.choices(action=[app_commands.Choice(name="Add", value="add"),app_commands.Choice(name="Remove", value="remove")])
async def partner(interaction: discord.Interaction, action: str, name: str, image_url: str = None, website_link: str = "#"):
    if not interaction.user.guild_permissions.administrator: return
    if action == "add":
        partners_col.update_one({"name": name}, {"$set": {"img": image_url, "link": website_link}}, upsert=True)
        await interaction.response.send_message(f"🤝 Partner Added: {name}")
    else:
        partners_col.delete_one({"name": name})
        await interaction.response.send_message(f"🗑️ Partner Removed: {name}")

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "magma_full_heritage_v32"

# 🛠️ TEAMSPEAK-STYLE MAINTENANCE PAGE
MAINTENANCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS - Disconnected</title>
    <style>
        body { background: #0a0b0d; color: #cfd8dc; font-family: 'Segoe UI', Tahoma, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .ts-modal { background: #1a1c1f; border: 1px solid #333; width: 450px; border-radius: 4px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); overflow: hidden;}
        .ts-header { background: #23272a; padding: 10px 15px; font-size: 13px; font-weight: bold; border-bottom: 1px solid #333; color: #aaa; }
        .ts-body { padding: 30px; text-align: center; }
        .progress-bg { background: #000; height: 12px; border-radius: 2px; position: relative; overflow: hidden; border: 1px solid #444; margin: 20px 0; }
        .progress-bar { background: linear-gradient(to right, #4a90e2, #357abd); width: 40%; height: 100%; animation: slide 2s infinite ease-in-out; }
        @keyframes slide { from { margin-left: -40%; } to { margin-left: 100%; } }
        .info-box { background: #000; color: #00ff00; font-family: monospace; padding: 10px; font-size: 11px; text-align: left; border: 1px solid #222; }
    </style>
</head>
<body>
    <div class="ts-modal">
        <div class="ts-header">MagmaTIERS - System Interruption</div>
        <div class="ts-body">
            <div style="color:#ff5555; font-weight:bold; font-size:14px;">MAINTENANCE IN PROGRESS</div>
            <div class="progress-bg"><div class="progress-bar"></div></div>
            <div class="info-box">
                > Status: 503_SERVICE_UNAVAILABLE<br>
                > System: Core Services<br>
                > Reason: Optimizing Tier Calculations<br>
                > Estimated Downtime: T-Minus 25m
            </div>
        </div>
    </div>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS | Competitive Leaderboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; --spotlight: #161a24; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; position: relative;}
        
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; }

        /* LIVE PILOT */
        .status-pill { font-size: 10px; padding: 4px 10px; border-radius: 20px; font-weight: 800; display: flex; align-items: center; gap: 6px; background: rgba(0, 255, 0, 0.1); color: #00ff00; border: 1px solid #00ff00; }
        .dot { width: 6px; height: 6px; border-radius: 50%; background: #00ff00; box-shadow: 0 0 5px #00ff00; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }

        /* MODE NAV */
        .mode-nav { display: flex; justify-content:center; gap: 8px; flex-wrap: wrap; padding: 15px 50px; background: #0f1117; border-bottom: 1px solid var(--border); }
        .mode-btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 12px; font-weight: 600; }
        .mode-btn.active, .mode-btn:hover { border-color: var(--accent); color: white; background: #1c1f2b; }

        /* --- HERITAGE HT1/LT1 'MAGMA SPIN' ANIMATION --- */
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; overflow: hidden; border-radius: 12px; border: 1px solid var(--border) !important; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; }
        .insane-name { color: #fff !important; text-shadow: 0 0 10px #ff4500; font-weight: 900; }

        /* PEAK HOVER TOOLTIP */
        .tier-badge { position: relative; cursor: help; background: #1c1f26; padding: 6px 12px; border-radius: 6px; text-align: center; font-weight: 800; font-size: 13px; color: var(--accent); }
        .peak-tooltip {
            visibility: hidden; background: #000; color: #fff; text-align: center; border-radius: 4px; padding: 4px 8px;
            position: absolute; z-index: 10; bottom: 125%; left: 50%; transform: translateX(-50%); font-size: 10px;
            white-space: nowrap; border: 1px solid var(--accent); opacity: 0; transition: 0.2s;
        }
        .tier-badge:hover .peak-tooltip { visibility: visible; opacity: 1; }

        /* GLOBAL RANKS (Pills) */
        .global-rank { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; margin-left: 8px; vertical-align: middle; cursor: help;}
        .rank-grand-master { background: rgba(255, 0, 0, 0.2); color: #ff0000; border: 1px solid #ff0000; box-shadow: 0 0 10px rgba(255,0,0,0.2); }
        .rank-combat-master { background: rgba(255, 140, 0, 0.2); color: #ff8c00; border: 1px solid #ff8c00; }
        .rank-combat-ace { background: rgba(139, 148, 158, 0.1); color: #8b949e; border: 1px solid #30363d;}

        /* LIST & WRAPPER */
        .wrapper { max-width: 950px; margin: auto; padding: 25px; min-height: 50vh; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 45px 50px 1fr 70px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .player-row:hover { border-color: var(--accent); transform: scale(1.01); background: #1c1f2b; }
        
        /* REGIONS */
        .REGION-tag { font-size: 13px; font-weight: 800; }
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; } .AF { color: #f76707; } .OC { color: #3498db; } .SA { color: #ae3ec9; }

        /* PARTNERS */
        .partners-section { margin-top: 50px; padding: 40px; border-top: 1px solid var(--border); background: #0f1117; text-align: center; }
        .partner-img { height: 45px; filter: grayscale(1); opacity: 0.6; transition: 0.3s; margin: 0 20px; }
        .partner-img:hover { filter: grayscale(0); opacity: 1; transform: scale(1.1); }

        /* --- PROFILE MODAL (Floating on Top) --- */
        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.85); z-index: 1000;
            display: flex; justify-content: center; align-items: center;
        }
        .ts-modal-heritage {
            background: #10141c; width: 450px; border-radius: 18px; border: 2px solid #2d3647;
            position: relative; overflow: hidden; padding: 40px;
        }
        .modal-heritage-close {
            position: absolute; top: 15px; right: 15px; background: none; border: none;
            color: #aaa; font-size: 20px; cursor: pointer; text-decoration: none;
        }
        .centered-avatar-heritage {
            width: 120px; height: 120px; border-radius: 50%; border: 3px solid #ffcc00;
            background: #000; display: block; margin: 0 auto;
        }
        .namemc-btn-heritage {
            background: var(--spotlight); color: white; text-decoration: none;
            padding: 8px 18px; border-radius: 20px; font-size: 12px;
            display: flex; align-items: center; gap: 8px; margin: 15px auto 30px; width: fit-content;
            border: 1px solid #333;
        }
        .section-header-heritage {
            color: var(--dim); font-size: 14px; text-transform: uppercase; letter-spacing: 1.5px;
            margin-bottom: 12px; font-weight: 600;
        }
        .heritage-tiers-panel {
            background: #080a0f; padding: 15px; border-radius: 12px; border: 1px solid var(--border);
            display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; text-align: center;
        }
        .position-badge-heritage {
            display: flex; gap: 15px; align-items: center;
            background: var(--spotlight); border: 1px solid var(--border); padding: 15px 20px; border-radius: 12px;
        }
        .pos-badge-num {
            background: #ffcc00; color: #000; font-size: 22px; font-weight: 800; font-style: italic;
            width: 50px; height: 35px; border-radius: 6px; display: flex; justify-content: center; align-items: center;
        }
        
    </style>
</head>
<body>
    <div class="navbar">
        <div style="display:flex; align-items:center; gap:15px;">
            <a href="/" class="logo">Magma<span>TIERS</span></a>
            <div class="status-pill"><div class="dot"></div> LIVE</div>
        </div>
        <form><input type="text" name="search" class="search-input" placeholder="Find player..." value="{{ search_query }}">
        {% if current_mode %}<input type="hidden" name="mode" value="{{current_mode}}">{% endif %}</form>
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="ts-modal-heritage">
            <a href="/{% if current_mode %}?mode={{current_mode}}{% endif %}" class="modal-heritage-close">×</a>
            
            <img src="https://minotar.net/helm/{{spotlight.username}}/120.png" class="centered-avatar-heritage">
            
            <h1 style="text-align:center; color: #fff; font-size: 32px; margin: 20px 0 10px; font-weight: 800;">
                {{ spotlight.username }}
            </h1>
            
            <div class="global-rank {{ spotlight.global_rank_id }}" style="display:block; margin: 0 auto; width: fit-content; font-size: 14px; padding: 6px 16px;">
                <span style="display:inline-flex; align-items:center; gap:8px;">
                    <img src="https://i.imgur.com/8QO5W5M.png" style="height:14px; filter:brightness(0) invert(1);"> 
                    {{ spotlight.global_rank_name }}
                </span>
            </div>
            
            <p style="text-align:center; color: var(--dim); margin: 10px 0;">{{ spotlight.primary_region }}</p>
            
            <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" class="namemc-btn-heritage">
                <img src="https://i.imgur.com/K4zI904.png" style="height:14px;"> NameMC Profile
            </a>
            
            <div class="section-header-heritage">POSITION</div>
            <div class="position-badge-heritage">
                <div class="pos-badge-num">1.</div>
                <div style="flex-grow:1; display:flex; justify-content:space-between; align-items:center;">
                    <b style="font-size:18px;">
                        <span style="color:#ffcc00; margin-right:8px;">🏆</span> OVERALL
                    </b>
                    <span style="color:var(--dim);">({{ spotlight.overall_points }} points)</span>
                </div>
            </div>
            
            <div class="section-header-heritage" style="margin-top: 30px;">TIERS</div>
            <div class="heritage-tiers-panel">
                {% for r in spotlight.ranks %}
                <div style="text-align:center;">
                    <img src="https://i.imgur.com/K4zI904.png" style="height:25px; filter:grayscale(1); opacity:0.3; margin-bottom:5px;"> <div class="tier-badge" style="font-size:11px; padding: 3px 8px;">
                        {{r.tier}}
                        <span class="peak-tooltip">Peak: {{r.peak}}</span>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn {% if current_mode.lower() == m.lower() %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>

    <div class="wrapper">
        {% for p in players %}
        {% set is_insane = p.tier in ['HT1', 'LT1'] %}
        <a href="/?search={{p.username}}{% if current_mode %}&mode={{current_mode}}{% endif %}" class="player-row {% if is_insane %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div>
                <b class="{% if is_insane %}insane-name{% endif %}">{{ p.username }}</b>
                <span class="global-rank {{ p.rank_id }}" title="{{ p.rank_desc }}">{{ p.rank_name }}</span>
                <br><small style="color:var(--dim)">{{ p.points }} Pts</small>
            </div>
            <div class="REGION-tag {{ p.region.upper() }}">{{ p.region }}</div>
            <div class="tier-badge">
                {{ p.tier }}
                <span class="peak-tooltip">Peak: {{ p.peak }}</span>
            </div>
        </a>
        {% endfor %}
    </div>

    <div class="partners-section">
        <div style="color:var(--dim); font-size:12px; margin-bottom:20px; text-transform:uppercase; letter-spacing:1px;">Partners</div>
        {% for partner in partners %}
        <a href="{{ partner.link }}" target="_blank"><img src="{{ partner.img }}" class="partner-img"></a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if is_maint(): return render_template_string(MAINTENANCE_HTML)
    
    mode_filter, search_q = request.args.get('mode', ''), request.args.get('search', '').strip().lower()
    try:
        players_data = list(players_col.find({}))
        partners_data = list(partners_col.find({}))
    except Exception as e:
        print(f"Web Data Fetch Error: {e}")
        players_data, partners_data = [], []
    
    stats = {}
    for p in players_data:
        u, gm, tier, ret = p['username'], p['gamemode'], p['tier'], p.get('retired', False)
        peak, reg = p.get('peak', 'LT5'), p.get('region', 'NA')
        val = TIER_DATA.get(tier, 0)
        
        if u not in stats: stats[u] = {"pts": 0, "region": reg, "retired": True, "tier": "N/A", "peak": peak}
        
        if mode_filter:
            if gm.lower() == mode_filter.lower(): stats[u].update({"pts": val, "tier": tier, "retired": ret, "peak": peak})
        else:
            # Global view adds points
            if not ret: (stats[u].update({"retired": False}), stats[u].update({"pts": stats[u]["pts"] + val}))
            else: stats[u]["pts"] += (val * 0.1) # Legacy points

    processed = []
    for u, d in stats.items():
        if d['pts'] <= 0: continue
        r_name, r_id, r_desc = get_global_rank(d['pts'])
        processed.append({"username": u, "points": int(d['pts']), "region": d['region'], "retired": d['retired'], "tier": d['tier'], "peak": d['peak'], "rank_name": r_name, "rank_id": r_id, "rank_desc": r_desc})

    processed = sorted(processed, key=lambda x: (x['retired'], -x['points']))
    
    # PROFILE SPOTLIGHT (Modal)
    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res:
            # Calculate overall points for spotlight
            over_pts = 0
            for r in res:
                v = TIER_DATA.get(r['tier'], 0)
                if not r.get('retired'): over_pts += v
                else: over_pts += (v * 0.1)
                
            gr_name, gr_id, _ = get_global_rank(over_pts)
            
            spotlight = {
                "username": res[0]['username'],
                "overall_points": int(over_pts),
                "global_rank_name": gr_name,
                "global_rank_id": gr_id,
                "primary_region": res[0].get('region', 'NA'),
                "ranks": res
            }

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_filter, search_query=search_q, partners=partners_data, spotlight=spotlight)

# Gunicorn-safe background thread for the bot
def start_bot():
    if TOKEN:
        print("🌋 Launching MagmaBot thread...")
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"❌ Bot Crash: {e}")

threading.Thread(target=start_bot, daemon=True).start()

if __name__ == '__main__':
    # Local development run
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
