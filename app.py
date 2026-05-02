
import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
HIGH_RESULTS_ID = os.getenv("HIGH_RESULTS_ID")

MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

REGION_COLORS = {
    "NA": "#ff4d4d", "EU": "#4d94ff", "AS": "#ffdb4d", 
    "SA": "#4dff88", "OC": "#ff4dff", "AF": "#ffa64d"
}
RANK_COLORS = {
    "Grandmaster": "#ff0000", "Legend": "#ff8c00", 
    "Master": "#9370db", "Elite": "#00ced1", 
    "Bronze": "#cd7f32", "Stone": "#a9a9a9"
}

# --- DATABASE ---
class DummyCollection:
    def find(self, *args, **kwargs):
        return []
    def find_one(self, *args, **kwargs):
        return None
    def update_one(self, *args, **kwargs):
        return None

class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri) if uri else None
        self.db = self.client['magmatiers_db'] if self.client is not None else None
        collection = self.db is not None
        self.players = self.db['players'] if collection else DummyCollection()
        self.settings = self.db['settings'] if collection else DummyCollection()
        self.reports = self.db['reports'] if collection else DummyCollection()

db_mgr = DatabaseManager(MONGO_URI)

# --- CORE LOGIC ---
def get_tier_value(tier_name):
    try: return TIER_ORDER.index(tier_name.upper().strip()) + 1
    except: return 0

def get_rank_info(tier_list):
    if not tier_list: return "Stone", RANK_COLORS["Stone"]
    score = sum(get_tier_value(t) for t in tier_list)
    highest = max([get_tier_value(t) for t in tier_list]) if tier_list else 0
    if highest >= 9 and len(tier_list) >= 3: name = "Grandmaster"
    elif score >= 35: name = "Legend"
    elif score >= 25: name = "Master"
    elif score >= 15: name = "Elite"
    else: name = "Bronze"
    return name, RANK_COLORS.get(name, "#ffffff")

def is_maintenance_active():
    if db_mgr.settings is None: return {"active": False}
    status = db_mgr.settings.find_one({"_id": "maintenance_mode"})
    return status if status is not None else {"active": False}

# --- SKIN HELPERS ---
DEFAULT_HEAD_URL = "https://minotar.net/helm/{}/{}"


def get_player_head_url(username, size=32):
    username = (username or "").strip()
    return DEFAULT_HEAD_URL.format(username or "Steve", size)

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank")
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str):
    if not interaction.user.guild_permissions.manage_roles: return
    t_up = tier.upper().strip()
    db_mgr.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {"tier": t_up, "region": region.upper(), "discord_id": discord_user.id, "retired": False, "banned": False, "ts": datetime.datetime.utcnow()}},
        upsert=True
    )
    chan = HIGH_RESULTS_ID if get_tier_value(t_up) >= 5 else LOG_CHANNEL_ID
    if chan:
        c = bot.get_channel(int(chan))
        if c: await c.send(f"**{player}** updated to **{t_up}** ({mode})")
    await interaction.response.send_message(f"Updated {player}", ephemeral=True)

@bot.tree.command(name="maintenance")
async def maintenance(interaction: discord.Interaction, action: str, reason: str = None):
    if not interaction.user.guild_permissions.manage_roles: return
    if action.lower() == "on":
        db_mgr.settings.update_one(
            {"_id": "maintenance_mode"},
            {"$set": {"active": True, "reason": reason or "Maintenance in progress"}},
            upsert=True
        )
        await interaction.response.send_message("Maintenance mode enabled", ephemeral=True)
    elif action.lower() == "off":
        db_mgr.settings.update_one(
            {"_id": "maintenance_mode"},
            {"$set": {"active": False}},
            upsert=True
        )
        await interaction.response.send_message("Maintenance mode disabled", ephemeral=True)
    else:
        await interaction.response.send_message("Use 'on' or 'off' for action", ephemeral=True)

