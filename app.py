import discord
from discord import app_commands
from flask import Flask, render_template_string, request, jsonify
from pymongo import MongoClient
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
HIGH_TIER_CHANNEL_ID = os.getenv("HIGH_TIER_CHANNEL_ID")

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]

client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']

def get_global_rank(pts):
    if pts >= 500: return "Grandmaster"
    if pts >= 250: return "Master"
    if pts >= 150: return "Elite"
    if pts >= 100: return "Diamond"
    if pts >= 75:  return "Platinum"
    if pts >= 50:  return "Gold"
    if pts >= 25:  return "Silver"
    if pts >= 10:  return "Bronze"
    return "Stone"

class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Set a player's base tier")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, 
               player: str, 
               discord_user: discord.Member, 
               mode: app_commands.Choice[str], 
               tier: str, 
               region: app_commands.Choice[str], 
               failed_tier: str = None, 
               reason: str = "Placement"):
    
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    
    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message("Invalid Tier.", ephemeral=True)

    # Convert Tier to Points for the Elo system
    starting_pts = TIER_DATA.get(tier_upper, 0)

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {
            "username": player, 
            "gamemode": mode.value, 
            "tier": tier_upper, 
            "points": starting_pts,
            "region": region.value, 
            "retired": False, 
            "last_updated": datetime.datetime.utcnow()
        }},
        upsert=True
    )
    
    # Logging
    header = f"{discord_user.display_name} -- {player} "
    if failed_tier: header += f"Failed {failed_tier.upper()}"
    
    embed = discord.Embed(
        title="Tier Placement",
        description=f"**{header}**\nUser: {discord_user.mention}\nKit: **{mode.value}**\nTier: **{tier_upper}** ({starting_pts} PTS)\n\n**Reason:** {reason}",
        color=0xff4500,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")

    # Routing
    chan_id = HIGH_TIER_CHANNEL_ID if tier_upper in HIGH_TIERS else LOG_CHANNEL_ID
    if chan_id:
        try:
            chan = bot.get_channel(int(chan_id))
            if chan: await chan.send(embed=embed)
        except: pass

    await interaction.response.send_message(f"✅ Ranked **{player}** as {tier_upper}.")
# --- NEW MATCH COMMAND (WINS/LOSSES) ---
@bot.tree.command(name="match", description="Report a win or loss for a player")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    result=[app_commands.Choice(name="Win (+5)", value="win"), 
            app_commands.Choice(name="Loss (-5)", value="loss")]
)
async def match(interaction: discord.Interaction, 
                player: str, 
                discord_user: discord.Member, 
                mode: app_commands.Choice[str], 
                result: app_commands.Choice[str],
                region: app_commands.Choice[str],
                reason: str = "Match played"):
    
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

    # Calculate point change
    point_change = 5 if result.value == "win" else -5
    
    # Update DB with Win/Loss counters
    update_query = {
        "$inc": {
            "points": point_change,
            "wins": 1 if result.value == "win" else 0,
            "losses": 1 if result.value == "loss" else 0
        },
        "$set": {
            "username": player,
            "region": region.value,
            "gamemode": mode.value,
            "retired": False,
            "last_updated": datetime.datetime.utcnow()
        }
    }
    
    players_col.update_one({"username": player, "gamemode": mode.value}, update_query, upsert=True)
    
    # Fetch updated data for the log
    updated_p = players_col.find_one({"username": player, "gamemode": mode.value})
    new_total = updated_p.get("points", 0)
    current_rank = get_global_rank(new_total)

    # --- LOGGING ---
    embed = discord.Embed(
        title=f"Match Result: {mode.value}",
        description=f"**{discord_user.display_name} -- {player}**\nResult: **{result.name}**\nNew Total: **{new_total} PTS**\nRank: **{current_rank}**\n\n**Note:** {reason}",
        color=0x00ff00 if result.value == "win" else 0xff0000,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
    embed.set_footer(text=f"Tester: {interaction.user.display_name}")

    # Routing
    target_chan_id = HIGH_TIER_CHANNEL_ID if new_total >= 75 else LOG_CHANNEL_ID
    if target_chan_id:
        try:
            chan = bot.get_channel(int(target_chan_id))
            if chan: await chan.send(embed=embed)
        except: pass

    # DM User
    try:
        await discord_user.send(f"🎮 **Match Recorded!**\nYou gained {point_change} points in **{mode.value}**. Your new total is **{new_total}**.")
    except: pass

    await interaction.response.send_message(f"✅ Recorded {result.value} for {player}. Total: {new_total} PTS.")

@bot.tree.command(name="retire", description="Retire a player")
async def retire(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    players_col.update_many({"username": {"$regex": f"^{player}$", "$options": "i"}}, {"$set": {"retired": True}})
    await interaction.response.send_message(f"💀 Retired **{player}**.")
# --- WEB UI ---
app = Flask(__name__)

@app.route('/')
def index():
    raw_players = list(players_col.find({"retired": {"$ne": True}}))
    stats = {}
    for p in raw_players:
        u, t, reg = p['username'], p['tier'], p.get('region', 'NA')
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "region": reg}
        stats[u]["pts"] += val
    
    processed = sorted([{"username": u, "points": d["pts"], "tier": d["tier"], "region": d["region"], "rank_name": get_global_rank(d["pts"])} for u, d in stats.items()], key=lambda x: -x["points"])
# --- WEB UI & API ---
app = Flask(__name__)
@app.route('/discord')
def discord_redirect():
    window_location = request.args.get('window_location', 'https://dsc.gg/magma')
    return f"<script>window.location.href = '{window_location}';</script>"
@app.route('/api/player/<username>')
def get_player_api(username):
    # FIXED: Properly closed the dictionary and parentheses here
    p_data = list(players_col.find({"username": {"$regex": f"^{username}$", "$options": "i"}, "retired": {"$ne": True}}))
    if not p_data: 
        return jsonify({"tested": False}), 404
    
    return jsonify({
        "username": p_data[0]['username'],
        "tested": True,
        "region": p_data[0].get('region', 'NA'),
        "ranks": {d['gamemode']: d['tier'] for d in p_data}
    })
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

        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); z-index:1001; display:flex; justify-content:center; align-items:center; backdrop-filter: blur(10px); }
        .profile-modal { background: #11141c; width: 420px; border-radius: 24px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .close-btn { position: absolute; top: 20px; right: 25px; color: var(--dim); text-decoration: none; font-size: 30px; }
        .modal-avatar { width: 110px; height: 110px; border-radius: 15px; border: 4px solid var(--accent); margin-bottom: 20px; }
        
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 17px; }
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }

        .wrapper { max-width: 950px; margin: auto; padding: 30px 20px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 18px 25px; margin-bottom: 12px; display: grid; grid-template-columns: 50px 60px 1fr 100px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .rank-badge { font-size: 10px; padding: 2px 8px; border: 1px solid var(--accent); border-radius: 5px; margin-left: 12px; color: var(--accent); font-weight: 800; text-transform: uppercase; }
        
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; } 
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <div style="display:flex; align-items:center; gap:20px;">
            <a href="/api-docs" style="color:var(--dim); text-decoration:none; font-size:14px; font-weight:600;">API MENU</a>
            <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search player..." value="{{ search_query }}"></form>
        </div>
    </div>
    
    <div class="sub-nav">
        <a href="/?region={{current_region}}" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}&region={{current_region}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>
    
    <div class="sub-nav">
        <a href="/?mode={{current_mode}}" class="mode-btn {% if not current_region %}active{% endif %}">ALL REGIONS</a>
        {% for r in all_regions %}<a href="/?region={{r}}&mode={{current_mode}}" class="mode-btn {% if current_region == r %}active{% endif %}">{{r}}</a>{% endfor %}
    </div>

    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" class="close-btn">&times;</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1 style="margin:0;">{{ spotlight.username }}</h1>
            <p style="color:var(--dim); font-size:14px;">RANK #{{ spotlight.pos }} | {{ spotlight.region }}</p>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:25px;">
                {% for s in spotlight.all_stats %}
                <div style="background:#1a1d26; padding:10px; border-radius:10px; border:1px solid var(--border); text-align:left;">
                    <span style="font-size:9px; color:var(--dim); text-transform:uppercase; display:block;">{{ s.gamemode }}</span>
                    <b style="color:var(--accent);">{{ s.tier }}</b>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %}">
            <div style="font-weight:800; color:var(--accent); font-size: 18px;">#{{ loop.index }}</div>
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

