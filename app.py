import discord
from discord.ext import commands
from flask import Flask, render_template_string, request, redirect, session, url_for
from pymongo import MongoClient
import os
import threading

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db_mongo = client['birdtiers_db']
    players_col = db_mongo['players']
except:
    print("DB Connection Failed")

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_LIST = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5", "RETIRED"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10, "RETIRED": 0
}

app = Flask(__name__)
app.secret_key = "birdtiers_profile_v2"

# --- DATABASE HELPERS ---
def get_all_players():
    try: return list(players_col.find({}, {'_id': 0}))
    except: return []

def update_player_rank(name, mode, tier, region):
    players_col.update_many({"username": {"$regex": f"^{name}$", "$options": "i"}}, {"$set": {"region": region.upper()}})
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
    update_player_rank(name, mode.capitalize(), tier.upper(), region.upper())
    await ctx.send(f"✅ Updated **{name}**")

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
        
        .wrapper { max-width: 1100px; margin: auto; padding: 40px; display: grid; grid-template-columns: {% if session.get('logged_in') %}3fr 1.2fr{% else %}1fr{% endif %}; gap: 30px; }
        
        /* Profile Card Styling */
        .profile-card { background: linear-gradient(145deg, #1a1d29, #14171f); border: 2px solid var(--accent); border-radius: 20px; padding: 30px; margin-bottom: 40px; display: flex; align-items: flex-start; gap: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        .big-head { width: 100px; height: 100px; border-radius: 15px; border: 3px solid #2d313d; }
        .namemc-btn { display: inline-block; background: #fff; color: #000; padding: 6px 15px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 12px; margin-top: 10px; transition: 0.2s; }
        .namemc-btn:hover { background: var(--accent); color: white; }
        
        .tier-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin-top: 15px; width: 100%; }
        .tier-item { background: rgba(0,0,0,0.3); padding: 8px; border-radius: 10px; border: 1px solid var(--border); font-size: 13px; text-align: center; }
        .tier-item b { display: block; color: var(--accent); font-size: 15px; }
        .retired-tag { color: var(--dim) !important; font-style: italic; }

        /* Leaderboard Styling */
        .player-row { 
            background: var(--card); border: 1px solid var(--border); border-radius: 15px; padding: 12px 20px; margin-bottom: 10px; 
            display: grid; grid-template-columns: 50px 50px 220px 80px 1fr; align-items: center; 
            cursor: pointer; transition: 0.2s; text-decoration: none; color: inherit;
        }
        .player-row:hover { border-color: var(--accent); transform: translateY(-2px); background: #1c1f2b; }
        .avatar { width: 40px; height: 40px; border-radius: 8px; }
        .na { color: #e74c3c; border: 1px solid #e74c3c; padding: 2px 5px; border-radius: 4px; font-size: 10px; font-weight: 800;}
        .eu { color: #2ecc71; border: 1px solid #2ecc71; padding: 2px 5px; border-radius: 4px; font-size: 10px; font-weight: 800;}
        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; font-weight: 600; }
        
        .admin-panel { background: #1c1f2b; border: 1px solid #ff4b2b; padding: 20px; border-radius: 18px; position: sticky; top: 100px; }
        input, select { width: 100%; background: #0b0c10; color: white; border: 1px solid #333; padding: 10px; border-radius: 8px; margin-bottom: 10px; box-sizing: border-box;}
        .btn { background: red; color: white; border: none; padding: 10px; width: 100%; border-radius: 8px; cursor: pointer; font-weight: 800;}
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">BIRD<span>TIERS</span></a>
        <form action="/" method="GET"><input type="text" name="search" class="search-input" placeholder="Search player..." value="{{ search_query }}"></form>
    </div>
    <div class="wrapper">
        <div class="main">
            {% if spotlight %}
            <div class="profile-card">
                <div style="text-align: center;">
                    <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="big-head">
                    <a href="https://namemc.com/profile/{{spotlight.username}}" target="_blank" class="namemc-btn">NameMC</a>
                </div>
                <div style="flex-grow: 1;">
                    <h1 style="margin:0; font-size: 32px;">{{ spotlight.username }}</h1>
                    <p style="color:var(--dim); margin: 5px 0 15px 0;">Global Region: <span class="{{spotlight.region.lower()}}">{{spotlight.region}}</span></p>
                    <div class="tier-grid">
                        {% for m, t in spotlight.ranks.items() %}
                        <div class="tier-item">
                            {{m}}
                            <b class="{% if t=='RETIRED' %}retired-tag{% endif %}">{{t}}</b>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
            {% endif %}

            <h2>🏆 RANKINGS</h2>
            {% for p in players if p.is_active %}
            <a href="/?search={{p.username}}" class="player-row">
                <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
                <img src="https://minotar.net/helm/{{p.username}}/40.png" class="avatar">
                <div><b>{{ p.username }}</b><br><small style="color:var(--dim)">{{ p.total_points }} Points</small></div>
                <div><span class="{{ p.region.lower() }}">{{ p.region }}</span></div>
                <div class="tier-badge">
                    {% if loop.index <= 3 %}<span style="color:#ffb800">ELITE</span>
                    {% elif loop.index <= 10 %}<span style="color:#fff">PRO</span>
                    {% else %}<span style="color:var(--dim)">BEGINNER</span>{% endif %}
                </div>
            </a>
            {% endfor %}
        </div>

        {% if session.get('logged_in') %}
        <div class="side"><div class="admin-panel">
            <small style="color:#ff4b2b; font-weight:800;">ADMIN PANEL</small>
            <form action="/update" method="POST">
                <input type="text" name="username" placeholder="Player Name" required>
                <select name="region"><option>NA</option><option>EU</option></select>
                <select name="gamemode">{% for m in modes %}<option>{{m}}</option>{% endfor %}</select>
                <select name="tier">{% for t in tier_list %}<option>{{t}}</option>{% endfor %}</select>
                <button type="submit" class="btn">UPDATE</button>
            </form>
            <a href="/logout" style="display:block; text-align:center; margin-top:10px; color:var(--dim); font-size:11px;">Logout</a>
        </div></div>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    search_q = request.args.get('search', '').strip().lower()
    players_data = get_all_players()
    stats = {}
    
    for p in players_data:
        u = p['username']
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA'), "is_active": False}
        if p.get('tier') != "RETIRED": stats[u]["is_active"] = True
        stats[u]["pts"] += TIER_DATA.get(p.get('tier'), 0)
    
    spotlight = None
    if search_q:
        user_ranks = [p for p in players_data if p['username'].lower() == search_q]
        if user_ranks:
            spotlight = {
                "username": user_ranks[0]['username'], 
                "region": user_ranks[0].get('region', 'NA'),
                "ranks": {p['gamemode']: p['tier'] for p in user_ranks}
            }

    processed = sorted([
        {"username": u, "total_points": d['pts'], "region": d['region'], "is_active": d['is_active']} 
        for u, d in stats.items()
    ], key=lambda x: x['total_points'], reverse=True)
    
    return render_template_string(HTML_TEMPLATE, players=processed, modes=MODES, tier_list=TIER_LIST, spotlight=spotlight, search_query=search_q)

@app.route('/login')
def login():
    session['logged_in'] = True
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/update', methods=['POST'])
def web_update():
    if not session.get('logged_in'): return redirect('/')
    update_player_rank(request.form['username'], request.form['gamemode'], request.form['tier'], request.form['region'])
    return redirect(url_for('index', search=request.form['username']))

if __name__ == '__main__':
    if TOKEN: threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
