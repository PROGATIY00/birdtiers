import discord
from discord import app_commands
from flask import Flask, render_template_string, request
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
settings_col = db_mongo['settings']

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
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Updates", duration: str = "1 hour"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

    settings_col.update_one(
        {"_id": "maintenance_mode"},
        {"$set": {"active": active, "reason": reason, "duration": duration}},
        upsert=True
    )
    await interaction.response.send_message(f"🛠️ Maintenance is now {'ENABLED' if active else 'DISABLED'}.")

@bot.tree.command(name="rank")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    m_status = get_maintenance_status()
    if m_status['active']:
        return await interaction.response.send_message("🛠️ Bot is in maintenance.", ephemeral=True)

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

MAINTENANCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Maintenance | MagmaTIERS</title>
    <style>
        body { background: #0b0c10; color: white; font-family: 'Fredoka', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; text-align: center; }
        .box { background: #14171f; padding: 50px; border-radius: 24px; border: 2px solid #ff4500; max-width: 500px; }
        h1 { color: #ff4500; margin: 0; }
        .meta { margin-top: 20px; padding: 15px; background: #0f1117; border-radius: 12px; font-size: 14px; color: #8b949e; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🛠️ MAINTENANCE</h1>
        <p>We are currently updating the system.</p>
        <div class="meta">
            <b>REASON:</b> {{ reason }}<br>
            <b>DURATION:</b> {{ duration }}
        </div>
    </div>
</body>
</html>
"""

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
        .profile-modal { background: #11141c; width: 400px; border-radius: 24px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .close-btn { position: absolute; top: 20px; right: 25px; color: var(--dim); text-decoration: none; font-size: 30px; }
        
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 17px; }
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        
        .wrapper { max-width: 900px; margin: auto; padding: 30px 20px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 18px 25px; margin-bottom: 12px; display: grid; grid-template-columns: 50px 60px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search..." value="{{ search_query }}"></form>
    </div>
    
    <div class="sub-nav">
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
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
        {% if not current_mode %}
            <div style="text-align:center; color:var(--dim); margin-top:50px;">Select a kit to view tiers.</div>
        {% else %}
            {% for p in players %}
            <a href="/?search={{p.username}}&mode={{current_mode}}" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %}">
                <div style="font-weight:800; color:var(--accent);">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:8px;">
                <div><b>{{ p.username }}</b></div>
                <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
                <div style="text-align:right; font-weight:800; color:var(--accent); font-size:18px;">{{ p.tier }}</div>
            </a>
            {% endfor %}
        {% endif %}
    </div>
</body>
</html>
"""

@app.before_request
def check_maintenance():
    m_status = get_maintenance_status()
    if m_status['active'] and request.path != '/maintenance_css_bypass': # hidden safety
        return render_template_string(MAINTENANCE_HTML, reason=m_status['reason'], duration=m_status['duration'])

@app.route('/')
def index():
    mode_f = request.args.get('mode', '').strip().lower()
    search_q = request.args.get('search', '').strip().lower()
    
    processed = []
    if mode_f:
        query = {"gamemode": {"$regex": f"^{mode_f}$", "$options": "i"}, "retired": {"$ne": True}}
        raw_players = list(players_col.find(query))
        
        for p in raw_players:
            processed.append({
                "username": p['username'],
                "tier": p.get('tier', 'LT5'),
                "region": p.get('region', 'NA')
            })
        
        # Sort by Tier Order
        processed = sorted(processed, key=lambda x: TIER_ORDER.index(x['tier']) if x['tier'] in TIER_ORDER else -1, reverse=True)

    spotlight = None
    if search_q:
        p_data = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if p_data:
            spotlight = {
                "username": p_data[0]['username'],
                "region": p_data[0].get('region', 'NA'),
                "all_stats": [{"gamemode": d['gamemode'], "tier": d.get('tier', 'LT5')} for d in p_data]
            }

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, all_modes=MODES, current_mode=mode_f)

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
