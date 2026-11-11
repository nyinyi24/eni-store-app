"""Start both the Telegram Bot (main.py) and FastAPI Mobile Backend (api.py) together."""
import threading
import uvicorn
from api import app

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    print("🚀 Starting FastAPI Mobile App Server on port 8000...")
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    print("🤖 Starting ENI Premium Store Telegram Bot...")
    import main
    main.bot.infinity_polling(timeout=10, long_polling_timeout=5)
