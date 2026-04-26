import discord
from discord.ext import commands
from flask import Flask, render_template_string, request, redirect, session, url_for
from pymongo import MongoClient
import os
import threading

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# MongoDB Setup
client = MongoClient(MONGO_URI)
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_LIST = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5", "RETIRED"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

app = Flask(__name__)
app.secret_key = "birdtiers_permanent_2026"

# --- DATABASE HELPERS ---
def get_all_players():
    return list(players_col.find({}, {'_id': 0}))

def update_player_rank(name, mode, tier, region):
    # Sync region for all entries of this player
    players_col.update_many(
        {"username": {"$regex": f"^{name}$", "$options": "i"}},
        {"$set": {"region": region.upper()}}
    )
    # Update or Insert specific gamemode rank
    players_col.update_one(
        {"username": {"$regex": f"^{name}$", "$options": "i"}, "gamemode": mode},
        {"$set": {"username": name, "gamemode": mode, "tier": tier.upper(), "region": region.upper()}},
        upsert=True
    )

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.command()
@commands.has_permissions(administrator=True)
async def rank(ctx, name: str, mode: str, tier: str, region: str):
    mode = mode.capitalize()
    if mode not in MODES or tier.upper() not in TIER_LIST:
        return await ctx.send("❌ Invalid Mode or Tier!")
    
    update_player_rank(name, mode, tier, region)
    await ctx.send(f"✅ **{name}** is now **{tier.upper()}** in **{mode}** ({region.upper()}). Data saved permanently.")

@bot.command()
@commands.has_permissions(administrator=True)
async def retire(ctx, name: str):
    players_col.update_many(
        {"username": {"$regex": f"^{name}$", "$options": "i"}},
        {"$set": {"tier": "RETIRED"}}
    )
    await ctx.send(f"💀 **{name}** has been retired.")

# --- WEB UI (Full Aesthetic) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS | Permanent Rankings</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; display: flex; align-items: center; border-bottom: 1px solid var(--border); }
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .wrapper { max-width: 1400px; margin: auto; display: grid; grid-template-columns: 3fr 1fr; gap: 30px; padding: 40px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 12px 20px; margin-bottom: 10px; display: grid; grid-template-columns: 50px 50px 220px 80px 1fr; align-items: center; }
        .avatar { width: 40px; height: 40px; border-radius: 8px; }
        .na { color: #e74c3c; border: 1px solid #e74c3c; padding: 2px 5px; border-radius: 4px; font-size: 10px; }
        .eu { color: #2ecc71; border: 1px solid #2ecc71; padding: 2px 5px; border-radius: 4px; font-size: 10px; }
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; font-weight: 600; }
        .retired-row { opacity: 0.4; filter: grayscale(0.8); }
    </style>
</head>
<body>
    <div class="navbar"><a href="/" class="logo">BIRD<span>TIERS</span></a></div>
    <div class="wrapper">
        <div class="main">
            <h2>ACTIVE PLAYERS</h2>
            {% for p in players if p.display_tier != "RETIRED" %}
            <div class="player-row">
                <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
                <img src="{% if p.username.lower()=='g4lactic4l' %}/static/friend_skin.png{% else %}https://minotar.net/helm/{{p.username}}/40.png{% endif %}" class="avatar">
                <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.total_points }} Pts</small></div>
                <div><span class="{{ p.region.lower() }}">{{ p.region }}</span></div>
                <div class="tier-badge">
                    {% if loop.index <= 5 %}<span style="color:#ffb800">ELITE</span>
                    {% elif loop.index <= 10 %}<span style="color:#fff">PRO</span>
                    {% else %}<span style="color:var(--dim)">BEGINNER</span>{% endif %}
                </div>
            </div>
            {% endfor %}

            <h2 style="margin-top:50px; color:var(--dim)">📜 RETIRED LEGENDS</h2>
            {% for p in players if p.display_tier == "RETIRED" %}
            <div class="player-row retired-row">
                <div>💀</div>
                <img src="https://minotar.net/helm/{{p.username}}/40.png" class="avatar">
                <div style="grid-column: span 2;"><b>{{ p.username }}</b></div>
                <div class="tier-badge">RETIRED</div>
            </div>
            {% endfor %}
        </div>
        <div class="side">
            <div style="background:var(--card); padding:20px; border-radius:15px; border:1px solid var(--border); font-size:13px; color:var(--dim)">
                Use <b>!rank</b> in Discord to update tiers permanently. Data is now stored in MongoDB.
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    players_data = get_all_players()
    stats = {}
    for p in players_data:
        u = p['username']
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "ret": False}
        if p['tier'] == "RETIRED": stats[u]["ret"] = True
        stats[u]["pts"] += TIER_DATA.get(p['tier'], 0)
    
    processed = sorted([
        {"username": u, "total_points": d['pts'], "region": d['region'], "display_tier": "RETIRED" if d['ret'] else ""} 
        for u, d in stats.items()
    ], key=lambda x: x['total_points'], reverse=True)
    
    return render_template_string(HTML_TEMPLATE, players=processed)

if __name__ == '__main__':
    if TOKEN:
        threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
