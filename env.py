import os

# Load environment variables from .env file
try:
    with open('.env', 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                os.environ[key] = value
except FileNotFoundError:
    pass

# Bot configuration
BOT_TOKEN = (os.getenv("BOT_TOKEN","8437367286:AAFMJMWurNe154x-M6r_PzB9z2pxOl_xmbU"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "6419935994"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "-1003033780543"))
DATA_FILE = "data.json"
