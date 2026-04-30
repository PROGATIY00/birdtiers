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
# Higher index = Better Tier
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

# --- LOGIC HELPERS ---

def get_global_rank_name(tier_list):
    """Determines Global Rank based on tier density and quality."""
    if not tier_list: return "Stone"
    
    # Convert tiers to numerical weights
    weights = [TIER_ORDER.index(t) for t in tier_list if t in TIER_ORDER]
    top_tier = max(weights) if weights else -1
    count = len(weights)

    if top_tier >= 9 and count >= 3: return "Grandmaster"
    if top_tier >= 8: return "Master"
    if top_tier >= 6: return "Elite"
    if top_tier >= 4: return "Diamond"
    if top_tier >= 2: return "Gold"
    return "Bronze"

def get_maintenance_status():
    status = settings_col.find_one({"_id": "maintenance_mode"})
    return status if status else {"active": False, "reason": "None", "duration": "Unknown"}

# --- DISCORD BOT ---

class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="maintenance", description="Toggle maintenance mode")
async def maintenance(interaction: discord.Interaction, active: bool, reason: str = "Updates", duration: str = "1 hour"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    settings_col.update_one(
        {"_id": "maintenance_mode"}, 
        {"$set": {"active": active, "reason": reason, "duration": duration}}, 
        upsert=True
    )
    status = "ENABLED" if active else "DISABLED"
    await interaction.response.send_message(f"🛠️ Maintenance is now **{status}**.")

@bot.tree.command(name="rank", description="Update a player's tier")
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
    reason: str = "Performance in matches"
):
    if get_maintenance_status()['active']:
        return await interaction.callback.send_message("🛠️ System is in maintenance.", ephemeral=True)
    
    tier_upper = tier.upper().strip()
    if tier_upper not in TIER_ORDER:
        return await interaction.response.send_message(f"Invalid Tier. Valid: {', '.join(TIER_ORDER)}", ephemeral=True)

    # Database logic
    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"tier": tier_upper, "region": region.value, "retired": False, "last_updated": datetime.datetime.utcnow()}},
        upsert=True
    )

    # Log Formatting
    log_chan = bot.get_channel(int(LOG_CHANNEL_ID))
    if log_chan:
        embed = discord.Embed(
            title="Tier Update",
            description=(
                f"**{player}** -- {discord_user.name}\n"
                f"**User:** {discord_user.mention}\n"
                f"**Kit:** {mode.value}\n"
                f"**Promoted to {tier_upper}**\n"
                f"**Reason:** {reason}\n\n"
                f"**Tester:** {interaction.user.display_name} | **Region:** {region.value}"
            ),
            color=0xff4500,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
        await log_chan.send(embed=embed)

    await interaction.response.send_message(f"✅ Updated {player} to {tier_upper}.", ephemeral=True)

@bot.tree.command(name="match", description="Record silent activity")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES])
async def match(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str]):
    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"last_updated": datetime.datetime.utcnow(), "retired": False}},
        upsert=True
    )
    await interaction.response.send_message(f"✅ Activity logged for {player}.", ephemeral=True)

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
        .rank-badge { font-size: 10px; padding: 2px 8px; border: 1px solid var(--accent); border-radius: 5px; margin-left: 10px; color: var(--accent); font-weight: 800; text-transform: uppercase; }
        .wrapper { max-width: 900px; margin: auto; padding: 30px 20px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 18px 25px; margin-bottom: 12px; display: grid; grid-template-columns: 50px 60px 1fr 100px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; } .AF { color: #ff922b; } .OC { color: #339af0; } .SA { color: #ae3ec9; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search player..." value="{{ search_query }}"></form>
    </div>
    <div class="sub-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>
    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row">
            <div style="font-weight:800; color:var(--accent);">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" style="border-radius:8px;">
            <div><b>{{ p.username }}</b> <span class="rank-badge">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:var(--accent); font-size:18px;">{{ p.tier }}</div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.before_request
def check_maintenance():
    m = get_maintenance_status()
    if m['active']:
        return f"<body style='background:#0b0c10;color:white;text-align:center;padding-top:100px;font-family:sans-serif;'><h1>🛠️ Under Maintenance</h1><p>{m['reason']}</p><p>Est: {m['duration']}</p></body>", 503

@app.route('/')
def index():
    mode_f = request.args.get('mode', '').strip().lower()
    search_q = request.args.get('search', '').strip().lower()
    
    raw_data = list(players_col.find({"retired": {"$ne": True}}))
    user_map = {}

    # Aggregate user data
    for d in raw_data:
        u = d['username']
        if u not in user_map:
            user_map[u] = {"username": u, "tiers": [], "region": d.get('region', 'NA'), "best_tier": "LT5"}
        
        user_map[u]["tiers"].append(d['tier'])
        if TIER_ORDER.index(d['tier']) > TIER_ORDER.index(user_map[u]["best_tier"]):
            user_map[u]["best_tier"] = d['tier']

    processed = []
    for u, data in user_map.items():
        rank_name = get_global_rank_name(data["tiers"])
        
        if mode_f:
            # Filter for specific mode
            mode_entry = next((item for item in raw_data if item['username'] == u and item['gamemode'].lower() == mode_f), None)
            if mode_entry:
                processed.append({"username": u, "tier": mode_entry['tier'], "region": data['region'], "rank_name": rank_name})
        else:
            # Global view: Best Tier + Rank Name
            processed.append({"username": u, "tier": data["best_tier"], "region": data['region'], "rank_name": rank_name})

    if search_q:
        processed = [p for p in processed if search_q in p['username'].lower()]

    processed = sorted(processed, key=lambda x: TIER_ORDER.index(x['tier']), reverse=True)

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_f, search_query=search_q)

if __name__ == '__main__':
    # Start Web UI
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    # Start Discord Bot
    bot.run(TOKEN)
