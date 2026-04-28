import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session
from pymongo import MongoClient
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      # Public Feed
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID") # Network Updates
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# --- DATA MAPS ---
MODE_ICONS = {
    "Crystal": "https://i.imgur.com/8QO5W5M.png",
    "UHC": "https://i.imgur.com/K4zI904.png",
    "Pot": "https://i.imgur.com/example_pot.png", # Replace with real URLs
}

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

# --- DB SETUP ---
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
partners_col = db_mongo['partners']
settings_col = db_mongo['settings']

def get_global_rank(pts):
    if pts >= 400: return "Combat Grandmaster", "rank-grand-master"
    if pts >= 200: return "Combat Master", "rank-combat-master"
    return "Combat Ace", "rank-combat-ace"

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
        activity = discord.Activity(type=discord.ActivityType.watching, name="⚠️ MAINTENANCE" if m else "🎮 MagmaTIERS LIVE")
        await self.change_presence(status=discord.Status.dnd if m else discord.Status.online, activity=activity)

    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
async def maintenance(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator: return
    settings_col.update_one({"id": "maintenance"}, {"$set": {"enabled": enabled, "timestamp": datetime.datetime.utcnow().isoformat()}})
    await bot.update_presence()
    if STATUS_CHANNEL_ID:
        try:
            ch = await bot.fetch_channel(int(STATUS_CHANNEL_ID))
            embed = discord.Embed(title="📡 Network Status", description="Maintenance is now **ACTIVE**" if enabled else "All systems **ONLINE**", color=discord.Color.red() if enabled else discord.Color.green())
            await ch.send(embed=embed)
        except: pass
    await interaction.response.send_message(f"Maintenance: {enabled}", ephemeral=True)

@bot.tree.command(name="rank", description="Set player rank")
async def rank(interaction: discord.Interaction, name: str, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.administrator: return
    tier, name = tier.upper().strip(), name.strip()
    existing = players_col.find_one({"username": name, "gamemode": mode})
    old_tier = existing['tier'] if existing else "N/A"
    peak = existing.get('peak', tier) if existing else tier
    if tier in TIER_ORDER and peak in TIER_ORDER:
        if TIER_ORDER.index(tier) > TIER_ORDER.index(peak): peak = tier
    players_col.update_one({"username": name, "gamemode": mode}, {"$set": {"username": name, "gamemode": mode, "tier": tier, "region": region.upper(), "retired": False, "peak": peak}}, upsert=True)
    if LOG_CHANNEL_ID:
        try:
            ch = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            await ch.send(f"🌋 **{name}** updated to **{tier}** in **{mode}** (Prev: {old_tier})")
        except: pass
    await interaction.response.send_message(f"Updated {name}", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

MAINTENANCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS - Maintenance</title>
    <style>
        body { background: #0a0b0d; color: white; font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; overflow: hidden; }
        .box { background: #161a24; padding: 40px; border-radius: 20px; border: 1px solid #333; text-align: center; width: 500px; }
        #game { background: #000; width: 100%; height: 150px; margin-top: 20px; position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #444;}
        #player { width: 20px; height: 20px; background: #ff4500; position: absolute; bottom: 0; left: 50px; }
        .obstacle { width: 20px; height: 20px; background: #555; position: absolute; bottom: 0; right: -20px; animation: move 1.5s infinite linear; }
        @keyframes move { from { right: -20px; } to { right: 100%; } }
        .jump { animation: jump 0.5s linear; }
        @keyframes jump { 0% { bottom: 0; } 30% { bottom: 50px; } 70% { bottom: 50px; } 100% { bottom: 0; } }
    </style>
</head>
<body onclick="jump()">
    <div class="box">
        <h1 style="color:#ff4500">System Down</h1>
        <p>Estimated Downtime: <span id="timer">Calculating...</span></p>
        <div id="game"><div id="player"></div><div class="obstacle"></div></div>
        <p style="font-size: 12px; color: #888; margin-top: 15px;">Click or tap to jump while you wait.</p>
    </div>
    <script>
        function jump(){ document.getElementById('player').classList.add('jump'); setTimeout(()=>document.getElementById('player').classList.remove('jump'), 500); }
        let end = new Date(); end.setMinutes(end.getMinutes() + 30);
        setInterval(()=>{
            let diff = end - new Date();
            if(diff < 0) { document.getElementById('timer').innerText = "Almost there..."; return; }
            let m = Math.floor(diff/60000), s = Math.floor((diff%60000)/1000);
            document.getElementById('timer').innerText = m + "m " + s + "s";
        }, 1000);
    </script>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; }
        
        /* HERITAGE MAGMA SPIN */
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; border-radius: 12px; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 14px; }

        /* MODAL */
        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:1001; display:flex; justify-content:center; align-items:center; }
        .profile-modal { background: #11141c; width: 450px; border-radius: 20px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .modal-avatar { width: 100px; height: 100px; border-radius: 50%; border: 3px solid #ffcc00; margin-bottom: 15px; }
        .modal-tier-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; background: #080a0f; padding: 20px; border-radius: 12px; margin-top: 20px; }
        .mode-item { display: flex; align-items: center; gap: 10px; background: #1c1f26; padding: 10px; border-radius: 8px; border: 1px solid #333; }
        .mode-icon { height: 24px; width: 24px; object-fit: contain; }
        .tier-badge { color: var(--accent); font-weight: 800; font-size: 14px; position: relative; cursor: help; margin-left: auto; }
        .peak-tooltip { visibility: hidden; background: #000; color: #fff; font-size: 10px; padding: 4px; position: absolute; bottom: 125%; left: 50%; transform: translateX(-50%); border-radius: 4px; border: 1px solid var(--accent); opacity: 0; transition: 0.2s; white-space: nowrap; z-index: 10; }
        .tier-badge:hover .peak-tooltip { visibility: visible; opacity: 1; }

        /* REGIONS */
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; } .AF { color: #f76707; } .OC { color: #3498db; } .SA { color: #ae3ec9; }
        
        .wrapper { max-width: 900px; margin: auto; padding: 25px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 40px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; }
        .global-rank { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; margin-left: 8px; border: 1px solid #ff4500; color: #ff4500; }
        
        .partner-slider { margin-top: 50px; padding: 20px; text-align: center; border-top: 1px solid var(--border); }
        .partner-img { height: 40px; margin: 0 15px; filter: grayscale(1); opacity: 0.5; transition: 0.3s; }
        .partner-img:hover { filter: grayscale(0); opacity: 1; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form><input type="text" name="search" class="search-input" placeholder="Search..." value="{{ search_query }}"></form>
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" style="position:absolute; top:15px; right:20px; color:#555; text-decoration:none; font-size:24px;">×</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1 style="margin:0;">{{ spotlight.username }}</h1>
            <div style="color: #ffcc00; font-weight: 800; font-size: 12px; margin-top: 5px;">{{ spotlight.region }} | OVERALL #{{ spotlight.pos }}</div>
            
            <div class="modal-tier-grid">
                {% for r in spotlight.ranks %}
                <div class="mode-item">
                    {% if r.gamemode in icons %}<img src="{{ icons[r.gamemode] }}" class="mode-icon">{% endif %}
                    <span style="font-size:11px; font-weight:600;">{{ r.gamemode }}</span>
                    <div class="tier-badge">{{ r.tier }}<span class="peak-tooltip">Peak: {{r.peak}}</span></div>
                </div>
                {% endfor %}
            </div>
            <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="display:block; margin-top:20px; color:var(--dim); font-size:12px;">NameMC Profile</a>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        {% for p in players %}
        {% set is_top = p.tier in ['HT1', 'LT1'] %}
        <a href="/?search={{p.username}}" class="player-row {% if is_top %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div><b {% if is_top %}style="color:#fff; text-shadow: 0 0 10px #ff4500;"{% endif %}>{{ p.username }}</b> <span class="global-rank">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div class="tier-badge" style="text-align:right;">{{ p.tier }}<span class="peak-tooltip">Peak: {{p.peak}}</span></div>
        </a>
        {% endfor %}
    </div>

    <div class="partner-slider">
        <p style="color:var(--dim); font-size:10px; text-transform:uppercase; margin-bottom:15px;">Partners</p>
        {% for partner in partners %}<a href="{{ partner.link }}"><img src="{{ partner.img }}" class="partner-img"></a>{% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if is_maint(): return render_template_string(MAINTENANCE_HTML)
    search_q = request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    partners_data = list(partners_col.find({}))
    
    stats = {}
    for p in players_data:
        u, t, ret = p['username'], p['tier'], p.get('retired', False)
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "peak": p.get('peak', t), "region": p.get('region', 'NA'), "retired": True}
        if not ret: stats[u]["retired"] = False; stats[u]["pts"] += val
        else: stats[u]["pts"] += (val * 0.1)

    processed = sorted([{"username": u, "points": int(d["pts"]), "tier": d["tier"], "peak": d["peak"], "region": d["region"], "retired": d["retired"], "rank_name": get_global_rank(d["pts"])[0]} for u, d in stats.items()], key=lambda x: (x["retired"], -x["points"]))

    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {"username": res[0]['username'], "ranks": res, "pos": pos, "region": res[0].get('region', 'NA')}

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, icons=MODE_ICONS, partners=partners_data)

if __name__ == '__main__':
    threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
