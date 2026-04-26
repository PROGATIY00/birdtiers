import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, session
from pymongo import MongoClient
import os
import threading

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# Maintenance toggle via Render Environment Variables
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "False").lower() == "true"

# Database Connection
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

# --- DISCORD BOT SETUP ---
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Bot Synced. Maintenance Mode: {MAINTENANCE_MODE}")

bot = MyBot()

# --- DATABASE HELPERS ---
def update_db(name, mode, tier, reg):
    name_clean = name.strip()
    mode_clean = mode.strip().capitalize()
    
    players_col.update_many(
        {"username": {"$regex": f"^{name_clean}$", "$options": "i"}}, 
        {"$set": {"region": reg.upper()}}
    )
    players_col.update_one(
        {"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode_clean},
        {"$set": {"username": name_clean, "gamemode": mode_clean, "tier": tier.upper(), "region": reg.upper()}},
        upsert=True
    )

# --- SLASH COMMANDS ---
@bot.tree.command(name="rank", description="Update a player's rank")
@app_commands.describe(mode="Gamemode", tier="Rank (HT1-LT5)", region="NA or EU")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES])
async def rank(interaction: discord.Interaction, name: str, mode: app_commands.Choice[str], tier: str, region: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only!", ephemeral=True)
    
    tier_up = tier.upper()
    if tier_up not in TIER_DATA:
        return await interaction.response.send_message(f"❌ Invalid tier: {tier_up}", ephemeral=True)

    update_db(name, mode.value, tier_up, region)
    
    embed = discord.Embed(title="📈 Rank Update", color=0x5e6ad2)
    embed.add_field(name="Player", value=name)
    embed.add_field(name="Mode", value=mode.value)
    embed.add_field(name="Tier", value=tier_up)
    embed.set_thumbnail(url=f"https://minotar.net/helm/{name}/64.png")
    
    await interaction.response.send_message(f"✅ Updated {name}", ephemeral=True)
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        if channel: await channel.send(embed=embed)

@bot.tree.command(name="retire", description="Retire a player from all leaderboards")
async def retire(interaction: discord.Interaction, name: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only!", ephemeral=True)
    
    players_col.update_many({"username": {"$regex": f"^{name}$", "$options": "i"}}, {"$set": {"tier": "RETIRED"}})
    
    embed = discord.Embed(title="💀 Retirement", description=f"**{name}** has officially retired.", color=0x333333)
    await interaction.response.send_message(f"💀 {name} retired.", ephemeral=False)
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        if channel: await channel.send(embed=embed)

@bot.tree.command(name="check", description="Check all ranks for a player")
async def check(interaction: discord.Interaction, name: str):
    data = list(players_col.find({"username": {"$regex": f"^{name}$", "$options": "i"}}))
    if not data: return await interaction.response.send_message("❌ Player not found.", ephemeral=True)
    embed = discord.Embed(title=f"🛡️ Profile: {data[0]['username']}", color=0x2ecc71)
    for entry in data: embed.add_field(name=entry['gamemode'], value=entry['tier'], inline=True)
    await interaction.response.send_message(embed=embed)

# --- WEB SERVER ---
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_KEY", "birdtiers_secret_2026")

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
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; width: 200px; transition: 0.2s;}
        .search-input:focus { width: 260px; border-color: var(--accent); }
        
        .mode-nav { display: flex; gap: 8px; flex-wrap: wrap; padding: 15px 50px; background: #0f1117; border-bottom: 1px solid var(--border); justify-content: center; }
        .mode-btn { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 12px; font-weight: 600; transition: 0.2s; }
        .mode-btn:hover, .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }

        .wrapper { max-width: 900px; margin: auto; padding: 25px; }

        /* Profile Card & Tilted Retirement */
        .profile-card { background: linear-gradient(145deg, #1a1d29, #14171f); border: 2px solid var(--accent); border-radius: 18px; padding: 25px; margin-bottom: 30px; display: flex; gap: 25px; align-items: center; box-shadow: 0 10px 20px rgba(0,0,0,0.4); }
        .tier-box { background: rgba(0,0,0,0.3); padding: 8px; border-radius: 8px; font-size: 11px; border: 1px solid var(--border); text-align: center; transition: 0.3s; }
        .tier-retired { opacity: 0.3; filter: grayscale(1); transform: rotate(-6deg); border-style: dashed; }
        .tier-retired b { text-decoration: line-through; color: var(--dim) !important; }

        /* Leaderboard */
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 20px; margin-bottom: 8px; display: grid; grid-template-columns: 40px 45px 1fr 70px 110px; align-items: center; text-decoration: none; color: inherit; transition: 0.15s; }
        .player-row:hover { border-color: var(--accent); transform: translateX(5px); background: #1c1f2b; }
        .retired-player { opacity: 0.4; filter: grayscale(1); }
        .tier-badge { background: #1c1f26; padding: 5px 10px; border-radius: 6px; border: 1px solid #2d313d; text-align: center; font-weight: 800; font-size: 12px; }
        .na { color: #e74c3c; font-weight: 800; }
        .eu { color: #2ecc71; font-weight: 800; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">BIRD<span>TIERS</span></a>
        <form action="/" method="GET"><input type="text" name="search" class="search-input" placeholder="Search player..." value="{{ search_query }}"></form>
    </div>
    
    {% if maint and not session.get('admin') %}
    <div class="wrapper" style="text-align:center; margin-top:100px;">
        <h1 style="color:var(--accent); font-size:48px;">🛠️ MAINTENANCE</h1>
        <p>Updating the tier list. Check back soon!</p>
    </div>
    {% else %}
    
    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}
        <a href="/?mode={{m}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>
        {% endfor %}
    </div>

    <div class="wrapper">
        {% if spotlight %}
        <div class="profile-card">
            <img src="https://minotar.net/helm/{{spotlight.username}}/80.png" style="border-radius:10px;">
            <div style="flex-grow:1;">
                <h1 style="margin:0;">{{ spotlight.username }}</h1>
                <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(95px, 1fr)); gap:10px; margin-top:10px;">
                    {% for m, t in spotlight.ranks.items() %}
                    <div class="tier-box {% if t == 'RETIRED' %}tier-retired{% endif %}">
                        {{m}}<br><b style="color:var(--accent)">{{t}}</b>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endif %}

        {% for p in players %}
        <a href="/?search={{p.username}}{% if current_mode %}&mode={{current_mode}}{% endif %}" class="player-row {% if not p.is_active %}retired-player{% endif %}">
            <div style="font-weight:800; color:var(--accent)">{% if not p.is_active %}💀{% else %}#{{ loop.index }}{% endif %}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:5px;">
            <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.points }} {{ 'Pts' if not current_mode else '' }}</small></div>
            <div class="{{ p.region.lower() }}">{{ p.region }}</div>
            <div class="tier-badge">{% if not p.is_active %}RETIRED{% else %}{{ p.tier if current_mode else 'ACTIVE' }}{% endif %}</div>
        </a>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    mode_filter = request.args.get('mode')
    search_q = request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    stats = {}
    for p in players_data:
        u = p['username']
        if mode_filter:
            if p['gamemode'] == mode_filter:
                stats[u] = {"points": p['tier'], "region": p.get('region', 'NA'), "active": p['tier'] != "RETIRED", "tier": p['tier']}
        else:
            if u not in stats: stats[u] = {"points": 0, "region": p.get('region', 'NA'), "active": False}
            if p.get('tier') != "RETIRED": stats[u]["active"] = True
            stats[u]["points"] += TIER_DATA.get(p.get('tier'), 0)
    
    processed = sorted([{"username": u, "points": d['points'], "region": d['region'], "is_active": d['active'], "tier": d.get('tier')} for u, d in stats.items() if u], 
                       key=lambda x: (not x['is_active'], -x['points'] if not mode_filter else 0))
    
    spotlight = None
    if search_q:
        user_ranks = [p for p in players_data if p['username'].lower() == search_q]
        if user_ranks: spotlight = {"username": user_ranks[0]['username'], "ranks": {p['gamemode']: p['tier'] for p in user_ranks}}

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_filter, maint=MAINTENANCE_MODE, spotlight=spotlight, search_query=search_q)

@app.route('/login')
def login():
    session['admin'] = True
    return redirect('/')

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000))), daemon=True).start()
    bot.run(TOKEN)