@app.route('/')
def index():
    mode_f = request.args.get('mode', '').strip()
    region_f = request.args.get('region', '').strip().upper()
    search_q = request.args.get('search', '').strip().lower()
    
    # Strictly filter by retired=False
    raw_players = list(players_col.find({"retired": {"$ne": True}}))
    stats = {}
    
    for p in raw_players:
        u, t, gm, reg = p['username'], p['tier'], p['gamemode'], p.get('region', 'NA')
        if region_f and reg != region_f: continue
        val = TIER_DATA.get(t, 0)
        
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "region": reg, "modes_active": []}
        stats[u]["modes_active"].append(gm.lower())
        
        if mode_f:
            if gm.lower() == mode_f.lower(): stats[u].update({"pts": val, "tier": t})
            elif stats[u]["pts"] <= 0: stats[u]["pts"] = -2 
        else: stats[u]["pts"] += val

    processed = []
    for u, d in stats.items():
        if (mode_f and mode_f.lower() in d["modes_active"]) or (not mode_f and d["pts"] > 0):
            processed.append({"username": u, "points": int(d["pts"]), "tier": d["tier"], "region": d["region"], "rank_name": get_global_rank(d["pts"])})

    processed = sorted(processed, key=lambda x: -x["points"])

    spotlight = None
    if search_q:
        p_data = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}, "retired": {"$ne": True}}))
        if p_data:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {"username": p_data[0]['username'], "pos": pos, "region": p_data[0].get('region', 'NA'), "all_stats": [{"gamemode": d['gamemode'], "tier": d['tier']} for d in p_data]}

    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, all_modes=MODES, all_regions=REGIONS, current_mode=mode_f, current_region=region_f)

@app.route('/api-docs')
def api_docs():
    return "<h1>API Documentation</h1><p>Use <code>/api/player/{username}</code> to fetch JSON data.</p>"

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
