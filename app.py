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

# REQUIRED DATA FOR RANKING SYSTEM
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}
HIGH_TIERS = ["HT3", "LT2", "HT2", "LT1", "HT1"]

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

# --- HELPER LOGIC FOR MATCHES ---
async def process_match(interaction, player, discord_user, mode, is_win):
    point_change = 5 if is_win else -5
    result_text = "Win" if is_win else "Loss"
    
    players_col.update_one(
        {"username": player, "gamemode": mode},
        {"$inc": {"points": point_change, "wins": 1 if is_win else 0, "losses": 1 if not is_win else 0},
         "$set": {"last_updated": datetime.datetime.utcnow(), "retired": False}},
        upsert=True
    )
    
    p_data = players_col.find_one({"username": player, "gamemode": mode})
    new_total = p_data.get("points", 0)
    current_rank = get_global_rank(new_total)

    embed = discord.Embed(
        title=f"Match Result: {mode}",
        description=f"**{discord_user.display_name} -- {player}**\nResult: **{result_text} ({'+5' if is_win else '-5'})**\nNew Total: **{new_total} PTS**\nRank: **{current_rank}**",
        color=0x00ff00 if is_win else 0xff0000,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
    embed.set_footer(text=f"Tester: {interaction.user.display_name}")

    # Routing
    target_chan_id = HIGH_TIER_CHANNEL_ID if new_total >= 100 else LOG_CHANNEL_ID
    if target_chan_id:
        try:
            chan = bot.get_channel(int(target_chan_id))
            if chan: await chan.send(embed=embed)
        except: pass

    try: await discord_user.send(f"🎮 **Match Recorded!**\nResult: {result_text} in **{mode}**. New total: **{new_total} PTS**.")
    except: pass

    await interaction.response.send_message(f"✅ Recorded {result_text} for {player}. Total: {new_total} PTS.")

# --- COMMANDS ---
@bot.tree.command(name="win", description="Record a win for a player")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES])
async def win(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    await process_match(interaction, player, discord_user, mode.value, True)

@bot.tree.command(name="loss", description="Record a loss for a player")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES])
async def loss(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    await process_match(interaction, player, discord_user, mode.value, False)

@bot.tree.command(name="rank", description="Set a player's base tier")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str], reason: str = "Placement"):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    
    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message(f"Invalid Tier. Use: {', '.join(TIER_ORDER)}", ephemeral=True)

    starting_pts = TIER_DATA.get(tier_upper, 0)

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"username": player, "gamemode": mode.value, "tier": tier_upper, "points": starting_pts, "region": region.value, "retired": False, "last_updated": datetime.datetime.utcnow()}},
        upsert=True
    )
    
    embed = discord.Embed(
        title="Tier Placement",
        description=f"**{player}**\nKit: **{mode.value}**\nTier: **{tier_upper}** ({starting_pts} PTS)\nRegion: **{region.value}**\nReason: **{reason}**",
        color=0xff4500,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")

    target = HIGH_TIER_CHANNEL_ID if tier_upper in HIGH_TIERS else LOG_CHANNEL_ID
    if target:
        chan = bot.get_channel(int(target))
        if chan: await chan.send(embed=embed)

    await interaction.response.send_message(f"✅ Ranked **{player}** as {tier_upper}.")

@bot.tree.command(name="retire", description="Retire a player")
async def retire(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    players_col.update_many({"username": {"$regex": f"^{player}$", "$options": "i"}}, {"$set": {"retired": True}})
    await interaction.response.send_message(f"💀 Retired **{player}**.")

# --- WEB UI & API ---
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
        .wrapper { max-width: 950px; margin: auto; padding: 30px 20px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 18px 25px; margin-bottom: 12px; display: grid; grid-template-columns: 50px 60px 1fr 100px 120px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .rank-badge { font-size: 10px; padding: 2px 8px; border: 1px solid var(--accent); border-radius: 5px; margin-left: 12px; color: var(--accent); font-weight: 800; text-transform: uppercase; }
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; } 
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white;" placeholder="Search player..." value="{{ search_query }}"></form>
    </div>
    <div class="sub-nav">
        <a href="/?region={{current_region}}" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}&region={{current_region}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>
    <div class="wrapper">
        {% for p in players %}
        <div class="player-row">
            <div style="font-weight:800; color:var(--accent);">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:8px;">
            <div><b>{{ p.username }}</b> <span class="rank-badge">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:#ffcc00;">{{ p.points }} PTS</div>
        </div>
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
    
    raw_players = list(players_col.find({"retired": {"$ne": True}}))
    stats = {}
    
    for p in raw_players:
        u, pts, gm, reg = p['username'], p.get('points', 0), p['gamemode'], p.get('region', 'NA')
        if region_f and reg != region_f: continue
        if search_q and search_q not in u.lower(): continue

        if u not in stats: stats[u] = {"pts": 0, "region": reg, "modes_active": []}
        stats[u]["modes_active"].append(gm.lower())
        
        if mode_f:
            if gm.lower() == mode_f.lower(): stats[u]["pts"] = pts
        else:
            stats[u]["pts"] += pts

    processed = []
    for u, d in stats.items():
        if (mode_f and mode_f.lower() in d["modes_active"]) or (not mode_f and d["pts"] > 0):
            processed.append({"username": u, "points": int(d["pts"]), "region": d["region"], "rank_name": get_global_rank(d["pts"])})

    processed = sorted(processed, key=lambda x: -x["points"])
    return render_template_string(HTML_TEMPLATE, players=processed, search_query=search_q, all_modes=MODES, all_regions=REGIONS, current_mode=mode_f, current_region=region_f)

@app.route('/api/player/<username>')
def get_player_api(username):
    p_data = list(players_col.find({"username": {"$regex": f"^{username}$", "$options": "i"}, "retired": {"$ne": True}}))
    if not p_data: return jsonify({"tested": False}), 404
    return jsonify({"username": p_data[0]['username'], "region": p_data[0].get('region', 'NA'), "ranks": {d['gamemode']: d.get('points', 0) for d in p_data}})

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
