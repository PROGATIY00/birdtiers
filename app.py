import discord
from discord.ext import commands
from flask import Flask, render_template_string, request, redirect, session, url_for
import json
import os
import threading
from pymongo import MongoClient

# Add this to your Environment Variables on Render as MONGO_URI
MONGO_URI = os.getenv("IL0WWRVucOYmBDme")
client = MongoClient(MONGO_URI)
db_mongo = client['birdtiers_db']
players_col = db_mongo['players']

def load_db():
    # Fetch all players from MongoDB
    players = list(players_col.find({}, {'_id': 0}))
    return {"players": players}

def save_db(data):
    # This is slightly different; we usually update specific players 
    # instead of overwriting the whole file.
    # For a quick fix, we wipe and re-insert (not ideal but works for small lists)
    players_col.delete_many({})
    if data['players']:
        players_col.insert_many(data['players'])
# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN", "MTQ5NzI5OTg5MTc1ODgyNTQ3Mg.GLlGY5.Uz223Kk9P43h3kaypRcr5201DbQ7KBhHqxggTo") 
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_LIST = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5", "RETIRED"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

app = Flask(__name__)
app.secret_key = "birdtiers_full_feature_2026"
DB_FILE = 'database.json'

def load_db():
    if not os.path.exists(DB_FILE): return {"players": []}
    try:
        with open(DB_FILE, 'r') as f: return json.load(f)
    except: return {"players": []}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- DISCORD BOT LOGIC ---
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

