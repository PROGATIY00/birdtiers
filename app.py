from flask import Flask, render_template_string, request, redirect, session, url_for
import json
import os

app = Flask(__name__)
app.secret_key = "birdtiers_final_sync_2026"

DB_FILE = 'database.json'

# --- CONFIG ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_LIST = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5"]
TIER_DATA = {
    "HT1": 100, "LT1": 90, "HT2": 80, "LT2": 70, "HT3": 60, 
    "LT3": 50, "HT4": 40, "LT4": 30, "HT5": 20, "LT5": 10
}

def load_db():
    if not os.path.exists(DB_FILE): return {"players": []}
    try:
        with open(DB_FILE, 'r') as f: return json.load(f)
    except: return {"players": []}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- UI TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BirdTiers | Rankings</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { 
            --bg: #0b0c10; --card: #14171f; --border: #262932; 
            --accent: #5e6ad2; --text: #e0e6ed; --dim: #8b949e; 
        }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; padding: 0; }
        
        .navbar { background: #0f1117; padding: 15px 50px; display: flex; align-items: center; border-bottom: 1px solid var(--border); }
        .logo { color: white; font-weight: 600; font-size: 24px; text-decoration: none; margin-right: 40px; text-transform: uppercase; letter-spacing: 1px; }
        .logo span { color: var(--accent); }
        
        .wrapper { max-width: 1400px; margin: auto; display: grid; grid-template-columns: 3fr 1fr; gap: 30px; padding: 40px; }

        .search-bar { width:100%; background:var(--card); border:2px solid var(--border); padding:15px; border-radius:15px; color:white; margin-bottom:25px; outline:none; box-sizing: border-box; }
        
        .spotlight {
            background: linear-gradient(145deg, #1a1d29, #14171f);
            border: 2px solid var(--accent); border-radius: 20px;
            padding: 25px; margin-bottom: 30px; display: flex; align-items: center; gap: 25px;
        }
        .big-head { width: 80px; height: 80px; border-radius: 12px; border: 2px solid #222; }
        .tier-grid { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
        .mini-badge { background: #0b0c10; border: 1px solid var(--border); padding: 4px 10px; border-radius: 8px; font-size: 11px; }
        .mini-badge b { color: var(--accent); }

        .nav-tabs { display: flex; gap: 8px; margin-bottom: 25px; flex-wrap: wrap; }
        .tab { background: var(--card); padding: 8px 18px; border-radius: 12px; text-decoration: none; color: var(--dim); font-weight: 600; border: 1px solid var(--border); font-size: 13px; }
        .tab.active { background: var(--accent); color: white; border-color: var(--accent); }

        .player-row {
            background: var(--card); border: 1px solid var(--border); border-radius: 15px;
            padding: 12px 20px; margin-bottom: 10px; display: grid;
            grid-template-columns: 50px 50px 220px 80px 1fr 40px; align-items: center;
        }
        .pos-num { font-weight: 800; font-size: 18px; color: #333; font-style: italic; }
        .pos-top { color: var(--accent); }
        .avatar { width: 40px; height: 40px; border-radius: 8px; }

        .region { font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; text-align: center; width: 30px; }
        .na { color: #e74c3c; border: 1px solid #e74c3c; }
        .eu { color: #2ecc71; border: 1px solid #2ecc71; }

        .tier-badge { background: #1c1f26; padding: 6px 12px; border-radius: 8px; border: 1px solid #2d313d; text-align: center; }

        .sidebar-box { background: #1c1f2b; border: 1px solid #ff4b2b; padding: 20px; border-radius: 18px; position: sticky; top: 20px; }
        .sidebar-title { color: #ff4b2b; font-weight: 800; font-size: 11px; text-transform: uppercase; margin-bottom: 15px; display: block; }
        input, select { width: 100%; background: #0b0c10; color: white; border: 1px solid #333; padding: 10px; border-radius: 8px; margin-bottom: 10px; font-family: 'Fredoka'; box-sizing: border-box;}
        .btn-update { background: linear-gradient(to right, #ff416c, #ff4b2b); color: white; border: none; padding: 12px; border-radius: 8px; width: 100%; font-weight: 800; cursor: pointer; text-transform: uppercase; }
        .remove-btn { background: none; border: none; color: #ff4d4d; font-weight: bold; cursor: pointer; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">BIRD<span>TIERS</span></a>
        {% if session.get('logged_in') %}<a href="/logout" style="margin-left:auto; color:var(--dim); font-size:12px; text-decoration:none;">Logout Admin</a>{% endif %}
    </div>

    <div class="wrapper">
        <div class="main">
            <form action="/" method="GET">
                <input type="text" name="search" class="search-bar" placeholder="🔍 Search player profile..." value="{{ search_query }}">
            </form>

            {% if spotlight %}
            <div class="spotlight">
                {% if spotlight.username.lower() == 'g4lactic4l' %}
                    <img src="/static/friend_skin.png" class="big-head">
                {% else %}
                    <img src="https://minotar.net/helm/{{ spotlight.username }}/80.png" class="big-head">
                {% endif %}
                <div style="flex-grow:1">
                    <h1 style="margin:0;">{{ spotlight.username }}</h1>
                    <div class="tier-grid">
                        {% for m, t in spotlight.ranks.items() %}
                        <div class="mini-badge"><span>{{ m }}</span>: <b>{{ t }}</b></div>
                        {% endfor %}
                    </div>
                </div>
            </div>
            {% endif %}

            <div class="nav-tabs">
                <a href="/" class="tab {% if not active_mode %}active{% endif %}">OVERALL</a>
                {% for mode in modes %}<a href="/?mode={{mode}}" class="tab {% if active_mode == mode %}active{% endif %}">{{mode}}</a>{% endfor %}
            </div>

            {% for p in players %}
            <div class="player-row">
                <div class="pos-num {% if loop.index <= 3 %}pos-top{% endif %}">#{{ loop.index }}</div>
                
                {% if p.username.lower() == 'g4lactic4l' %}
                    <img src="/static/friend_skin.png" class="avatar">
                {% else %}
                    <img src="https://minotar.net/helm/{{ p.username }}/40.png" class="avatar">
                {% endif %}

                <div class="p-info">
                    <div class="p-name">{{ p.username }}</div>
                    <div class="p-points">{{ p.total_points }} Pts</div>
                </div>
                <div><span class="region {{ p.region.lower() }}">{{ p.region }}</span></div>
                <div class="tier-badge">
                    {% if not active_mode %}
                        {% if loop.index <= 5 %}<b style="color:#ffb800">ELITE</b>
                        {% elif loop.index <= 10 %}<b style="color:#fff">PRO</b>
                        {% else %}<b style="color:#444">BEGINNER</b>{% endif %}
                    {% else %}
                        <b style="color:var(--accent)">{{ p.display_tier }}</b>
                    {% endif %}
                </div>
                {% if session.get('logged_in') %}
                <form action="/remove" method="POST">
                    <input type="hidden" name="username" value="{{ p.username }}">
                    <input type="hidden" name="mode" value="{{ active_mode or 'ALL' }}">
                    <button type="submit" class="remove-btn">×</button>
                </form>
                {% endif %}
            </div>
            {% endfor %}
        </div>

        <div class="side">
            {% if session.get('logged_in') %}
            <div class="sidebar-box">
                <span class="sidebar-title">Admin Panel - Tier Override</span>
                <form action="/update" method="POST">
                    <input type="text" name="username" placeholder="Player name" required>
                    <select name="region"><option>NA</option><option>EU</option></select>
                    <select name="gamemode">{% for m in modes %}<option>{{m}}</option>{% endfor %}</select>
                    <select name="tier">{% for t in tier_list %}<option>{{t}}</option>{% endfor %}</select>
                    <button type="submit" class="btn-update">Update Tier & Override</button>
                </form>
            </div>
            {% else %}
            <div style="background:var(--card); border:1px solid var(--border); padding:20px; border-radius:18px; color:var(--dim); font-size:12px; text-align:center;">
                Staff login required for dashboard management.
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    mode = request.args.get('mode')
    search_q = request.args.get('search', '').strip().lower()
    db = load_db()
    players_data = db.get('players', [])
    
    stats = {}
    for p in players_data:
        u = p['username']
        if u not in stats: stats[u] = {"pts": 0, "region": p.get('region', 'NA')}
        stats[u]["pts"] += TIER_DATA.get(p['tier'], 0)
    
    global_sorted = sorted([{"u": u, "s": d['pts'], "r": d['region']} for u, d in stats.items()], key=lambda x: x['s'], reverse=True)
    
    spotlight = None
    if search_q:
        user_ranks = [p for p in players_data if p['username'].lower() == search_q]
        if user_ranks:
            spotlight = {"username": user_ranks[0]['username'], "ranks": {p['gamemode']: p['tier'] for p in user_ranks}}

    if mode:
        display = [p for p in players_data if p['gamemode'] == mode]
        processed = [{"username": p['username'], "display_tier": p['tier'], "total_points": TIER_DATA.get(p['tier'], 0), "region": p.get('region', 'NA')} for p in display]
    else:
        processed = [{"username": item['u'], "total_points": item['s'], "region": item['r']} for item in global_sorted]

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

@app.route('/remove', methods=['POST'])
def remove():
    if not session.get('logged_in'): return redirect('/')
    name, mode = request.form['username'], request.form['mode']
    db = load_db()
    if mode == "ALL":
        db['players'] = [p for p in db.get('players', []) if p['username'].lower() != name.lower()]
    else:
        db['players'] = [p for p in db.get('players', []) if not (p['username'].lower() == name.lower() and p['gamemode'] == mode)]
    save_db(db)
    return redirect('/')

@app.route('/login')
def login():
    session['logged_in'] = True
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)