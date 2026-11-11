# config.py
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # .env ဖိုင်ကို ဖတ်မည်
except ImportError:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

API_TOKEN       = os.environ.get('BOT_TOKEN', '')
ADMIN_ID        = int(os.environ.get('ADMIN_ID', '0'))
YOUR_CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '0'))
SELL_PROOF_CHANNEL_ID = int(os.environ.get('SELL_PROOF_CHANNEL_ID', '0'))
SELL_PROOF_CHANNEL_URL = os.environ.get('SELL_PROOF_CHANNEL_URL', 'https://t.me/enistoreproof')
CHANNEL_URL     = os.environ.get('CHANNEL_URL', 'https://t.me/ENIpremiumstore')
SUPPORT_URL     = os.environ.get('SUPPORT_URL', 'https://t.me/independence_N')
DATABASE_NAME   = os.path.join(BASE_DIR, 'shop.db')
MMK_PER_USD     = float(os.environ.get('MMK_PER_USD', '4500'))
STOCK_RESERVATION_MINUTES = int(os.environ.get('STOCK_RESERVATION_MINUTES', '10'))
USDT_ERC20_ADDRESS = os.environ.get('USDT_ERC20_ADDRESS', os.environ.get('USDT_TRC20_ADDRESS', ''))
USDT_BEP20_ADDRESS = os.environ.get('USDT_BEP20_ADDRESS', '')
BINANCE_PAY_ID     = os.environ.get('BINANCE_PAY_ID', '')
OUTLINE_API_URL = os.environ.get('OUTLINE_API_URL', '').rstrip('/')
OUTLINE_API_VERIFY_TLS = os.environ.get('OUTLINE_API_VERIFY_TLS', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
BINANCE_API_KEY    = os.environ.get('BINANCE_API_KEY', '').strip()
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '').strip()
ETHERSCAN_API_KEY  = os.environ.get('ETHERSCAN_API_KEY', '').strip()
BSCSCAN_API_KEY    = os.environ.get('BSCSCAN_API_KEY', '').strip()
CRYPTOPAY_API_TOKEN = os.environ.get('CRYPTOPAY_API_TOKEN', '').strip()
