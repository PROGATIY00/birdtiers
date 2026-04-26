import discord
from discord.ext import commands
from flask import Flask, render_template_string, request, redirect, session, url_for
import json
import os
import threading

# --- CONFIGURATION ---
# Use an Environment Variable on Render for the Token for security!
TOKEN = os.getenv("DISCORD_TOKEN", "MTQ5NzI5OTg5MTc1ODgyNTQ3Mg.GLlGY5.Uz223Kk9P43h3kaypRcr5201DbQ7KBhHqxggTo") 
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_LIST = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5", "RETIRED"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

app = Flask(__name__)
app.secret_key = "birdtiers_render_2026"
DB_FILE = 'database.json'

def load_db():
    if not os.path.exists(DB_FILE): return {"players": []}
    with open(DB_FILE, 'r') as f: return json.load(f)

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.command()
@commands.has_permissions(administrator=True)
async def rank(ctx, name: str, mode: str, tier: str, region: str):
    db = load_db()
    players = db.get('players', [])
    mode, tier, region = mode.capitalize(), tier.upper(), region.upper()
    
    for p in players:
        if p['username'].lower() == name.lower(): p['region'] = region
    
    players = [p for p in players if not (p['username'].lower() == name.lower() and p['gamemode'] == mode)]
    players.append({"username": name, "gamemode": mode, "tier": tier, "region": region})
    db['players'] = players
    save_db(db)
    await ctx.send(f"✅ **{name}** updated to **{tier}** in **{mode}** ({region})")

@bot.command()
@commands.has_permissions(administrator=True)
async def retire(ctx, name: str):
    db = load_db()
    for p in db['players']:
        if p['username'].lower() == name.lower(): p['tier'] = "RETIRED"
    save_db(db)
    await ctx.send(f"💀 **{name}** moved to Retired.")

# --- WEB UI (Simplified for speed) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        body { background: #0b0c10; color: #e0e6ed; font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 1px solid #262932; }
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; }
        .logo span { color: #5e6ad2; }
        .wrapper { max-width: 1000px; margin: auto; padding: 40px; }
        .player-row { background: #14171f; border: 1px solid #262932; border-radius: 12px; padding: 15px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }
        .retired { opacity: 0.4; filter: grayscale(1); }
        .na { color: #e74c3c; } .eu { color: #2ecc71; }
    </style>
</head>
<body>
    <div class="navbar"><a href="/" class="logo">BIRD<span>TIERS</span></a></div>
    <div class="wrapper">
        <h2>ACTIVE</h2>
        {% for p in players if p.display_tier != "RETIRED" %}
        <div class="player-row">
            <img src="{% if p.username.lower()=='g4lactic4l' %}/static/friend_skin.png{% else %}https://minotar.net/helm/{{p.username}}/40.png{% endif %}" width="40">
            <b>{{ p.username }}</b>
            <span class="{{ p.region.lower() }}">{{ p.region }}</span>
            <span style="color:#f59e0b">#{{ loop.index }}</span>
        </div>
        {% endfor %}
        <h2 style="margin-top:50px; color:#8b949e">RETIRED</h2>
        {% for p in players if p.display_tier == "RETIRED" %}
        <div class="player-row retired">
            <b>{{ p.username }}</b>
            <span>RETIRED</span>
        </div>
        {% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    db = load_db()
    stats = {}
    for p in db['players']:
        u = p['username']
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "ret": False}
        if p['tier'] == "RETIRED": stats[u]["ret"] = True
        stats[u]["pts"] += TIER_DATA.get(p['tier'], 0)
    
    processed = sorted([{"username": u, "total_points": d['pts'], "region": d['region'], "display_tier": "RETIRED" if d['ret'] else ""} for u, d in stats.items()], key=lambda x: x['total_points'], reverse=True)
    return render_template_string(HTML_TEMPLATE, players=processed)

def run_bot():
    if TOKEN != "YOUR_BOT_TOKEN_HERE":
        bot.run(TOKEN)

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    # Render requires binding to 0.0.0.0 and using the PORT env var
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
