import threading, os
from index import *

start_mongo_backup_loop()
threading.Thread(target=lambda: bot.run(TOKEN), daemon=True).start()
port = int(os.getenv("PORT", "10000"))
app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
