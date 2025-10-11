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
BOT_TOKEN = (os.getenv("BOT_TOKEN","7988925435:AAE30e4vC5A2vHJoahphAA2bjsoFsyd8gJA"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8197491717"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "-1002921388318"))
DATA_FILE = "data.json"
