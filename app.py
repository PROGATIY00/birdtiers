import discord
from discord import app_commands
from flask import Flask, render_template_string, request
from pymongo import MongoClient
import os
import threading
import asyncio
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 5 for i, t in enumerate(TIER_ORDER)}

# --- DB SETUP ---
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
partners_col = db_mongo['partners']
settings_col = db_mongo['settings']

def get_global_rank(pts):
    if pts >= 500: return "Combat Grandmaster"
    if pts >= 250: return "Combat Master"
    if pts >= 100: return "Combat Ace"
    if pts >= 50:  return "Combat Specialist"
    if pts >= 25:  return "Combat Cadet"
    if pts >= 10:  return "Combat Novice"
    return "Rookie"

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash commands synced.")

bot = MagmaBot()

@bot.tree.command(name="rank", description="Set a player's tier and region")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    
    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.followup.send(f"Invalid Tier. Use: {', '.join(TIER_ORDER)}")

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {
            "username": player, "gamemode": mode.value, "tier": tier_upper, 
            "region": region.value, "retired": False, "last_updated": datetime.datetime.utcnow()
        }},
        upsert=True
    )

    if LOG_CHANNEL_ID:
        try:
            chan = bot.get_channel(int(LOG_CHANNEL_ID))
            if chan:
                embed = discord.Embed(title="📈 Tier Updated", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
                embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
                embed.add_field(name="Player", value=player, inline=True)
                embed.add_field(name="Tier", value=tier_upper, inline=True)
                embed.add_field(name="Region", value=region.value, inline=True)
                await chan.send(embed=embed)
        except: pass

    await interaction.followup.send(f"✅ Updated **{player}** to **{tier_upper}** ({region.value})")

# --- WEB UI (FLASK) ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS | Official Leaderboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 3px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .sub-nav { display: flex; justify-content:center; gap: 8px; padding: 10px; background: #0f1117; border-bottom: 1px solid var(--border); overflow-x: auto; }
        .mode-btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 11px; transition: 0.2s; white-space: nowrap; }
        .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }
        .region-btn.active { border-color: #5865F2; color: white; background: #23272a; }
        .wrapper { max-width: 950px; margin: auto; padding: 25px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 15px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 40px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .player-row:hover { border-color: var(--accent); background: #1a1d26; transform: translateY(-2px); }
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; border-radius: 12px; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 14px; }
        .rank-badge { font-size: 10px; padding: 2px 8px; border: 1px solid var(--accent); border-radius: 4px; margin-left: 10px; color: var(--accent); text-transform: uppercase; font-weight: 800; }
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; } .AF { color: #ae3ec9; } .OC { color: #20c997; } .SA { color: #4dabf7; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white;" placeholder="Search..." value="{{ search_query }}"></form>
    </div>
    <div class="sub-nav">
        <a href="/?region={{current_region}}" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}&region={{current_region}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>
    <div class="sub-nav">
        <a href="/?mode={{current_mode}}" class="mode-btn region-btn {% if not current_region %}active{% endif %}">ALL REGIONS</a>
        {% for r in all_regions %}<a href="/?region={{r}}&mode={{current_mode}}" class="mode-btn region-btn {% if current_region == r %}active{% endif %}">{{r}}</a>{% endfor %}
    </div>
    <div class="wrapper">
        {% for p in players %}
        <a href="#" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div><b>{{ p.username }}</b> <span class="rank-badge">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:#ffcc00;">{{ p.points }} PTS</div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    mode_f = request.args.get('mode', '')
    region_f = request.args.get('region', '').upper()
    search_q = request.args.get('search', '').strip().lower()
    
    raw_players = list(players_col.find({"retired": False}))
    stats = {}
    
    for p in raw_players:
        u, t, gm, reg = p['username'], p['tier'], p['gamemode'], p.get('region', 'NA')
        if region_f and reg != region_f: continue
        if search_q and search_q not in u.lower(): continue
            
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "region": reg}
        
        if mode_f:
            if gm.lower() == mode_f.lower(): stats[u].update({"pts": val, "tier": t})
            else: stats[u]["pts"] = -1
        else:
            stats[u]["pts"] += val

    processed = sorted([
        {"username": u, "points": int(d["pts"]), "tier": d["tier"], "region": d["region"], "rank_name": get_global_rank(d["pts"])} 
        for u, d in stats.items() if d["pts"] > 0
    ], key=lambda x: -x["points"])

    return render_template_string(HTML_TEMPLATE, players=processed, search_query=search_q, all_modes=MODES, all_regions=REGIONS, current_mode=mode_f, current_region=region_f)

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