# --- WEB UI ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BIRDTIERS | Elite Rankings</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; padding: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; display: flex; align-items: center; border-bottom: 1px solid var(--border); }
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .wrapper { max-width: 1400px; margin: auto; display: grid; grid-template-columns: 3fr 1fr; gap: 30px; padding: 40px; }
        
        .search-bar { width:100%; background:var(--card); border:2px solid var(--border); padding:15px; border-radius:15px; color:white; margin-bottom:25px; outline:none; box-sizing: border-box; }
        
        .spotlight {
            background: linear-gradient(145deg, #1a1d29, #14171f);
            border: 2px solid var(--accent); border-radius: 20px;
            padding: 25px; margin-bottom: 30px; display: flex; align-items: center; gap: 25px;
        }
        .big-head { width: 80px; height: 80px; border-radius: 12px; border: 2px solid #222; }
        
        .nav-tabs { display: flex; gap: 8px; margin-bottom: 25px; flex-wrap: wrap; }
        .tab { background: var(--card); padding: 8px 18px; border-radius: 12px; text-decoration: none; color: var(--dim); font-weight: 600; border: 1px solid var(--border); font-size: 13px; }
        .tab.active { background: var(--accent); color: white; border-color: var(--accent); }

        .player-row {
            background: var(--card); border: 1px solid var(--border); border-radius: 15px;
            padding: 12px 20px; margin-bottom: 10px; display: grid;
            grid-template-columns: 50px 50px 220px 80px 1fr 40px; align-items: center;
        }
        .retired-row { opacity: 0.4; filter: grayscale(0.8); }
        .avatar { width: 40px; height: 40px; border-radius: 8px; }
        .na { color: #e74c3c; font-weight: 800; font-size: 10px; border: 1px solid #e74c3c; padding: 2px 5px; border-radius: 4px; }
        .eu { color: #2ecc71; font-weight: 800; font-size: 10px; border: 1px solid #2ecc71; padding: 2px 5px; border-radius: 4px; }
        
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; }
        .sidebar-box { background: #1c1f2b; border: 1px solid #ff4b2b; padding: 20px; border-radius: 18px; position: sticky; top: 20px; }
        input, select { width: 100%; background: #0b0c10; color: white; border: 1px solid #333; padding: 10px; border-radius: 8px; margin-bottom: 10px; font-family: 'Fredoka'; box-sizing: border-box; }
        .btn-update { background: linear-gradient(to right, #ff416c, #ff4b2b); color: white; border: none; padding: 12px; border-radius: 8px; width: 100%; font-weight: 800; cursor: pointer; text-transform: uppercase; }
    </style>
</head>
<body>
    <div class="navbar"><a href="/" class="logo">BIRD<span>TIERS</span></a></div>
    <div class="wrapper">
        <div class="main">
            <form action="/" method="GET"><input type="text" name="search" class="search-bar" placeholder="🔍 Search player profile..." value="{{ search_query }}"></form>

            {% if spotlight %}
            <div class="spotlight">
                <img src="{% if spotlight.username.lower()=='g4lactic4l' %}/static/friend_skin.png{% else %}https://minotar.net/helm/{{spotlight.username}}/80.png{% endif %}" class="big-head">
                <div style="flex-grow:1">
                    <h1 style="margin:0;">{{ spotlight.username }}</h1>
                    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">
                        {% for m, t in spotlight.ranks.items() %}
                        <div style="background:#0b0c10; padding:4px 10px; border-radius:8px; font-size:11px;">{{m}}: <b style="color:var(--accent)">{{t}}</b></div>
                        {% endfor %}
                    </div>
                </div>
            </div>
            {% endif %}

            <div class="nav-tabs">
                <a href="/" class="tab {% if not active_mode %}active{% endif %}">OVERALL</a>
                {% for mode in modes %}<a href="/?mode={{mode}}" class="tab {% if active_mode == mode %}active{% endif %}">{{mode}}</a>{% endfor %}
            </div>

            <h3>ACTIVE RANKINGS</h3>
            {% for p in players if p.display_tier != "RETIRED" %}
            <div class="player-row">
                <div style="font-weight:800; font-style:italic; color:{{'#5e6ad2' if loop.index <= 3 else '#333'}}">#{{ loop.index }}</div>
                <img src="{% if p.username.lower()=='g4lactic4l' %}/static/friend_skin.png{% else %}https://minotar.net/helm/{{p.username}}/40.png{% endif %}" class="avatar">
                <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.total_points }} Pts</small></div>
                <div><span class="{{ p.region.lower() }}">{{ p.region }}</span></div>
                <div class="tier-badge">
                    {% if not active_mode %}
                        <b style="color:{{ '#ffb800' if loop.index <= 5 else '#fff' }}">
                        {{ 'ELITE' if loop.index <= 5 else ('PRO' if loop.index <= 10 else 'BEGINNER') }}</b>
                    {% else %}<b style="color:var(--accent)">{{ p.display_tier }}</b>{% endif %}
                </div>
            </div>
            {% endfor %}

            <h3 style="margin-top:40px; color:var(--dim)">📜 RETIRED LEGENDS</h3>
            {% for p in players if p.display_tier == "RETIRED" %}
            <div class="player-row retired-row">
                <div style="font-size:18px;">💀</div>
                <img src="https://minotar.net/helm/{{p.username}}/40.png" class="avatar">
                <div style="grid-column: span 2;"><b>{{ p.username }}</b></div>
                <div class="tier-badge">RETIRED</div>
            </div>
            {% endfor %}
        </div>

        <div class="side">
            {% if session.get('logged_in') %}
            <div class="sidebar-box">
                <small style="color:#ff4b2b; font-weight:800;">ADMIN PANEL</small>
                <form action="/update" method="POST">
                    <input type="text" name="username" placeholder="Player name" required>
                    <select name="region"><option>NA</option><option>EU</option></select>
                    <select name="gamemode">{% for m in modes %}<option>{{m}}</option>{% endfor %}</select>
                    <select name="tier">{% for t in tier_list %}<option>{{t}}</option>{% endfor %}</select>
                    <button type="submit" class="btn-update">Update Tier</button>
                </form>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    mode, search_q = request.args.get('mode'), request.args.get('search', '').strip().lower()
    db = load_db()
    players_data = db.get('players', [])
    stats = {}
    for p in players_data:
        u = p['username']
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "ret": False}
        if p['tier'] == "RETIRED": stats[u]["ret"] = True
        stats[u]["pts"] += TIER_DATA.get(p['tier'], 0)
    
    spotlight = None
    if search_q:
        user_ranks = [p for p in players_data if p['username'].lower() == search_q]
        if user_ranks: spotlight = {"username": user_ranks[0]['username'], "ranks": {p['gamemode']: p['tier'] for p in user_ranks}}

    if mode:
        display = [p for p in players_data if p['gamemode'] == mode]
        processed = [{"username": p['username'], "display_tier": p['tier'], "total_points": TIER_DATA.get(p['tier'], 0), "region": p.get('region', 'NA')} for p in display]
    else:
        processed = [{"username": u, "total_points": d['pts'], "region": d['region'], "display_tier": "RETIRED" if d['ret'] else ""} for u, d in stats.items()]

    if search_q: processed = [p for p in processed if search_q in p['username'].lower()]
    processed = sorted(processed, key=lambda x: x['total_points'], reverse=True)
    return render_template_string(HTML_TEMPLATE, players=processed, modes=MODES, active_mode=mode, tier_list=TIER_LIST, search_query=search_q, spotlight=spotlight)

@app.route('/update', methods=['POST'])
def update():
    if not session.get('logged_in'): return redirect('/')
    name, mode, tier, reg = request.form['username'].strip(), request.form['gamemode'], request.form['tier'], request.form['region']
    db = load_db()
    players = db.get('players', [])
    for p in players:
        if p['username'].lower() == name.lower(): p['region'] = reg
    players = [p for p in players if not (p['username'].lower() == name.lower() and p['gamemode'] == mode)]
    players.append({"username": name, "gamemode": mode, "tier": tier, "region": reg})
    db['players'] = players
    save_db(db)
    return redirect(url_for('index', search=name))

@app.route('/login')
def login():
    session['logged_in'] = True
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    threading.Thread(target=lambda: bot.run(TOKEN) if TOKEN != "YOUR_BOT_TOKEN_HERE" else print("Bot token missing"), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
