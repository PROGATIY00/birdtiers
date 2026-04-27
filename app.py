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
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://discord.gg/2aBZzT6yyq")
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "False").lower() == "true"

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, retryWrites=True)
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"] 

TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, 
    "HT3": 60, "LT3": 50, "HT4": 40, "LT4": 30, 
    "HT5": 20, "LT5": 10
}

# --- DISCORD BOT ---
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()
bot = MyBot()

async def announce_change(embed):
    if not LOG_CHANNEL_ID: return
    try:
        channel = await bot.fetch_channel(int(LOG_CHANNEL_ID))
        await channel.send(embed=embed)
    except: pass

# --- SLASH COMMANDS ---
@bot.tree.command(name="rank", description="Set a player's tier")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, name: str, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    tier_up = tier.upper().strip()
    if tier_up == "RETIRED":
        return await interaction.response.send_message("❌ Use `/retire` instead.", ephemeral=True)

    name_clean = name.strip()
    players_col.update_one(
        {"username": {"$regex": f"^{name_clean}$", "$options": "i"}, "gamemode": mode.value},
        {"$set": {"username": name_clean, "gamemode": mode.value, "tier": tier_up, "region": region.value, "retired": False}},
        upsert=True
    )
    await interaction.response.send_message(f"✅ Updated {name_clean}.", ephemeral=True)
    
    embed = discord.Embed(title="📈 Tier Update", color=0x5e6ad2)
    embed.add_field(name="Player", value=name_clean, inline=True)
    embed.add_field(name="Mode", value=mode.value, inline=True)
    embed.add_field(name="Tier", value=tier_up, inline=True)
    embed.set_thumbnail(url=f"https://minotar.net/helm/{name_clean}/100.png")
    await announce_change(embed)

