import discord
from discord import app_commands
from flask import Flask, render_template_string, request, abort
from pymongo import MongoClient
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
settings_col = db_mongo['settings']  # New collection for maintenance state

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

# --- MAINTENANCE HELPERS ---
def get_maintenance_status():
    status = settings_col.find_one({"_id": "maintenance_mode"})
    if not status:
        return {"active": False, "reason": "None", "duration": "Unknown"}
    return status

class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

# --- DISCORD COMMANDS ---

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
@app_commands.describe(active="Enable or disable", reason="Reason for maintenance", duration="Estimated time")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Technical Updates", duration: str = "1 hour"):
    # Permissions check (Admin only recommended)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ You don't have permission to do this.", ephemeral=True)

    settings_col.update_one(
        {"_id": "maintenance_mode"},
        {"$set": {"active": active, "reason": reason, "duration": duration, "updated_at": datetime.datetime.utcnow()}},
        upsert=True
    )
    
    status = "ENABLED 🛠️" if active else "DISABLED ✅"
    color = 0xff0000 if active else 0x00ff00
    
    embed = discord.Embed(title=f"Maintenance Mode {status}", color=color)
    embed.add_field(name="Reason", value=reason)
    embed.add_field(name="Est. Duration", value=duration)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rank")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    m_status = get_maintenance_status()
    if m_status['active']:
        return await interaction.response.send_message(f"🛠️ **Bot is in Maintenance Mode.**\nReason: {m_status['reason']}", ephemeral=True)

    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message("Invalid Tier.", ephemeral=True)

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"tier": tier_upper, "region": region.value, "retired": False, "last_updated": datetime.datetime.utcnow()}},
        upsert=True
    )
    await interaction.response.send_message(f"✅ Updated {player} to {tier_upper}.")
# --- WEB UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS | Official</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 3px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100; }
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .sub-nav { display: flex; justify-content:center; gap: 8px; padding: 10px; background: #0f1117; border-bottom: 1px solid var(--border); overflow-x: auto; }
        .mode-btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 11px; transition: 0.2s; white-space: nowrap; }
        .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }
        
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; }
        .AF { color: #ff922b; } .OC { color: #339af0; } .SA { color: #ae3ec9; }

        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); z-index:1001; display:flex; justify-content:center; align-items:center; backdrop-filter: blur(10px); }
        .profile-modal { background: #11141c; width: 420px; border-radius: 24px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .close-btn { position: absolute; top: 20px; right: 25px; color: var(--dim); text-decoration: none; font-size: 30px; }
        
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 17px; }
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        
        .wrapper { max-width: 950px; margin: auto; padding: 30px 20px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 18px 25px; margin-bottom: 12px; display: grid; grid-template-columns: 50px 60px 1fr 100px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .rank-badge { font-size: 10px; padding: 2px 8px; border: 1px solid var(--accent); border-radius: 5px; margin-left: 12px; color: var(--accent); font-weight: 800; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search..." value="{{ search_query }}"></form>
    </div>
    
    <div class="sub-nav">
        <a href="/?region={{current_region}}" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}&region={{current_region}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" class="close-btn">&times;</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" style="width:100px; border-radius:15px; border:3px solid var(--accent);">
            <h1>{{ spotlight.username }}</h1>
            <p class="{{ spotlight.region }}" style="font-weight:800;">{{ spotlight.region }}</p>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:20px;">
                {% for s in spotlight.all_stats %}
                <div style="background:#1a1d26; padding:10px; border-radius:10px; border:1px solid var(--border);">
                    <small style="text-transform:uppercase;">{{ s.gamemode }}</small><br><b style="color:var(--accent);">{{ s.tier }}</b>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent);">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:8px;">
            <div><b>{{ p.username }}</b> <span class="rank-badge">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:#ffcc00;">{{ p.points }} PTS</div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""
@app.before_request
def check_for_maintenance():
    # Allow /api-docs to stay up or bypass if needed, otherwise block
    if request.path == '/api-docs':
        return
        
    m_status = get_maintenance_status()
    if m_status['active']:
        return render_template_string(MAINTENANCE_HTML, reason=m_status['reason'], duration=m_status['duration'])
@app.route('/')
def index():
    mode_f = request.args.get('mode', '').strip().lower()
    region_f = request.args.get('region', '').strip().upper()
    search_q = request.args.get('search', '').strip().lower()
    
    raw_players = list(players_col.find({"retired": {"$ne": True}}))
    stats = {}
    
    for p in raw_players:
        u, t, gm, reg = p['username'], p.get('tier', 'LT5'), p['gamemode'], p.get('region', 'NA')
        pts = p.get('points', 0)
        
        if region_f and reg != region_f: continue
        
        if u not in stats:
            stats[u] = {"pts": 0, "tier": t, "region": reg, "modes_active": []}
        
        stats[u]["modes_active"].append(gm.lower())
        
        if mode_f:
            if gm.lower() == mode_f:
                stats[u]["pts"] = pts
                stats[u]["tier"] = t
        else:
            stats[u]["pts"] += pts

    processed = []
    for u, d in stats.items():
        if (mode_f and mode_f in d["modes_active"]) or (not mode_f and d["pts"] > 0):
            processed.append({
                "username": u, "points": d["pts"], "tier": d["tier"], 
                "region": d["region"], "rank_name": get_global_rank(d["pts"])
            })

    processed = sorted(processed, key=lambda x: -x["points"])

    spotlight = None
    if search_q:
        p_data = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if p_data:
            spotlight = {
                "username": p_data[0]['username'],
                "region": p_data[0].get('region', 'NA'),
                "all_stats": [{"gamemode": d['gamemode'], "tier": d.get('tier', 'LT5')} for d in p_data]
            }

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, all_modes=MODES, all_regions=REGIONS, current_mode=mode_f, current_region=region_f)

@app.route('/api-docs')
def api_docs():
    return "<h1>Magma API</h1><p>Endpoint: /api/player/&lt;username&gt;</p>"

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
