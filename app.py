import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session, url_for
from pymongo import MongoClient
import os
import threading
import asyncio

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID") # Set this in Render!

# MongoDB Setup
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000) # Faster timeout
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

app = Flask(__name__)
app.secret_key = "birdtiers_slash_v3"

# --- DATABASE LOGIC ---
def update_db_rank(name, mode, tier, region):
    players_col.update_many({"username": {"$regex": f"^{name}$", "$options": "i"}}, {"$set": {"region": region.upper()}})
    players_col.update_one(
        {"username": {"$regex": f"^{name}$", "$options": "i"}, "gamemode": mode},
        {"$set": {"username": name, "gamemode": mode, "tier": tier.upper(), "region": region.upper()}},
        upsert=True
    )

# --- DISCORD BOT (Slash Commands) ---
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Syncing slash commands globally
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    print(f"✅ Bot Ready: {bot.user}")

# --- SLASH COMMANDS ---

@bot.tree.command(name="rank", description="Update a player's tier and region")
@app_commands.checks.has_permissions(administrator=True)
async def rank(interaction: discord.Interaction, name: str, mode: str, tier: str, region: str):
    mode = mode.capitalize()
    tier = tier.upper()
    if mode not in MODES or tier not in TIER_DATA:
        return await interaction.response.send_message("❌ Invalid Mode or Tier!", ephemeral=True)
    
    update_db_rank(name, mode, tier, region)
    
    # Send Announcement
    embed = discord.Embed(title="📈 Rank Update", color=0x5e6ad2)
    embed.add_field(name="Player", value=name)
    embed.add_field(name="Mode", value=mode)
    embed.add_field(name="New Tier", value=tier)
    embed.set_thumbnail(url=f"https://minotar.net/helm/{name}/64.png")
    
    await interaction.response.send_message(f"Updated {name}.", ephemeral=True)
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        await channel.send(embed=embed)

@bot.tree.command(name="retire", description="Move a player to retired status")
@app_commands.checks.has_permissions(administrator=True)
async def retire(interaction: discord.Interaction, name: str):
    players_col.update_many({"username": {"$regex": f"^{name}$", "$options": "i"}}, {"$set": {"tier": "RETIRED"}})
    
    embed = discord.Embed(title="💀 Player Retired", color=0x333333)
    embed.description = f"**{name}** has officially moved to the Retired Legends list."
    embed.set_thumbnail(url=f"https://minotar.net/helm/{name}/64.png")
    
    await interaction.response.send_message(f"{name} retired.", ephemeral=True)
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        await channel.send(embed=embed)

@bot.tree.command(name="check", description="View all tiers for a specific player")
async def check(interaction: discord.Interaction, name: str):
    data = list(players_col.find({"username": {"$regex": f"^{name}$", "$options": "i"}}))
    if not data:
        return await interaction.response.send_message("❌ Player not found.", ephemeral=True)
    
    embed = discord.Embed(title=f"🛡️ {data[0]['username']}'s Profiles", color=0x2ecc71)
    for entry in data:
        embed.add_field(name=entry['gamemode'], value=entry['tier'], inline=True)
    
    await interaction.response.send_message(embed=embed)

# --- WEB UI ---
# (Keeping the clean HTML Template from the previous version)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS | Live</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .wrapper { max-width: 1100px; margin: auto; padding: 40px; display: grid; grid-template-columns: 1fr; gap: 30px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 12px 20px; margin-bottom: 10px; display: grid; grid-template-columns: 50px 50px 220px 80px 1fr; align-items: center; text-decoration:none; color:inherit;}
        .avatar { width: 40px; height: 40px; border-radius: 8px; }
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; font-weight: 600; }
        .profile-card { background: #1a1d29; border: 2px solid var(--accent); border-radius: 20px; padding: 25px; margin-bottom: 30px; display: flex; gap: 20px; align-items: center; }
        .na { color: #e74c3c; border: 1px solid #e74c3c; padding: 2px 5px; border-radius: 4px; font-size: 10px;}
        .eu { color: #2ecc71; border: 1px solid #2ecc71; padding: 2px 5px; border-radius: 4px; font-size: 10px;}
    </style>
</head>
<body>
    <div class="navbar"><a href="/" class="logo">BIRD<span>TIERS</span></a></div>
    <div class="wrapper">
        <div class="main">
            {% if spotlight %}
            <div class="profile-card">
                <img src="https://minotar.net/helm/{{spotlight.username}}/80.png" style="border-radius:10px;">
                <div>
                    <h1 style="margin:0;">{{ spotlight.username }}</h1>
                    <div style="display:flex; gap:10px; margin-top:10px;">
                        {% for m, t in spotlight.ranks.items() %}<div style="background:#0b0c10; padding:5px; border-radius:5px; font-size:12px;">{{m}}: {{t}}</div>{% endfor %}
                    </div>
                    <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="color:var(--accent); font-size:12px;">View NameMC</a>
                </div>
            </div>
            {% endif %}

            <h2>🏆 ACTIVE LEADERBOARD</h2>
            {% for p in players if p.is_active %}
            <a href="/?search={{p.username}}" class="player-row">
                <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{p.username}}/40.png" class="avatar">
                <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.total_points }} Pts</small></div>
                <div><span class="{{ p.region.lower() }}">{{ p.region }}</span></div>
                <div class="tier-badge">HT{{loop.index}}</div>
            </a>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    search_q = request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    stats = {}
    for p in players_data:
        u = p['username']
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "is_active": False}
        if p.get('tier') != "RETIRED": stats[u]["is_active"] = True
        stats[u]["pts"] += TIER_DATA.get(p.get('tier'), 0)
    
    spotlight = None
    if search_q:
        user_ranks = [p for p in players_data if p['username'].lower() == search_q]
        if user_ranks: spotlight = {"username": user_ranks[0]['username'], "ranks": {p['gamemode']: p['tier'] for p in user_ranks}}

    processed = sorted([{"username": u, "total_points": d['pts'], "region": d['region'], "is_active": d['is_active']} for u, d in stats.items()], key=lambda x: x['total_points'], reverse=True)
    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight)

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    bot.run(TOKEN)
