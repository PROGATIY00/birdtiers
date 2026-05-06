import discord
from discord import app_commands
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID")) if os.getenv("LOG_CHANNEL_ID") else None
HIGH_RESULTS_ID = int(os.getenv("HIGH_RESULTS_ID")) if os.getenv("HIGH_RESULTS_ID") else None

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

GAMEMODE_ICON_URLS = {
    "Crystal": "https://imgur.com/g9GZWN4.png",
    "UHC": "https://imgur.com/Bhr49wo.png",
    "Pot": "https://imgur.com/HSR3a7Z.png",
    "SMP": "https://imgur.com/tu6NG54.png",
    "Axe": "https://imgur.com/BLl7vXs.png",
    "Sword": "https://imgur.com/Wf9dcUa.png",
    "Mace": "https://imgur.com/W4qul51.png",
    "Cart": "https://img.icons8.com/ios-filled/64/ffffff/minecart.png",
    "1.8": "https://img.icons8.com/ios-filled/64/ffffff/shield.png",
    "Trident": "https://img.icons8.com/ios-filled/64/ffffff/trident.png",
    "Spear": "https://img.icons8.com/ios-filled/64/ffffff/spear.png"
}
DEFAULT_GAMEMODE_ICON_URL = "https://img.icons8.com/ios-filled/64/ffffff/question-mark.png"

# --- DATABASE ---
class DummyCollection:
    def find(self, *args, **kwargs): return []
    def find_one(self, *args, **kwargs): return None
    def update_one(self, *args, **kwargs): return None
    def update_many(self, *args, **kwargs): return type('obj', (object,), {'modified_count': 0})

class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri) if uri else None
        self.db = self.client['magmatiers_db'] if self.client else None
        if self.db is not None:
            self.players = self.db['players']
            self.settings = self.db['settings']
            self.reports = self.db['reports']
        else:
            self.players = DummyCollection()
            self.settings = DummyCollection()
            self.reports = DummyCollection()

db_mgr = DatabaseManager(MONGO_URI)

# --- CORE LOGIC ---
def normalize_tier(tier_name):
    if not tier_name: return ""
    return str(tier_name).upper().strip()

def normalize_mode(mode_name):
    if not mode_name: return ""
    mode_name = str(mode_name).strip()
    for mode in MODES:
        if mode.lower() == mode_name.lower():
            return mode
    return mode_name

def get_tier_value(tier_name):
    try:
        return TIER_ORDER.index(normalize_tier(tier_name)) + 1
    except ValueError:
        return 0

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
    status = db_mgr.settings.find_one({"_id": "maintenance_mode"})
    return status if status is not None else {"active": False}

# --- SKIN HELPERS ---
DEFAULT_HEAD_URL = "https://minotar.net/helm/{}/{}"

