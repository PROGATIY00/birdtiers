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

    # Fetch existing data for Peak and Previous tracking
    existing = players_col.find_one({"username": player, "gamemode": mode.value})
    status_text = "Placed into"
    old_tier = "None"
    peak_tier = tier_upper

    if existing:
        old_tier = existing.get('tier', 'None')
        peak_tier = existing.get('peak', tier_upper)
        
        # Determine movement status
        if TIER_ORDER.index(tier_upper) > TIER_ORDER.index(old_tier):
            status_text = "Promoted to"
        elif TIER_ORDER.index(tier_upper) < TIER_ORDER.index(old_tier):
            status_text = "Demoted to"
        else:
            status_text = "Updated in"
            
        # Update Peak if current tier is higher
        if TIER_ORDER.index(tier_upper) > TIER_ORDER.index(peak_tier):
            peak_tier = tier_upper

    # Update Database
    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {
            "username": player, "gamemode": mode.value, "tier": tier_upper, 
            "region": region.value, "peak": peak_tier, "retired": False, 
            "last_updated": datetime.datetime.utcnow()
        }},
        upsert=True
    )

    # Discord Logging (Official Feed Style)
    if LOG_CHANNEL_ID:
        try:
            chan = bot.get_channel(int(LOG_CHANNEL_ID))
            if chan:
                embed = discord.Embed(
                    title="Tier Update", 
                    description=f"**{player}** has been **{status_text}** **{tier_upper}**!",
                    color=discord.Color.orange(), 
                    timestamp=datetime.datetime.utcnow()
                )
                embed.add_field(name="Gamemode", value=mode.value, inline=False)
                embed.add_field(name="Region", value=region.value, inline=False)
                embed.add_field(name="Previous Tier", value=old_tier, inline=False)
                embed.add_field(name="Peak Tier", value=peak_tier, inline=False)
                embed.set_footer(text="MagmaTIERS Official Feed")
                await chan.send(embed=embed)
        except: pass

    await interaction.followup.send(f"✅ Successfully updated **{player}**.")

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
        
        /* Modal Styles */
        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:1001; display:flex; justify-content:center; align-items:center; }
        .profile-modal { background: #11141c; width: 400px; border-radius: 20px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .modal-avatar { width: 100px; height: 100px; border-radius: 50%; border: 3px solid var(--accent); margin-bottom: 15px; }

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
        <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search player..." value="{{ search_query }}"></form>
    </div>
    
    <div class="sub-nav">
        <a href="/?region={{current_region}}" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}&region={{current_region}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>
    
    <div class="sub-nav">
        <a href="/?mode={{current_mode}}" class="mode-btn region-btn {% if not current_region %}active{% endif %}">ALL REGIONS</a>
        {% for r in all_regions %}<a href="/?region={{r}}&mode={{current_mode}}" class="mode-btn region-btn {% if current_region == r %}active{% endif %}">{{r}}</a>{% endfor %}
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" style="position:absolute; top:15px; right:20px; color:#555; text-decoration:none; font-size:24px;">×</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1 style="margin:0;">{{ spotlight.username }}</h1>
            <p style="color:var(--accent); font-weight:800; margin-top:5px;">#{{ spotlight.pos }} OVERALL | {{ spotlight.region }}</p>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %}">
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
        
        # Region Filter
        if region_f and reg != region_f: continue
            
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "region": reg}
        
        if mode_f:
            if gm.lower() == mode_f.lower(): stats[u].update({"pts": val, "tier": t})
            else: stats[u]["pts"] = -1 # Filter out
        else:
            stats[u]["pts"] += val

    processed = sorted([
        {"username": u, "points": int(d["pts"]), "tier": d["tier"], "region": d["region"], "rank_name": get_global_rank(d["pts"])} 
        for u, d in stats.items() if d["pts"] > 0
    ], key=lambda x: -x["points"])

    spotlight = None
    if search_q:
        res = next((p for p in processed if p['username'].lower() == search_q), None)
        if res:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {"username": res['username'], "pos": pos, "region": res['region']}

    return render_template_string(HTML_TEMPLATE, 
        players=processed, 
        spotlight=spotlight, 
        search_query=search_q, 
        all_modes=MODES, 
        all_regions=REGIONS, 
        current_mode=mode_f, 
        current_region=region_f
    )

# --- EXECUTION ---
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
