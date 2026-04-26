import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session, url_for
from pymongo import MongoClient
import os
import threading

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

app = Flask(__name__)
app.secret_key = "birdtiers_permanent_history"

def update_db_rank(name, mode, tier, region):
    players_col.update_many({"username": {"$regex": f"^{name}$", "$options": "i"}}, {"$set": {"region": region.upper()}})
    players_col.update_one(
        {"username": {"$regex": f"^{name}$", "$options": "i"}, "gamemode": mode},
        {"$set": {"username": name, "gamemode": mode, "tier": tier.upper(), "region": region.upper()}},
        upsert=True
    )

# --- SLASH BOT ---
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="rank", description="Update a player's tier and region")
@app_commands.checks.has_permissions(administrator=True)
async def rank(interaction: discord.Interaction, name: str, mode: str, tier: str, region: str):
    mode = mode.capitalize()
    tier = tier.upper()
    update_db_rank(name, mode, tier, region)
    
    embed = discord.Embed(title="📈 Rank Update", color=0x5e6ad2)
    embed.add_field(name="Player", value=name)
    embed.add_field(name="Mode", value=mode)
    embed.add_field(name="Tier", value=tier)
    embed.set_thumbnail(url=f"https://minotar.net/helm/{name}/64.png")
    
    await interaction.response.send_message(f"Updated {name}.", ephemeral=True)
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        await channel.send(embed=embed)

@bot.tree.command(name="retire", description="Retire a player from all modes")
@app_commands.checks.has_permissions(administrator=True)
async def retire(interaction: discord.Interaction, name: str):
    players_col.update_many({"username": {"$regex": f"^{name}$", "$options": "i"}}, {"$set": {"tier": "RETIRED"}})
    embed = discord.Embed(title="💀 Retirement", description=f"**{name}** has retired.", color=0x333333)
    await interaction.response.send_message(f"{name} retired.", ephemeral=True)
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        await channel.send(embed=embed)

@bot.tree.command(name="check", description="Check all tiers for a player")
async def check(interaction: discord.Interaction, name: str):
    data = list(players_col.find({"username": {"$regex": f"^{name}$", "$options": "i"}}))
    if not data: return await interaction.response.send_message("Not found.", ephemeral=True)
    embed = discord.Embed(title=f"🛡️ {data[0]['username']}", color=0x2ecc71)
    for entry in data: embed.add_field(name=entry['gamemode'], value=entry['tier'], inline=True)
    await interaction.response.send_message(embed=embed)

# --- WEB UI ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS | Rankings</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 15px; border-radius: 20px; color: white; outline: none; width: 250px; }
        
        .wrapper { max-width: 900px; margin: auto; padding: 40px; }
        
        .profile-card { background: #1a1d29; border: 2px solid var(--accent); border-radius: 20px; padding: 30px; margin-bottom: 40px; display: flex; gap: 30px; align-items: center; }
        
        .player-row { 
            background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 12px 20px; margin-bottom: 10px; 
            display: grid; grid-template-columns: 50px 50px 220px 80px 1fr; align-items: center; 
            cursor: pointer; transition: 0.2s; text-decoration: none; color: inherit;
        }
        .player-row:hover { border-color: var(--accent); transform: scale(1.01); }
        
        /* THE RETIRED STYLE */
        .retired-player { opacity: 0.35; filter: grayscale(1); }
        .retired-player:hover { opacity: 0.6; filter: grayscale(0.5); }
        
        .avatar { width: 40px; height: 40px; border-radius: 8px; }
        .na { color: #e74c3c; border: 1px solid #e74c3c; padding: 2px 5px; border-radius: 4px; font-size: 10px; font-weight: 800;}
        .eu { color: #2ecc71; border: 1px solid #2ecc71; padding: 2px 5px; border-radius: 4px; font-size: 10px; font-weight: 800;}
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; font-weight: 600; }
        .retired-badge { color: var(--dim); border-color: var(--border); }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">BIRD<span>TIERS</span></a>
        <form action="/" method="GET"><input type="text" name="search" class="search-input" placeholder="Search..." value="{{ search_query }}"></form>
    </div>
    <div class="wrapper">
        {% if spotlight %}
        <div class="profile-card">
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" style="border-radius:12px;">
            <div style="flex-grow:1;">
                <h1 style="margin:0;">{{ spotlight.username }}</h1>
                <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap:10px; margin-top:15px;">
                    {% for m, t in spotlight.ranks.items() %}
                    <div style="background:rgba(0,0,0,0.2); padding:8px; border-radius:8px; font-size:12px; border:1px solid var(--border); text-align:center;">
                        {{m}}<br><b style="color:var(--accent)">{{t}}</b>
                    </div>
                    {% endfor %}
                </div>
                <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="display:inline-block; margin-top:15px; color:white; background:#333; padding:5px 12px; border-radius:5px; text-decoration:none; font-size:12px;">NameMC</a>
            </div>
        </div>
        {% endif %}

        <h2>🏆 LEADERBOARD</h2>
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row {% if not p.is_active %}retired-player{% endif %}">
            <div style="font-weight:800; color:{% if not p.is_active %}var(--dim){% else %}var(--accent){% endif %}">
                {% if not p.is_active %}💀{% else %}#{{ loop.index }}{% endif %}
            </div>
            <img src="https://minotar.net/helm/{{p.username}}/40.png" class="avatar">
            <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.total_points }} Pts</small></div>
            <div><span class="{{ p.region.lower() }}">{{ p.region }}</span></div>
            <div class="tier-badge {% if not p.is_active %}retired-badge{% endif %}">
                {% if not p.is_active %}RETIRED{% else %}ACTIVE{% endif %}
            </div>
        </a>
        {% endfor %}
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
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "active": False}
        if p.get('tier') != "RETIRED": stats[u]["active"] = True
        stats[u]["pts"] += TIER_DATA.get(p.get('tier'), 0)
    
    spotlight = None
    if search_q:
        user_ranks = [p for p in players_data if p['username'].lower() == search_q]
        if user_ranks: spotlight = {"username": user_ranks[0]['username'], "ranks": {p['gamemode']: p['tier'] for p in user_ranks}}

    processed = sorted([{"username": u, "total_points": d['pts'], "region": d['region'], "is_active": d['active']} for u, d in stats.items()], key=lambda x: (not x['is_active'], -x['total_points']))
    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q)

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000))), daemon=True).start()
    bot.run(TOKEN)
