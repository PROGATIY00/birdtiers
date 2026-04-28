import discord
from discord import app_commands
from flask import Flask, render_template_string, request
from pymongo import MongoClient
import os
import threading
import asyncio
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID") 
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

MODE_ICONS = {
    "Crystal": "https://i.imgur.com/8QO5W5M.png",
    "UHC": "https://i.imgur.com/K4zI904.png",
    "Pot": "https://i.imgur.com/example_pot.png"
}

# --- DB SETUP ---
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
partners_col = db_mongo['partners']
settings_col = db_mongo['settings']

def get_global_rank(pts):
    if pts >= 400: return "Combat Grandmaster"
    if pts >= 200: return "Combat Master"
    return "Combat Ace"

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

@bot.tree.command(name="rank", description="Update tier with Promotion/Demotion logic")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator: return
    tier = tier.upper().strip()
    if tier not in TIER_ORDER: return await interaction.response.send_message("Invalid Tier", ephemeral=True)
    
    existing = players_col.find_one({"username": player, "gamemode": mode.value})
    status_text, color, old_t = "Placed into", discord.Color.blue(), "None"

    if existing:
        old_t = existing.get('tier', 'LT5')
        if TIER_ORDER.index(tier) > TIER_ORDER.index(old_t):
            status_text, color = "Promoted to", discord.Color.green()
        elif TIER_ORDER.index(tier) < TIER_ORDER.index(old_t):
            status_text, color = "Demoted to", discord.Color.red()
        else:
            status_text, color = "Updated in", discord.Color.gold()

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"username": player, "gamemode": mode.value, "tier": tier, "region": region.value, "peak": tier, "retired": False}},
        upsert=True
    )

    if LOG_CHANNEL_ID:
        try:
            ch = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            embed = discord.Embed(title="📈 Tier Update", description=f"**{player}** has been **{status_text}** **{tier}**!", color=color)
            embed.set_thumbnail(url=f"https://minotar.net/helm/{player}/100.png")
            embed.add_field(name="Mode", value=mode.value, inline=True)
            embed.add_field(name="Prev", value=old_t, inline=True)
            await ch.send(embed=embed)
        except: pass
    await interaction.response.send_message(f"✅ Updated {player}", ephemeral=True)

@bot.tree.command(name="retire", description="Retire a player (Legacy Points)")
async def retire(interaction: discord.Interaction, player: str, status: bool):
    if not interaction.user.guild_permissions.administrator: return
    players_col.update_many({"username": {"$regex": f"^{player}$", "$options": "i"}}, {"$set": {"retired": status}})
    await interaction.response.send_message(f"✅ {player} retirement set to {status}", ephemeral=True)

@bot.tree.command(name="add_partner", description="Add a sponsor to the website")
async def add_partner(interaction: discord.Interaction, name: str, img_url: str, link: str):
    if not interaction.user.guild_permissions.administrator: return
    partners_col.update_one({"name": name}, {"$set": {"img": img_url, "link": link}}, upsert=True)
    await interaction.response.send_message(f"✅ Added Partner: {name}", ephemeral=True)

