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
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      # Public Feed
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID") # Network Updates
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

MODE_ICONS = {
    "Crystal": "https://i.imgur.com/8QO5W5M.png",
    "UHC": "https://i.imgur.com/K4zI904.png",
    "Pot": "https://i.imgur.com/example_pot.png", 
}

# --- DATABASE SETUP ---
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
        intents.members = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"🌋 Bot logged in as {self.user}")

bot = MagmaBot()

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
async def maintenance(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    settings_col.update_one({"id": "maintenance"}, {"$set": {"enabled": enabled, "time": datetime.datetime.utcnow()}}, upsert=True)
    
    if STATUS_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(STATUS_CHANNEL_ID))
            embed = discord.Embed(
                title="📡 Network Status",
                description="🚨 **Maintenance Active**" if enabled else "✅ **Systems Live**",
                color=discord.Color.red() if enabled else discord.Color.green()
            )
            await channel.send(embed=embed)
        except Exception as e: print(f"Status Log Error: {e}")

    await interaction.response.send_message(f"Maintenance set to: {enabled}", ephemeral=True)

@bot.tree.command(name="rank", description="Set a player's tier")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

    tier = tier.upper().strip()
    if tier not in TIER_ORDER:
        return await interaction.response.send_message(f"Invalid Tier. Use: {', '.join(TIER_ORDER)}", ephemeral=True)

    existing = players_col.find_one({"username": player, "gamemode": mode.value})
    peak = tier
    if existing and TIER_ORDER.index(tier) < TIER_ORDER.index(existing.get('peak', 'LT5')):
        peak = existing.get('peak', tier)

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"username": player, "gamemode": mode.value, "tier": tier, "region": region.value, "peak": peak, "retired": False}},
        upsert=True
    )

    if LOG_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            await channel.send(f"🌋 **{player}** ranked **{tier}** in **{mode.value}** ({region.value})")
        except Exception as e: print(f"Rank Log Error: {e}")

    await interaction.response.send_message(f"✅ Success: {player} is now {tier} in {mode.value}.", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

MAINTENANCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS - Maintenance</title>
    <style>
        body { background: #0a0b0d; color: white; font-family: 'Fredoka', sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .box { background: #161a24; padding: 40px; border-radius: 20px; border: 1px solid #333; text-align: center; width: 400px; }
        #game { background: #000; width: 100%; height: 100px; margin-top: 20px; position: relative; border-radius: 10px; overflow: hidden; }
        #player { width: 20px; height: 20px; background: #ff4500; position: absolute; bottom: 0; left: 20px; }
        .obstacle { width: 15px; height: 15px; background: #888; position: absolute; bottom: 0; right: -20px; animation: move 1.5s infinite linear; }
        @keyframes move { from { right: -20px; } to { right: 100%; } }
        .jump { animation: jump 0.5s linear; }
        @keyframes jump { 0%, 100% { bottom: 0; } 50% { bottom: 40px; } }
    </style>
</head>
<body onclick="document.getElementById('player').classList.add('jump'); setTimeout(()=>document.getElementById('player').classList.remove('jump'), 500)">
    <div class="box">
        <h1 style="color:#ff4500">Updating...</h1>
        <p>Estimated Downtime: 15m</p>
        <div id="game"><div id="player"></div><div class="obstacle"></div></div>
        <p style="font-size:10px; color:#555; margin-top:10px;">Tap to jump</p>
    </div>
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
        .discord-btn { background: #5865F2; color: white; text-decoration: none; padding: 8px 16px; border-radius: 8px; font-weight: 600; }

        .mode-nav { display: flex; justify-content:center; gap: 8px; flex-wrap: wrap; padding: 15px; background: #0f1117; border-bottom: 1px solid var(--border); }
        .mode-btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 12px; }
        .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }

        /* MAGMA SPIN */
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; border-radius: 12px; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 14px; }

        /* PROFILE MODAL */
        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:1001; display:flex; justify-content:center; align-items:center; }
        .profile-modal { background: #11141c; width: 450px; border-radius: 20px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .modal-avatar { width: 100px; height: 100px; border-radius: 50%; border: 3px solid #ffcc00; margin-bottom: 15px; }
        .modal-tier-grid { display: grid; grid-template-columns: 1fr; gap: 10px; background: #080a0f; padding: 15px; border-radius: 12px; margin-top: 20px; max-height: 300px; overflow-y: auto; }
        .mode-item { display: flex; align-items: center; gap: 10px; background: #1c1f26; padding: 10px; border-radius: 8px; }
        .tier-badge { color: var(--accent); font-weight: 800; margin-left: auto; position: relative; cursor: help; }
        .peak-tooltip { visibility: hidden; background: #000; font-size: 10px; padding: 4px; position: absolute; bottom: 125%; left: 50%; transform: translateX(-50%); border-radius: 4px; white-space: nowrap; border: 1px solid var(--accent); }
        .tier-badge:hover .peak-tooltip { visibility: visible; }

        .wrapper { max-width: 900px; margin: auto; padding: 25px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 40px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; }
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; }

        .partner-img { height: 40px; margin: 0 15px; filter: grayscale(1); opacity: 0.5; transition: 0.3s; }
        .partner-img:hover { filter: grayscale(0); opacity: 1; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <div style="display:flex; align-items:center; gap:20px;">
            <form><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white;" placeholder="Search player..." value="{{ search_query }}"></form>
            <a href="{{ invite_link }}" target="_blank" class="discord-btn">Discord</a>
        </div>
    </div>

    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" style="position:absolute; top:15px; right:20px; color:#555; text-decoration:none; font-size:24px;">×</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1>{{ spotlight.username }}</h1>
            <p style="color:#ffcc00; font-weight:800;">#{{ spotlight.pos }} OVERALL | {{ spotlight.region }}</p>
            <div class="modal-tier-grid">
                {% for r in spotlight.ranks %}
                <div class="mode-item">
                    {% if r.gamemode in icons %}<img src="{{ icons[r.gamemode] }}" style="height:20px;">{% endif %}
                    <span style="font-size:13px; font-weight:600;">{{ r.gamemode }}</span>
                    <div class="tier-badge">{{ r.tier }}<span class="peak-tooltip">Peak: {{r.peak}}</span></div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div><b>{{ p.username }}</b> <span style="font-size:10px; padding:2px 8px; border:1px solid var(--accent); border-radius:4px; margin-left:10px;">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div class="tier-badge" style="text-align:right;">{{ p.tier }}<span class="peak-tooltip">Peak: {{p.peak}}</span></div>
        </a>
        {% endfor %}
    </div>

    <div style="text-align:center; padding:40px; border-top:1px solid var(--border);">
        {% for p in partners %}<a href="{{p.link}}"><img src="{{p.img}}" class="partner-img"></a>{% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if is_maint(): return render_template_string(MAINTENANCE_HTML)
    mode_f = request.args.get('mode', '')
    search_q = request.args.get('search', '').strip().lower()
    
    players_data = list(players_col.find({}))
    partners_data = list(partners_col.find({}))
    
    stats = {}
    for p in players_data:
        u, t, gm = p['username'], p['tier'], p['gamemode']
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "peak": p.get('peak', t), "region": p.get('region', 'NA'), "retired": p.get('retired', False)}
        
        if mode_f:
            if gm.lower() == mode_f.lower(): stats[u].update({"pts": val, "tier": t})
            else: stats[u]["pts"] = -1
        else:
            if not p.get('retired'): stats[u]["pts"] += val
            else: stats[u]["pts"] += (val * 0.1)

    processed = sorted([{"username": u, "points": int(d["pts"]), "tier": d["tier"], "peak": d["peak"], "region": d["region"], "rank_name": get_global_rank(d["pts"])[0]} for u, d in stats.items() if d["pts"] >= 0], key=lambda x: -x["points"])

    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {"username": res[0]['username'], "ranks": res, "pos": pos, "region": res[0].get('region', 'NA')}

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, all_modes=MODES, current_mode=mode_f, icons=MODE_ICONS, partners=partners_data, invite_link=DISCORD_INVITE)

def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