@bot.tree.command(name="retire", description="Retire a player")
@app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in MODES] + [app_commands.Choice(name="Global", value="all")])
async def retire(interaction: discord.Interaction, name: str, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    name_clean = name.strip()
    query = {"username": {"$regex": f"^{name_clean}$", "$options": "i"}}
    if mode.value != "all": query["gamemode"] = mode.value
    
    if players_col.count_documents(query) == 0:
        return await interaction.response.send_message("❌ Player not found.", ephemeral=True)

    players_col.update_many(query, {"$set": {"retired": True}})
    await interaction.response.send_message(f"💀 Retired {name_clean}.", ephemeral=True)
    
    embed = discord.Embed(title="💀 Retirement", color=0x666666)
    embed.description = f"**{name_clean}** is now retired from **{mode.value}**."
    embed.set_thumbnail(url=f"https://minotar.net/helm/{name_clean}/100.png")
    await announce_change(embed)

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "birdtiers_master_final"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; --discord: #5865F2; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .nav-right { display: flex; gap: 15px; align-items: center; }
        .search-input { background: #0b0c10; border: 1px solid var(--border); padding: 8px 18px; border-radius: 20px; color: white; outline: none; width: 180px; }
        .discord-btn { background: var(--discord); color: white; text-decoration: none; padding: 8px 16px; border-radius: 20px; font-size: 13px; font-weight: 600; transition: 0.2s; display: flex; align-items: center; gap: 8px; }
        .discord-btn:hover { background: #4752c4; transform: translateY(-2px); }
        .mode-nav { display: flex; gap: 8px; flex-wrap: wrap; padding: 15px 50px; background: #0f1117; border-bottom: 1px solid var(--border); justify-content: center; }
        .mode-btn { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 12px; font-weight: 600; }
        .mode-btn:hover, .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }
        .wrapper { max-width: 900px; margin: auto; padding: 25px; }
        .profile-card { background: linear-gradient(145deg, #1a1d29, #14171f); border: 2px solid var(--accent); border-radius: 18px; padding: 25px; margin-bottom: 30px; display: flex; gap: 25px; align-items: center; }
        .tier-box { background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; font-size: 11px; border: 1px solid var(--border); text-align: center; }
        .legacy-tier { display: inline-block; color: #666 !important; font-weight: 800; font-style: italic; text-decoration: line-through; text-decoration-thickness: 2px; transform: skewX(-15deg); opacity: 0.6; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 20px; margin-bottom: 8px; display: grid; grid-template-columns: 40px 45px 1fr 60px 110px; align-items: center; text-decoration: none; color: inherit; transition: 0.1s; }
        .player-row:hover { border-color: var(--accent); transform: translateX(5px); }
        .retired-row { opacity: 0.5; filter: grayscale(1); }
        .tier-badge { background: #1c1f26; padding: 5px 10px; border-radius: 6px; border: 1px solid #2d313d; text-align: center; font-weight: 800; font-size: 12px; }
        .na { color: #e74c3c; } .eu { color: #2ecc71; } .asia { color: #f1c40f; } .oc { color: #3498db; } .af { color: #e67e22; } .sa { color: #9b59b6; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">BIRD<span>TIERS</span></a>
        <div class="nav-right">
            <form><input type="text" name="search" class="search-input" placeholder="Search..." value="{{ search_query }}"></form>
            <a href="{{ discord_link }}" target="_blank" class="discord-btn">Discord</a>
        </div>
    </div>
    {% if maint and not session.get('admin') %}
    <div class="wrapper" style="text-align:center; margin-top:100px;"><h1>🛠️ Under Maintenance</h1></div>
    {% else %}
    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}
        <a href="/?mode={{m}}" class="mode-btn {% if current_mode.lower() == m.lower() %}active{% endif %}">{{m|upper}}</a>
        {% endfor %}
    </div>
    <div class="wrapper">
        {% if spotlight %}
        <div class="profile-card">
            <div style="text-align:center">
                <img src="https://minotar.net/helm/{{spotlight.username}}/80.png" style="border-radius:10px;">
                <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" style="font-size:10px; color:var(--dim); text-decoration:none; display:block; margin-top:5px;">NameMC</a>
            </div>
            <div style="flex-grow:1;">
                <h1 style="margin:0;">{{ spotlight.username }}</h1>
                <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(95px, 1fr)); gap:10px; margin-top:10px;">
                    {% for r in spotlight.ranks %}
                    <div class="tier-box">
                        <span style="color:var(--dim); font-size:10px;">{{r.gamemode}}</span><br>
                        <b class="{% if r.retired %}legacy-tier{% endif %}" style="color:var(--accent); font-size:16px;">{{r.tier}}</b>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endif %}
        {% for p in players %}
        <a href="/?search={{p.username}}{% if current_mode %}&mode={{current_mode}}{% endif %}" class="player-row {% if p.retired %}retired-row{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:5px;">
            <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.points }} Pts</small></div>
            <div class="{{ p.region.lower() }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div class="tier-badge">{% if p.retired %}RETIRED{% else %}{{ p.tier }}{% endif %}</div>
        </a>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    mode_filter, search_q = request.args.get('mode', ''), request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    stats = {}
    for p in players_data:
        u, gm, tier, ret = p['username'], p['gamemode'], p['tier'], p.get('retired', False)
        if mode_filter:
            if gm.lower() == mode_filter.lower():
                stats[u] = {"points": TIER_DATA.get(tier, 0), "region": p.get('region', 'NA'), "retired": ret, "tier": tier}
        else:
            if u not in stats: stats[u] = {"points": 0, "region": p.get('region', 'NA'), "retired": True}
            val = TIER_DATA.get(tier, 0)
            if not ret: (stats[u].update({"retired": False}), stats[u].update({"points": stats[u]["points"] + val}))
            else: stats[u]["points"] += (val * 0.1)

    processed = sorted([{"username": u, "points": int(d['points']), "region": d['region'], "retired": d['retired'], "tier": d.get('tier', 'N/A')} for u, d in stats.items() if d['points'] > 0], 
                       key=lambda x: (x['retired'], -x['points']))

    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res: spotlight = {"username": res[0]['username'], "ranks": res}

    return render_template_string(HTML_TEMPLATE, players=processed, all_modes=MODES, current_mode=mode_filter, discord_link=DISCORD_INVITE, search_query=search_q, maint=MAINTENANCE_MODE, spotlight=spotlight)

@app.route('/login')
def login(): session['admin'] = True; return redirect('/')

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000))), daemon=True).start()
    bot.run(TOKEN)