# --- WEB UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MagmaTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 2px solid var(--accent); display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index: 100;}
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .discord-btn { background: #5865F2; color: white; text-decoration: none; padding: 8px 16px; border-radius: 8px; font-weight: 600; font-size: 13px; }
        .mode-nav { display: flex; justify-content:center; gap: 8px; padding: 15px; background: #0f1117; border-bottom: 1px solid var(--border); overflow-x: auto; }
        .mode-btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--dim); text-decoration: none; font-size: 12px; white-space: nowrap; }
        .mode-btn.active { border-color: var(--accent); color: white; background: #1c1f2b; }
        @property --angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rotate { to { --angle: 360deg; } }
        .insane-row { position: relative; background: var(--card) !important; z-index: 1; border-radius: 12px; }
        .insane-row::before { content: ''; position: absolute; inset: -2px; z-index: -1; background: conic-gradient(from var(--angle), transparent 70%, #ff4500, #ff8c00, #ff4500); animation: rotate 2s linear infinite; border-radius: 14px; }
        .modal-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:1001; display:flex; justify-content:center; align-items:center; }
        .profile-modal { background: #11141c; width: 450px; border-radius: 20px; border: 2px solid #2d3647; padding: 40px; position: relative; text-align: center; }
        .modal-avatar { width: 100px; height: 100px; border-radius: 50%; border: 3px solid #ffcc00; margin-bottom: 15px; }
        .modal-tier-grid { display: grid; grid-template-columns: 1fr; gap: 10px; background: #080a0f; padding: 15px; border-radius: 12px; margin-top: 20px; max-height: 250px; overflow-y: auto; }
        .mode-item { display: flex; align-items: center; gap: 10px; background: #1c1f26; padding: 10px; border-radius: 8px; }
        .tier-badge { color: var(--accent); font-weight: 800; margin-left: auto; }
        .wrapper { max-width: 900px; margin: auto; padding: 25px; }
        .player-row { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 25px; margin-bottom: 10px; display: grid; grid-template-columns: 40px 50px 1fr 80px 100px; align-items: center; text-decoration: none; color: inherit; }
        .player-row.retired { opacity: 0.5; filter: grayscale(0.6); border-style: dashed; }
        .retired-badge { background: #333; color: #aaa; font-size: 9px; padding: 2px 5px; border-radius: 4px; text-transform: uppercase; margin-left: 5px; }
        .NA { color: #ff6b6b; } .EU { color: #51cf66; } .ASIA { color: #fcc419; }
        .partner-img { height: 40px; margin: 0 15px; filter: grayscale(1); opacity: 0.5; transition: 0.3s; }
        .partner-img:hover { filter: grayscale(0); opacity: 1; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <div style="display:flex; align-items:center; gap:20px;">
            <form><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search..." value="{{ search_query }}"></form>
            <a href="{{ invite_link }}" target="_blank" class="discord-btn">Discord</a>
        </div>
    </div>
    <div class="mode-nav">
        <a href="/" class="mode-btn {% if not current_mode %}active{% endif %}">GLOBAL</a>
        {% for m in all_modes %}<a href="/?mode={{m}}" class="mode-btn {% if current_mode == m %}active{% endif %}">{{m|upper}}</a>{% endfor %}
    </div>
    {% if spotlight %}
    <div class="modal-overlay">
        <div class="profile-modal">
            <a href="/" style="position:absolute; top:15px; right:20px; color:#555; text-decoration:none; font-size:24px;">×</a>
            <img src="https://minotar.net/helm/{{spotlight.username}}/100.png" class="modal-avatar">
            <h1>{{ spotlight.username }}</h1>
            <p style="color:#ffcc00; font-weight:800;">#{{ spotlight.pos }} OVERALL | {{ spotlight.region }}</p>
            <div class="modal-tier-grid">
                {% for r in spotlight.ranks %}<div class="mode-item">
                    {% if r.gamemode in icons %}<img src="{{ icons[r.gamemode] }}" style="height:20px;">{% endif %}
                    <span style="font-size:12px; font-weight:600;">{{ r.gamemode }}</span>
                    <div class="tier-badge">{{ r.tier }}</div>
                </div>{% endfor %}
            </div>
        </div>
    </div>
    {% endif %}
    <div class="wrapper">
        {% for p in players %}
        <a href="/?search={{p.username}}" class="player-row {% if p.tier in ['HT1', 'LT1'] %}insane-row{% endif %} {% if p.retired %}retired{% endif %}">
            <div style="font-weight:800; color:var(--accent)">#{{ loop.index }}</div>
            <img src="https://minotar.net/helm/{{p.username}}/35.png" style="border-radius:6px;">
            <div><b>{{ p.username }}</b> {% if p.retired %}<span class="retired-badge">Retired</span>{% endif %}
            <span style="font-size:10px; padding:2px 8px; border:1px solid var(--accent); border-radius:4px; margin-left:10px;">{{ p.rank_name }}</span></div>
            <div class="{{ p.region }}" style="font-weight:800; font-size:12px;">{{ p.region }}</div>
            <div style="text-align:right; font-weight:800; color:var(--accent);">{{ p.tier }}</div>
        </a>
        {% endfor %}
    </div>
    <div style="text-align:center; padding:50px; border-top:1px solid var(--border);">
        <p style="font-size:10px; color:var(--dim); margin-bottom:20px; text-transform:uppercase;">Partners</p>
        {% for p in partners %}<a href="{{p.link}}"><img src="{{p.img}}" class="partner-img"></a>{% endfor %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    m_doc = settings_col.find_one({"id": "maintenance"})
    if m_doc and m_doc.get('enabled'): return "<h1>Maintenance Mode</h1>"
    mode_f = request.args.get('mode', '')
    search_q = request.args.get('search', '').strip().lower()
    players_data = list(players_col.find({}))
    p_list = list(partners_col.find({}))
    stats = {}
    for p in players_data:
        u, t, gm = p['username'], p['tier'], p['gamemode']
        is_ret = p.get('retired', False)
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "region": p.get('region', 'NA'), "retired": is_ret}
        if mode_f:
            if gm.lower() == mode_f.lower(): stats[u].update({"pts": val, "tier": t})
            else: stats[u]["pts"] = -1
        else:
            stats[u]["pts"] += (val * 0.1) if is_ret else val

    processed = sorted([{"username": u, "points": int(d["pts"]), "tier": d["tier"], "region": d["region"], "retired": d["retired"], "rank_name": get_global_rank(d["pts"])} for u, d in stats.items() if d["pts"] >= 0], key=lambda x: (x["retired"], -x["points"]))
    spotlight = None
    if search_q:
        res = list(players_col.find({"username": {"$regex": f"^{search_q}$", "$options": "i"}}))
        if res:
            pos = next((i + 1 for i, p in enumerate(processed) if p['username'].lower() == search_q), "?")
            spotlight = {"username": res[0]['username'], "ranks": res, "pos": pos, "region": res[0].get('region', 'NA')}
    return render_template_string(HTML_TEMPLATE, players=processed, spotlight=spotlight, search_query=search_q, all_modes=MODES, current_mode=mode_f, icons=MODE_ICONS, partners=p_list, invite_link=DISCORD_INVITE)

def run_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    bot.run(TOKEN)

if not os.environ.get("BOT_ALIVE"):
    os.environ["BOT_ALIVE"] = "true"
    threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