def get_player_head_url(username, size=32):
    username = (username or "Steve").strip()
    return DEFAULT_HEAD_URL.format(username, size)

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank")
async def rank(interaction: discord.Interaction, player: str, discord_user: discord.Member, mode: str, tier: str, region: str, reason: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("No permission", ephemeral=True)

    t_up = tier.upper().strip()
    existing = db_mgr.players.find_one({"username": player, "gamemode": mode})
    old_tier = existing.get("tier") if existing else None
    old_value = get_tier_value(old_tier) if old_tier else 0
    new_value = get_tier_value(t_up)

    status = "promoted" if new_value > old_value else "demoted" if new_value < old_value else "updated"

    # peak_tier only ever goes up — never replaced with a lower tier
    existing_peak = existing.get("peak_tier") if existing else None
    new_peak = t_up if (existing_peak is None or new_value > get_tier_value(existing_peak)) else existing_peak

    db_mgr.players.update_one(
        {"username": player, "gamemode": mode},
        {"$set": {
            "tier": t_up,
            "peak_tier": new_peak,
            "region": region.upper(),
            "discord_id": discord_user.id,
            "retired": False,
            "banned": False,
            "ts": datetime.datetime.utcnow()
        }},
        upsert=True
    )

    log_channel = bot.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
    if log_channel:
        await log_channel.send(
            f"{discord_user.mention}\n**{player}** was {status} to **{t_up}** in {mode}\n**Reason:** {reason or 'No reason provided'}"
        )
    await interaction.response.send_message("Updated!", ephemeral=True)

@bot.tree.command(name="maintenance")
async def maintenance(interaction: discord.Interaction, action: str, reason: str = None):
    if not interaction.user.guild_permissions.manage_roles: return
    action_lower = action.lower()
    if action_lower == "on":
        db_mgr.settings.update_one(
            {"_id": "maintenance_mode"},
            {"$set": {"active": True, "reason": reason or "Maintenance in progress"}},
            upsert=True
        )
        await interaction.response.send_message("Maintenance mode enabled", ephemeral=True)
    elif action_lower == "off":
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
    msg = f"Retired {player}" if result.modified_count > 0 else f"Player {player} not found"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, player: str):
    if not interaction.user.guild_permissions.manage_roles: return
    result = db_mgr.players.update_many(
        {"username": player},
        {"$set": {"banned": True, "ts": datetime.datetime.utcnow()}}
    )
    msg = f"Banned {player}" if result.modified_count > 0 else f"Player {player} not found"
    await interaction.response.send_message(msg, ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
    :root { --bg: #0b0c10; --card: #14171f; --accent: #ff4500; --text: #f0f2f5; --border: #262932; }
    body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
    .header { background: #0f1117; padding: 1rem 2rem; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }
    .nav-links { display: flex; gap: 15px; align-items: center; }
    .nav-links a { color: #9ba3af; text-decoration: none; font-weight: 600; font-size: 0.9rem; transition: 0.2s; }
    .nav-links a:hover, .nav-links a.active { color: var(--accent); }
    .container { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
    .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 0.8rem; display: grid; grid-template-columns: 50px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; transition: 0.2s; }
    .player-row:hover { border-color: var(--accent); transform: scale(1.01); }
    .player-row.top-player { border-color: gold; box-shadow: 0 0 20px rgba(255, 215, 0, 0.18); background: linear-gradient(135deg, rgba(255,215,0,0.08), rgba(17,23,34,0.96)); }
    .badge { padding: 2px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase; border: 1px solid currentColor; }
    .top-badge { margin-left: 0.75rem; color: #ffd700; font-size: 0.75rem; font-weight: 800; background: rgba(255,215,0,0.12); padding: 3px 8px; border-radius: 999px; }
    .reg-tag { font-weight: 800; font-size: 0.85rem; }
    .high-results { background: rgba(255, 69, 0, 0.05); border-left: 5px solid var(--accent); padding: 20px; border-radius: 0 15px 15px 0; margin-bottom: 30px; }
    input { background: var(--card); border: 1px solid var(--border); color: white; padding: 8px 15px; border-radius: 8px; outline: none; }

    .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); display:flex; justify-content:center; align-items:center; z-index:2000; backdrop-filter: blur(10px); }
    .profile-card { background: #11141c; width: 460px; border-radius: 24px; border: 1px solid var(--border); overflow: hidden; }
    .profile-header { background: linear-gradient(180deg, #1a1e29 0%, #11141c 100%); padding: 35px 20px 25px; text-align: center; }
    .profile-avatar-wrapper { width: 120px; height: 120px; border-radius: 50%; border: 4px solid #f5c06d; display: inline-flex; justify-content: center; align-items: center; margin: 0 auto 15px; background: radial-gradient(circle at top, rgba(255,255,255,0.12), transparent 55%); }
    .profile-avatar { width: 104px; height: 104px; border-radius: 50%; border: 3px solid rgba(255,255,255,0.12); object-fit: cover; }
    .profile-name { margin: 0; font-size: 2rem; font-weight: 800; color: #ffffff; }
    .profile-rank { display: inline-flex; align-items: center; gap: 8px; margin-top: 10px; padding: 8px 16px; border-radius: 999px; background: rgba(255, 192, 100, 0.12); color: #f5c06d; border: 1px solid rgba(245,192,100,0.25); font-weight: 800; font-size: 0.9rem; }
    .profile-region { color: #8f9bb3; margin-top: 8px; font-size: 0.95rem; }
    .name-mc-button { display: inline-flex; align-items: center; gap: 8px; margin: 14px auto 0; padding: 10px 16px; border-radius: 999px; background: #0f1117; color: #d8dde7; text-decoration: none; border: 1px solid rgba(255,255,255,0.08); font-size: 0.9rem; }
    .profile-body { padding: 25px; background: #14171f; }
    .profile-section { margin-bottom: 18px; }
    .profile-section h3 { margin: 0 0 12px; font-size: 0.8rem; letter-spacing: 0.15em; color: #9ba3af; }
    .position-box { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 18px; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 12px; }
    .position-number { font-size: 1.4rem; font-weight: 800; color: #f5c06d; }
    .tier-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 12px; }

    /* Tier card */
    .tier-card { background: #0f1117; border: 1px solid var(--border); border-radius: 16px; padding: 14px 10px; text-align: center; transition: 0.2s; position: relative; cursor: default; }
    .tier-card:hover { border-color: var(--accent); transform: translateY(-2px); }
    .tier-card.retired { opacity: 0.45; filter: grayscale(100%); }
    .tier-card.top-mode { border-color: #ffd700; box-shadow: 0 0 10px rgba(255,215,0,0.2); }
    .discord {
    background: #7289da;
    color: white;
    border: none;
    
    padding: 8px 15px;
    border-radius: 20px;
    font-weight: 600;
    cursor: pointer;
    }
    /* Peak tooltip — appears above card on hover */
    .tier-card .peak-tooltip {
        display: none;
        position: absolute;
        bottom: calc(100% + 8px);
        left: 50%;
        transform: translateX(-50%);
        background: #1e2230;
        border: 1px solid var(--accent);
        color: #f0f2f5;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        padding: 5px 10px;
        border-radius: 8px;
        white-space: nowrap;
        z-index: 10;
        pointer-events: none;
    }
    .tier-card .peak-tooltip::after {
        content: '';
        position: absolute;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        border: 5px solid transparent;
        border-top-color: var(--accent);
    }
    .tier-card:hover .peak-tooltip { display: block; }

    .tier-icon-img { width: 38px; height: 38px; margin: 0 auto 8px; border-radius: 12px; display: block; object-fit: contain; }
    .tier-label { color: #d8dde7; font-size: 0.85rem; font-weight: 800; }
    .tier-subtext { color: #9ba3af; font-size: 0.75rem; margin-top: 6px; }
</style>
"""

@app.route('/')
def home():
    maint = is_maintenance_active()
    if maint.get('active'):
        return f"<html><head>{STYLE}</head><body style='display:flex;justify-content:center;align-items:center;height:100vh;'><div class='container' style='text-align:center;'><h1>🛠️ {maint.get('reason')}</h1></div></body></html>"

    mode_q = normalize_mode(request.args.get('mode', ''))
    search_q = request.args.get('search', '').lower()

    raw = list(db_mgr.players.find({"banned": {"$ne": True}}))
    users = {}

    for r in raw:
        u = r['username']
        n_mode = normalize_mode(r.get('gamemode'))
        n_tier = normalize_tier(r.get('tier'))
        r['_normalized_gamemode'] = n_mode
        r['_normalized_tier'] = n_tier

        if u not in users:
            reg = r.get('region', 'NA').strip().upper()
            users[u] = {
                "u": u, "tiers": [], "kits": [], "reg": reg,
                "reg_c": REGION_COLORS.get(reg, "#fff"),
                "mode_tier": "N/A", "head_url": get_player_head_url(u, 32)
            }

        users[u]["kits"].append(r)

        if n_mode == mode_q and not r.get('retired'):
            cur = users[u].get("mode_tier")
            if cur == "N/A" or get_tier_value(n_tier) > get_tier_value(cur):
                users[u]["mode_tier"] = n_tier

        if not r.get('retired'):
            users[u]["tiers"].append(n_tier)

    top_mode_tiers = {}
    for data in users.values():
        for kit in data["kits"]:
            if kit.get("retired"): continue
            m_name = kit.get("_normalized_gamemode")
            if not m_name: continue
            t_val = get_tier_value(kit.get("_normalized_tier"))
            existing = top_mode_tiers.get(m_name)
            if existing is None or t_val > existing["tier_value"]:
                top_mode_tiers[m_name] = {"tier_value": t_val, "tier": kit.get("_normalized_tier")}

    processed = []
    spotlight = None

    for u, data in users.items():
        data["rank"], data["rank_c"] = get_rank_info(data["tiers"])
        data["score"] = sum(get_tier_value(t) for t in data["tiers"])
        data["best"] = max(data["tiers"], key=get_tier_value) if data["tiers"] else "N/A"
        if mode_q and data["mode_tier"] == "N/A": continue
        processed.append(data)

    players = sorted(
        processed,
        key=lambda x: (get_tier_value(x['mode_tier']), x['score']) if mode_q else x['score'],
        reverse=True
    )
    high_p = [p for p in players if p['rank'] in ["Grandmaster", "Legend", "Master"]]

    if search_q:
        for idx, p in enumerate(players, 1):
            if p['u'].lower() == search_q:
                spotlight = dict(p)
                spotlight.update({
                    "head_url": get_player_head_url(p['u'], 80),
                    "position": idx,
                    "position_label": mode_q.upper() if mode_q else "OVERALL",
                    "region_name": {
                        "NA": "North America", "EU": "Europe", "AS": "Asia",
                        "SA": "South America", "OC": "Oceania", "AF": "Africa"
                    }.get(p['reg'], p['reg']),
                    "placement_color": 'gold' if idx == 1 else 'silver' if idx == 2 else '#cd7f32' if idx == 3 else '#9ba3af'
                })

                # One entry per mode. peak_tier is persisted by /rank and never goes down.
                # Falls back to current tier for players ranked before this field existed.
                peak_by_mode = {}
                for kit_item in p.get("kits", []):
                    km = kit_item.get("_normalized_gamemode", "")
                    kt = kit_item.get("_normalized_tier", "")
                    if not km or not kt:
                        continue
                    if kit_item.get("retired", False):
                        continue
                    stored_peak = normalize_tier(kit_item.get("peak_tier") or kt)
                    kv = get_tier_value(kt)
                    if km not in peak_by_mode or kv > peak_by_mode[km]["tier_value"]:
                        peak_by_mode[km] = {
                            "gamemode": km,
                            "tier": kt,
                            "tier_value": kv,
                            "peak_tier": stored_peak,
                        }

                spotlight["kits"] = []
                for kit in peak_by_mode.values():
                    is_top = top_mode_tiers.get(kit["gamemode"], {}).get("tier_value", 0) == kit["tier_value"]
                    kit["peak_label"] = f"PEAK {kit['peak_tier']}"
                    kit["top_mode"] = is_top
                    spotlight["kits"].append(kit)
                break

    template = """
    <html><head><meta http-equiv="refresh" content="30"><title>MagmaTIERS</title>{{ s|safe }}</head>
    <body>
        <div class="header">
            <a href="/" style="color:white;text-decoration:none;font-weight:800;font-size:1.6rem;">Magma<span style="color:var(--accent);">TIERS</span></a>
            <div class="nav-links">
                <a href="/" class="{% if not m %}active{% endif %}">Global</a>
                {% for gm in modes %}<a href="/?mode={{gm}}" class="{% if m == gm %}active{% endif %}">{{gm}}</a>{% endfor %}
            </div>
            <button class="discord" onclick='window.location.href="https://magmatiers.onrender.com/discord"'>DISCORD</button>
            <form action="/" style="margin:0;"><input name="search" placeholder="Search..."></form>
        </div>

        {% if spot %}
        <div class="modal-bg" onclick="window.location.href='/?mode={{m}}'">
            <div class="profile-card" onclick="event.stopPropagation()">
                <div class="profile-header">
                    <div class="profile-avatar-wrapper" style="border-color:{{ spot.placement_color }};">
                        <img src="{{ spot.head_url }}" class="profile-avatar">
                    </div>
                    <h2 class="profile-name">{{ spot.u }}</h2>
                    <div class="profile-rank">🏆 {{ spot.rank }}</div>
                    <div class="profile-region">{{ spot.region_name }}</div>
                    <a class="name-mc-button" href="https://namemc.com/profile/{{ spot.u }}" target="_blank">NameMC</a>
                </div>
                <div class="profile-body">
                    <div class="profile-section">
                        <h3>POSITION</h3>
                        <div class="position-box">
                            <div class="position-number" style="color:{{ spot.placement_color }};">#{{ spot.position }}</div>
                            <div style="font-weight:800;">{{ spot.position_label }} · {{ spot.best }}</div>
                            <div style="color:#9ba3af;">({{ spot.score }} pts)</div>
                        </div>
                    </div>
                    <div class="profile-section">
                        <h3>TIERS</h3>
                        <div class="tier-grid">
                            {% for k in spot.kits %}
                            <div class="tier-card{% if k.retired %} retired{% endif %}{% if k.top_mode %} top-mode{% endif %}">
                                <div class="peak-tooltip">{{ k.peak_label }}</div>
                                <img src="{{ mode_icon_urls.get(k.gamemode, default_icon_url) }}" class="tier-icon-img" onerror="this.onerror=null;this.src='{{ default_icon_url }}';">
                                <div class="tier-label">{{ k.gamemode }}</div>
                                <div class="tier-subtext">{{ k.tier }}</div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="container">
            {% if not m and not search and high_p %}
            <div class="high-results">
                <div style="font-weight:800;color:var(--accent);margin-bottom:10px;">FEATURED ELITES</div>
                {% for h in high_p[:3] %}
                <a href="/?search={{h.u}}" class="player-row" style="border-color:gold;">
                    <div style="color:gold;font-weight:800;">TOP</div>
                    <img src="{{ h.head_url }}">
                    <div>{{h.u}} <span class="badge" style="color:{{ h.rank_c }}">{{ h.rank }}</span></div>
                    <div style="color:{{h.reg_c}}">{{h.reg}}</div>
                    <div style="text-align:right;color:var(--accent);font-weight:800;">{{h.best}}</div>
                </a>
                {% endfor %}
            </div>
            {% endif %}

            {% for p in players %}
            {% set pc = 'gold' if loop.index == 1 else 'silver' if loop.index == 2 else '#cd7f32' if loop.index == 3 else '#9ba3af' %}
            <a href="/?search={{ p.u }}&mode={{m}}" class="player-row{% if m and loop.index == 1 %} top-player{% endif %}">
                <div style="font-weight:800;color:{{ pc }};">#{{ loop.index }}</div>
                <img src="{{ p.head_url }}">
                <div>{{ p.u }} <span class="badge" style="color:{{ p.rank_c }};margin-left:10px;">{{ p.rank }}</span></div>
                <div class="reg-tag" style="color:{{ p.reg_c }}">{{ p.reg }}</div>
                <div style="text-align:right;color:var(--accent);font-weight:800;">{{ p.mode_tier if m else p.best }}</div>
            </a>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(
        template, s=STYLE, players=players, spot=spotlight, modes=MODES,
        m=mode_q, search=search_q, high_p=high_p,
        mode_icon_urls=GAMEMODE_ICON_URLS, default_icon_url=DEFAULT_GAMEMODE_ICON_URL
    )

@app.route('/moderation')
def moderation():
    reps = list(db_mgr.reports.find({"status": "Pending"}))
    return render_template_string("""
        <html><head>{{ s|safe }}</head><body><div class="container">
        <h1>Reports Queue</h1>
        {% for r in reps %}
        <div style="background:var(--card);padding:20px;border-radius:12px;margin-bottom:10px;border:1px solid var(--border);">
            <h3>{{ r.player }}</h3><p>{{ r.reason }}</p>
            <form action="/moderation/resolve" method="POST">
                <input type="hidden" name="id" value="{{ r._id }}">
                <button name="a" value="approve" style="background:green;color:white;border:none;padding:10px;border-radius:5px;cursor:pointer;">Approve</button>
                <button name="a" value="decline" style="background:#444;color:white;border:none;padding:10px;border-radius:5px;cursor:pointer;">Decline</button>
            </form>
        </div>
        {% endfor %}
        <a href="/" style="color:var(--accent);text-decoration:none;">← Back Home</a>
        </div></body></html>
    """, s=STYLE, reps=reps)

@app.route('/moderation/resolve', methods=['POST'])
def resolve():
    status = "Resolved" if request.form.get('a') == "approve" else "Declined"
    db_mgr.reports.update_one({"_id": ObjectId(request.form.get('id'))}, {"$set": {"status": status}})
    return redirect(url_for('moderation'))
@app.route('/discord')
def discord_redirect():
    return redirect("https://dsc.gg/magmatiers")

@app.route('/status')
def status():
    maint = is_maintenance_active()
    return jsonify({
        "maintenance": maint.get('active', False),
        "reason": maint.get('reason', '') if maint.get('active') else ''
    })
@app.route('/api/player/<username>/<mode>')
def get_player_tier(username, mode):
    n_mode = normalize_mode(mode)
    player = db_mgr.players.find_one({"username": username, "gamemode": n_mode, "banned": {"$ne": True}})
    if not player:
        return jsonify({"error": "Player or mode not found"}), 404
    tier = player.get("tier", "N/A")
    return jsonify({"username": username, "mode": n_mode, "tier": tier})

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False), daemon=True).start()
    bot.run(TOKEN)
