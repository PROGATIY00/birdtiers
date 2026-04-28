import discord
from discord import app_commands
from flask import Flask, render_template_string, request
from pymongo import MongoClient
import os
import threading
import asyncio

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID")
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://dsc.gg/magmatiers")

# --- DATA ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 10 for i, t in enumerate(TIER_ORDER)}

# --- DB SETUP ---
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']
settings_col = db_mongo['settings']
partners_col = db_mongo['partners']

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash Commands Synced")

bot = MagmaBot()

@bot.tree.command(name="rank", description="Set player tier")
@app_commands.choices(
    mode=[app_commands.Choice(name=m, value=m) for m in MODES],
    region=[app_commands.Choice(name=r, value=r) for r in REGIONS]
)
async def rank(interaction: discord.Interaction, player: str, mode: app_commands.Choice[str], tier: str, region: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

    tier = tier.upper().strip()
    if tier not in TIER_ORDER:
        return await interaction.response.send_message(f"Invalid Tier. Use: {', '.join(TIER_ORDER)}", ephemeral=True)

    players_col.update_one(
        {"username": player, "gamemode": mode.value},
        {"$set": {"username": player, "gamemode": mode.value, "tier": tier, "region": region.value, "retired": False}},
        upsert=True
    )

    if LOG_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(int(LOG_CHANNEL_ID))
            await channel.send(f"🌋 **{player}** ranked **{tier}** in **{mode.value}** ({region.value})")
        except: pass

    await interaction.response.send_message(f"✅ Ranked {player} as {tier}!", ephemeral=True)

# --- FLASK APP ---
app = Flask(__name__)

# Start Bot in Background Thread so Gunicorn doesn't block it
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot.start(TOKEN))

if not os.environ.get("BOT_STARTED"):
    os.environ["BOT_STARTED"] = "true"
    threading.Thread(target=run_bot, daemon=True).start()

@app.route('/')
def index():
    # Maintenance check
    m_doc = settings_col.find_one({"id": "maintenance"})
    if m_doc and m_doc.get('enabled'):
        return "<h1>Maintenance Mode</h1>"

    mode_f = request.args.get('mode', '')
    search_q = request.args.get('search', '').strip().lower()
    
    # Process leaderboard logic
    players_data = list(players_col.find({}))
    stats = {}
    for p in players_data:
        u, t = p['username'], p['tier']
        val = TIER_DATA.get(t, 0)
        if u not in stats: stats[u] = {"pts": 0, "tier": t, "region": p.get('region', 'NA')}
        stats[u]["pts"] += val

    processed = sorted([{"username": u, "points": d["pts"], "tier": d["tier"], "region": d["region"]} for u, d in stats.items()], key=lambda x: -x["points"])

    # Basic UI (Simplified for functionality test)
    return render_template_string("""
    <h1>MagmaTIERS Leaderboard</h1>
    <p>Bot Status: Running</p>
    <ul>
        {% for p in players %}
        <li>#{{ loop.index }} {{ p.username }} - {{ p.tier }} ({{ p.points }} pts)</li>
        {% endfor %}
    </ul>
    """, players=processed)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