@bot.tree.command(name="retire")
async def retire(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles: return
    result = db_mgr.players.update_many(
        {"username": player},
        {"$set": {"retired": True, "ts": datetime.datetime.utcnow()}}
    )
    if result.modified_count > 0:
        await interaction.response.send_message(f"Retired {player}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Player {player} not found", ephemeral=True)

@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles: return
    result = db_mgr.players.update_many(
        {"username": player},
        {"$set": {"banned": True, "ts": datetime.datetime.utcnow()}}
    )
    if result.modified_count > 0:
        await interaction.response.send_message(f"Banned {player}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Player {player} not found", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
    :root { --bg: #0b0c10; --card: #14171f; --accent: #ff4500; --text: #f0f2f5; --border: #262932; }
    body { background: var(--bg) url('https://www.google.com/imgres?q=minecraft%20magma%20wallpaper&imgurl=http%3A%2F%2Fthe-minecraft.fr%2Fupload%2Fdefault%2FMinecraft-17.png&imgrefurl=https%3A%2F%2Fthe-minecraft.fr%2Fminecraft%2Fwallpaper%2Fmagma-cube&docid=0EMqd3-zkvIWdM&tbnid=enXoW6g-XR5mDM&vet=12ahUKEwjL2rPympuUAxVlhv0HHYlDAEAQnPAOegQIfRAB..i&w=1920&h=1080&hcb=2&ved=2ahUKEwjL2rPympuUAxVlhv0HHYlDAEAQnPAOegQIfRAB') no-repeat center center fixed; background-size: cover; color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
    .header { background: #0f1117; padding: 1rem 2rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }
    .nav-links { display: flex; gap: 15px; align-items: center; }
    .nav-links a { color: #9ba3af; text-decoration: none; font-weight: 600; font-size: 0.9rem; transition: 0.2s; }
    .nav-links a:hover, .nav-links a.active { color: var(--accent); }
    .container { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 50px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    .player-row:hover { border-color: var(--accent); transform: scale(1.01); }
    .badge { padding: 2px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase; border: 1px solid currentColor; }
    .reg-tag { font-weight: 800; font-size: 0.85rem; }
    .high-results { background: rgba(255, 69, 0, 0.05); border-left: 5px solid var(--accent); padding: 20px; border-radius: 0 15px 15px 0; margin-bottom: 30px; }
    input { background: var(--card); border: 1px solid var(--border); color: white; padding: 8px 15px; border-radius: 8px; outline: none; }
    
    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(10px); }
    .profile-card { background: #11141c; width: 420px; border-radius: 24px; border: 1px solid var(--border); overflow: hidden; }
    .profile-header { background: linear-gradient(180deg, #1a1e29 0%, #11141c 100%); padding: 35px 20px; text-align: center; }
    .profile-body { padding: 25px; background: #14171f; }
    .kit-item { background: #1a1e29; padding: 10px; border-radius: 10px; display: flex; justify-content: space-between; margin-bottom: 6px; border: 1px solid var(--border); }
</style>
"""

@app.route('/')
def home():
    maint = is_maintenance_active()
    if maint.get('active'): 
        return f"<html><head>{STYLE}</head><body style='display:flex; justify-content:center; align-items:center; height:100vh;'><div class='container' style='text-align:center;'><h1>🛠️ {maint.get('reason')}</h1></div></body></html>"

    mode_q = request.args.get('mode', '').capitalize()
    search_q = request.args.get('search', '').lower()
    
    raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    users = {}

    for r in raw:
        u = r['username']
        if u not in users:
            reg = r.get('region', 'NA').upper()
            users[u] = {
                "u": u,
                "tiers": [],
                "kits": [],
                "reg": reg,
                "reg_c": REGION_COLORS.get(reg, "#fff"),
                "mode_tier": "N/A",
                "head_url": get_player_head_url(u, 32)
            }
        
        users[u]["kits"].append(r)
        if r['gamemode'].capitalize() == mode_q:
            users[u]["mode_tier"] = r['tier']
            
        if not r.get('retired'):
            users[u]["tiers"].append(r['tier'])

    processed = []
    spotlight = None
    for u, data in users.items():
        data["rank"], data["rank_c"] = get_rank_info(data["tiers"])
        data["score"] = sum(get_tier_value(t) for t in data["tiers"])
        data["best"] = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        
        # Filter logic
        if mode_q and data["mode_tier"] == "N/A": continue
        processed.append(data)
        if search_q and u.lower() == search_q:
            spotlight = dict(data)
            spotlight["head_url"] = get_player_head_url(u, 80)

    players = sorted(processed, key=lambda x: x['score'], reverse=True)
    high_p = [p for p in players if p['rank'] in ["Grandmaster", "Legend", "Master"]]

    template = """
    <html><head><meta http-equiv="refresh" content="15"><title>MagmaTIERS</title>{{ s|safe }}</head>
    <body>
        <div class="header">
            <a href="/" style="color:white; text-decoration:none; font-weight:800; font-size:1.6rem;">Magma<span style="color:var(--accent);">TIERS</span></a>
            <div class="nav-links">
                <a href="/" class="{% if not m %}active{% endif %}">Global</a>
                {% for gm in modes %}<a href="/?mode={{gm}}" class="{% if m == gm %}active{% endif %}">{{gm}}</a>{% endfor %}
            </div>
            <div style="display:flex; gap:10px; align-items:center;">
                <form action="/" style="margin:0;"><input name="search" placeholder="Search..."></form>
            
            </div>
        </div>

        {% if spot %}
        <div class="modal-bg" onclick="window.location.href='/?mode={{m}}'">
            <div class="profile-card" onclick="event.stopPropagation()">
                <div class="profile-header">
                    <img src="{{ spot.head_url }}" style="border-radius:15px; border:3px solid var(--accent); margin-bottom:15px;">
                    <h2 style="margin:0;">{{ spot.u }}</h2>
                    <span class="badge" style="color:{{ spot.rank_c }}; border-color:{{ spot.rank_c }}; margin-top:10px; display:inline-block;">{{ spot.rank }}</span>
                </div>
                <div class="profile-body">
                    <div style="display:flex; justify-content:space-between; margin-bottom:15px;">
                        <span style="color:{{ spot.reg_c }}; font-weight:800;">{{ spot.reg }} Region</span>
                        <span style="color:var(--accent); font-weight:800;">{{ spot.score }} Pts</span>
                    </div>
                    {% for k in spot.kits %}
                    <div class="kit-item">
                        <span style="color:#9ba3af;">{{ k.gamemode }}</span>
                        <b style="color:var(--accent)">{{ k.tier }}</b>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endif %}

        <div class="container">
            {% if not m and not search and high_p %}
            <div class="high-results">
                <div style="font-weight:800; color:var(--accent); margin-bottom:10px; font-size:0.8rem;">FEATURED ELITES</div>
                {% for h in high_p[:3] %}
                <a href="/?search={{h.u}}" class="player-row" style="border-color: gold;">
                    <div style="color:gold; font-weight:800;">TOP</div>
                    <img src="{{ h.head_url }}">
                    <div>{{h.u}} <span class="badge" style="color:{{ h.rank_c }}">{{ h.rank }}</span></div>
                    <div style="color:{{h.reg_c}}">{{h.reg}}</div>
                    <div style="text-align:right; color:var(--accent); font-weight:800;">{{h.best}}</div>
                </a>
                {% endfor %}
            </div>
            {% endif %}

            {% for p in players %}
            {% set placement_color = 'gold' if loop.index == 1 else 'silver' if loop.index == 2 else '#cd7f32' if loop.index == 3 else '#9ba3af' %}
            <a href="/?search={{ p.u }}&mode={{m}}" class="player-row">
                <div style="font-weight:800; color:{{ placement_color }};">#{{ loop.index }}</div>
                <img src="{{ p.head_url }}">
                <div>{{ p.u }} <span class="badge" style="color:{{ p.rank_c }}; margin-left:10px;">{{ p.rank }}</span></div>
                <div class="reg-tag" style="color:{{ p.reg_c }}">{{ p.reg }}</div>
                <div style="text-align:right; color:var(--accent); font-weight:800;">{{ p.mode_tier if m else p.best }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(template, s=STYLE, players=players, spot=spotlight, modes=MODES, m=mode_q, search=search_q, high_p=high_p)

@app.route('/moderation')
def moderation():
    reps = list(db_mgr.reports.find({"status": "Pending"}))
    return render_template_string("""
        <html><head>{{ s|safe }}</head><body><div class="container">
        <h1>Reports Queue</h1>
        {% for r in reps %}
        <div style="background:var(--card); padding:20px; border-radius:12px; margin-bottom:10px; border:1px solid var(--border);">
            <h3>{{ r.player }}</h3><p>{{ r.reason }}</p>
            <form action="/moderation/resolve" method="POST">
                <input type="hidden" name="id" value="{{ r._id }}">
                <button name="a" value="approve" style="background:green; color:white; border:none; padding:10px; border-radius:5px;">Approve</button>
                <button name="a" value="decline" style="background:#444; color:white; border:none; padding:10px; border-radius:5px;">Decline</button>
            </form>
        </div>
        {% endfor %}
        <a href="/" style="color:var(--accent); text-decoration:none;">← Back Home</a>
        </div></body></html>
    """, s=STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_mgr.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect(url_for('moderation'))

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.run(TOKEN)
