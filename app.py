import discord
from discord import app_commands
from flask import Flask, render_template_string, request, jsonify
from pymongo import MongoClient
import os
import threading
import datetime

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")      

# --- DATA MAPS ---
MODES = ["Crystal", "UHC", "Pot", "SMP", "Axe", "Sword", "Mace", "Cart", "1.8", "Trident", "Spear"]
REGIONS = ["NA", "EU", "ASIA", "AF", "OC", "SA"]
TIER_ORDER = ["LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
TIER_DATA = {t: (i + 1) * 5 for i, t in enumerate(TIER_ORDER)}

# --- DB SETUP ---
client_db = MongoClient(MONGO_URI)
db_mongo = client_db['magmatiers_db']
players_col = db_mongo['players']

def get_global_rank(pts):
    if pts >= 500: return "Combat Grandmaster"
    if pts >= 250: return "Combat Master"
    if pts >= 100: return "Combat Ace"
    return "Rookie"

# --- DISCORD BOT ---
class MagmaBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()

bot = MagmaBot()

# --- WEB UI & API (FLASK) ---
app = Flask(__name__)

# --- API ENDPOINTS ---
@app.route('/api/player/<username>')
def get_player_api(username):
    p_data = list(players_col.find({"username": {"$regex": f"^{username}$", "$options": "i"}}))
    if not p_data:
        return jsonify({"username": username, "tested": False, "ranks": {}}), 404
    
    response = {
        "username": p_data[0]['username'],
        "tested": True,
        "region": p_data[0].get('region', 'NA'),
        "ranks": {d['gamemode']: d['tier'] for d in p_data}
    }
    return jsonify(response)

# --- THE API MENU ROUTE ---
@app.route('/api-docs')
def api_docs():
    return render_template_string(API_MENU_HTML)

# --- HTML TEMPLATES ---
NAVBAR_HTML = """
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <div style="display:flex; align-items:center; gap:20px;">
            <a href="/api-docs" style="color:var(--dim); text-decoration:none; font-size:14px; font-weight:600;">API MENU</a>
            <form action="/"><input type="text" name="search" style="background:#0b0c10; border:1px solid var(--border); padding:8px 18px; border-radius:20px; color:white; outline:none;" placeholder="Search player..."></form>
        </div>
    </div>
"""

API_MENU_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>API Menu | MagmaTIERS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;800&display=swap');
        :root { --bg: #0b0c10; --card: #14171f; --border: #262932; --accent: #ff4500; --text: #e0e6ed; --dim: #8b949e; }
        body { background: var(--bg); color: var(--text); font-family: 'Fredoka', sans-serif; margin: 0; line-height: 1.6; }
        .navbar { background: #0f1117; padding: 15px 50px; border-bottom: 3px solid var(--accent); display: flex; justify-content: space-between; align-items: center; }
        .logo { color: white; font-weight: 800; font-size: 26px; text-decoration: none; text-transform: uppercase; }
        .logo span { color: var(--accent); }
        .container { max-width: 800px; margin: 40px auto; padding: 20px; }
        .endpoint-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 25px; margin-bottom: 20px; }
        code { background: #000; color: #00ff00; padding: 4px 8px; border-radius: 4px; font-family: monospace; }
        pre { background: #000; padding: 15px; border-radius: 8px; overflow-x: auto; color: #00ff00; font-size: 13px; }
        .method { background: var(--accent); color: white; padding: 2px 8px; border-radius: 4px; font-weight: 800; font-size: 12px; margin-right: 10px; }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/" class="logo">Magma<span>TIERS</span></a>
        <a href="/" style="color:var(--dim); text-decoration:none;">← Back to Leaderboard</a>
    </div>
    <div class="container">
        <h1>Developer API</h1>
        <p style="color:var(--dim);">Integrate MagmaTIERS data into your Minecraft mods or plugins.</p>
        
        <div class="endpoint-card">
            <h3><span class="method">GET</span> Get Player Tiers</h3>
            <p>Fetch all tested tiers and region for a specific player.</p>
            <code>/api/player/{username}</code>
            <h4>Example Request:</h4>
            <pre>https://your-app.render.com/api/player/Gemini</pre>
            <h4>Example Response:</h4>
            <pre>
{
  "username": "Gemini",
  "tested": true,
  "region": "NA",
  "ranks": {
    "Crystal": "HT1",
    "UHC": "LT2"
  }
}
            </pre>
        </div>
    </div>
</body>
</html>
"""

# ... (Insert the rest of your index/leaderboard HTML and logic here)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
