import json, os, asyncio
from datetime import datetime, timedelta
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from env import BOT_TOKEN, ADMIN_ID, ADMIN_GROUP_ID, DATA_FILE
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://wanglinmongodb:wanglin@cluster0.tny5vhz.mongodb.net/")
try:
    mongo_client = MongoClient(MONGO_URI)
    mongo_client.admin.command('ping')
    db = mongo_client['mlbb_bot']
    users_collection = db['users']
    prices_collection = db['prices']
    settings_collection = db['settings']
    print("✅ MongoDB connection successful!")
except ConnectionFailure:
    print("❌ MongoDB connection failed! Using JSON fallback...")
    mongo_client = None
    db = None

# Authorized users - only these users can use the bot
AUTHORIZED_USERS = set()

# User states for restricting actions after screenshot
user_states = {}

# Bot maintenance mode
bot_maintenance = {
    "orders": True,    # True = enabled, False = disabled
    "topups": True,    # True = enabled, False = disabled
    "general": True    # True = enabled, False = disabled
}

# Payment information
payment_info = {
    "kpay_number": "09678786528",
    "kpay_name": "Ma May Phoo Wai",
    "kpay_image": None,  # Store file_id of KPay QR code image
    "wave_number": "09673585480",
    "wave_name": "Nine Nine",
    "wave_image": None   # Store file_id of Wave QR code image
}

def is_user_authorized(user_id):
    """Check if user is authorized to use the bot"""
    return str(user_id) in AUTHORIZED_USERS or int(user_id) == ADMIN_ID

async def is_bot_admin_in_group(bot, chat_id):
    """Check if bot is admin in the group"""
    try:
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(chat_id, me.id)
        is_admin = bot_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        print(f"Bot admin check for group {chat_id}: {is_admin}, status: {bot_member.status}")
        return is_admin
    except Exception as e:
        print(f"Error checking bot admin status in group {chat_id}: {e}")
        return False



def simple_reply(message_text):
    """
    Simple auto-replies for common queries
    """
    message_lower = message_text.lower()

    # Greetings
    if any(word in message_lower for word in ["hello", "hi", "မင်္ဂလာပါ", "ဟယ်လို", "ဟိုင်း", "ကောင်းလား"]):
        return ("👋 မင်္ဂလာပါ! 𝙆𝙀𝘼 𝙈𝙇𝘽𝘽 𝘼𝙐𝙏𝙊 𝙏𝙊𝙋 𝙐𝙋 𝘽𝙊𝙏 မှ ကြိုဆိုပါတယ်!\n\n"
                "📱 Bot commands များ သုံးရန် /start နှိပ်ပါ\n")


    # Help requests
    elif any(word in message_lower for word in ["help", "ကူညီ", "အကူအညီ", "မသိ", "လမ်းညွှန်"]):
        return ("📱 ***အသုံးပြုနိုင်တဲ့ commands:***\n\n"
                "• /start - Bot စတင်အသုံးပြုရန်\n"
                "• /mmb gameid serverid amount - Diamond ဝယ်ယူရန်\n"
                "• /balance - လက်ကျန်ငွေ စစ်ရန်\n"
                "• /topup amount - ငွေဖြည့်ရန်\n"
                "• /price - ဈေးနှုန်းများ ကြည့်ရန်\n"
                "• /history - မှတ်တမ်းများ ကြည့်ရန်\n\n"
                "💡 အသေးစိတ် လိုအပ်ရင် admin ကို ဆက်သွယ်ပါ!")

    # Default response
    else:
        return ("📱 ***MLBB Diamond Top-up Bot***\n\n"
                "💎 ***Diamond ဝယ်ယူရန် /mmb command သုံးပါ။***\n"
                "💰 ***ဈေးနှုန်းများ သိရှိရန် /price နှိပ်ပါ။***\n"
                "🆘 ***အကူအညီ လိုရင် /start နှိပ်ပါ။***")

def load_data():
    if db is not None:
        # Use MongoDB
        try:
            # Get settings document
            settings = settings_collection.find_one({"_id": "main_settings"})
            if not settings:
                settings = {
                    "_id": "main_settings",
                    "authorized_users": [],
                    "admin_ids": [ADMIN_ID],
                    "clone_bots": {}
                }
                settings_collection.insert_one(settings)
            
            # Get all users
            users = {}
            for user in users_collection.find():
                user_id = user.pop("_id")
                users[user_id] = user
            
            # Get all prices
            prices = {}
            price_doc = prices_collection.find_one({"_id": "prices"})
            if price_doc:
                prices = price_doc.get("items", {})
            
            return {
                "users": users,
                "prices": prices,
                "authorized_users": settings.get("authorized_users", []),
                "admin_ids": settings.get("admin_ids", [ADMIN_ID]),
                "clone_bots": settings.get("clone_bots", {})
            }
        except Exception as e:
            print(f"MongoDB error: {e}, using JSON fallback")
    
    # Fallback to JSON file
    if not os.path.exists(DATA_FILE):
        initial_data = {
            "users": {},
            "prices": {},
            "authorized_users": [],
            "admin_ids": [ADMIN_ID]
        }
        with open(DATA_FILE, "w") as f:
            json.dump(initial_data, f, indent=2)

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            if "users" not in data:
                data["users"] = {}
            if "prices" not in data:
                data["prices"] = {}
            if "authorized_users" not in data:
                data["authorized_users"] = []
            if "admin_ids" not in data:
                data["admin_ids"] = [ADMIN_ID]
            return data
    except json.JSONDecodeError:
        initial_data = {
            "users": {},
            "prices": {},
            "authorized_users": [],
            "admin_ids": [ADMIN_ID]
        }
        with open(DATA_FILE, "w") as f:
            json.dump(initial_data, f, indent=2)
        return initial_data

def save_data(data):
    if db is not None:
        # Use MongoDB
        try:
            # Save users
            for user_id, user_data in data.get("users", {}).items():
                users_collection.update_one(
                    {"_id": user_id},
                    {"$set": user_data},
                    upsert=True
                )
            
            # Save prices
            prices_collection.update_one(
                {"_id": "prices"},
                {"$set": {"items": data.get("prices", {})}},
                upsert=True
            )
            
            # Save settings
            settings_collection.update_one(
                {"_id": "main_settings"},
                {"$set": {
                    "authorized_users": data.get("authorized_users", []),
                    "admin_ids": data.get("admin_ids", [ADMIN_ID]),
                    "clone_bots": data.get("clone_bots", {})
                }},
                upsert=True
            )
            return
        except Exception as e:
            print(f"MongoDB save error: {e}, using JSON fallback")
    
    # Fallback to JSON file
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_authorized_users():
    """Load authorized users from data file"""
    global AUTHORIZED_USERS
    data = load_data()
    AUTHORIZED_USERS = set(data.get("authorized_users", []))

def save_authorized_users():
    """Save authorized users to data file"""
    data = load_data()
    data["authorized_users"] = list(AUTHORIZED_USERS)
    save_data(data)

def load_prices():
    """Load custom prices from data file"""
    data = load_data()
    return data.get("prices", {})

def save_prices(prices):
    """Save prices to data file"""
    data = load_data()
    data["prices"] = prices
    save_data(data)

def validate_game_id(game_id):
    """Validate MLBB Game ID (6-10 digits)"""
    if not game_id.isdigit():
        return False
    if len(game_id) < 6 or len(game_id) > 10:
        return False
    return True

def validate_server_id(server_id):
    """Validate MLBB Server ID (3-5 digits)"""
    if not server_id.isdigit():
        return False
    if len(server_id) < 3 or len(server_id) > 5:
        return False
    return True

def is_banned_account(game_id):
    """
    Check if MLBB account is banned
    This is a simple example - in reality you'd need to integrate with MLBB API
    For now, we'll use some common patterns of banned accounts
    """
    # Add known banned account IDs here
    banned_ids = [
        "123456789",  # Example banned ID
        "000000000",  # Invalid pattern
        "111111111",  # Invalid pattern
    ]

    # Check if game_id matches banned patterns
    if game_id in banned_ids:
        return True

    # Check for suspicious patterns (all same digits, too simple patterns)
    if len(set(game_id)) == 1:  # All same digits like 111111111
        return True

    if game_id.startswith("000") or game_id.endswith("000"):
        return True

    return False

def get_price(diamonds):
    # Load custom prices first - these override defaults
    custom_prices = load_prices()
    if diamonds in custom_prices:
        return custom_prices[diamonds]

    # Default prices
    if diamonds.startswith("wp") and diamonds[2:].isdigit():
        n = int(diamonds[2:])
        if 1 <= n <= 10:
            return n * 6000
    table = {
        "11": 950, "22": 1900, "33": 2850, "56": 4200, "112": 8200,
        "86": 5100, "172": 10200, "257": 15300, "343": 20400,
        "429": 25500, "514": 30600, "600": 35700, "706": 40800,
        "878": 51000, "963": 56100, "1049": 61200, "1135": 66300,
        "1412": 81600, "2195": 122400, "3688": 204000,
        "5532": 306000, "9288": 510000, "12976": 714000,
        "55": 3500, "165": 10000, "275": 16000, "565": 33000
    }
    return table.get(diamonds)

def is_payment_screenshot(update):
    """
    Check if the image is likely a payment screenshot
    This is a basic validation - you can enhance it with image analysis
    """
    # For now, we'll accept all photos as payment screenshots
    # You can add image analysis here to check for payment app UI elements
    if update.message.photo:
        # Check if photo has caption containing payment keywords
        caption = update.message.caption or ""
        payment_keywords = ["kpay", "wave", "payment", "pay", "transfer", "လွှဲ", "ငွေ"]

        # Accept all photos for now, but you can add more validation here
        return True
    return False

pending_topups = {}

async def check_pending_topup(user_id):
    """Check if user has pending topups"""
    data = load_data()
    user_data = data["users"].get(user_id, {})

    for topup in user_data.get("topups", []):
        if topup.get("status") == "pending":
            return True
    return False

async def send_pending_topup_warning(update: Update):
    """Send pending topup warning message"""
    await update.message.reply_text(
        "⏳ ***Pending Topup ရှိနေပါတယ်!***\n\n"
        "❌ သင့်မှာ admin က approve မလုပ်သေးတဲ့ topup ရှိနေပါတယ်။\n\n"
        "***လုပ်ရမည့်အရာများ***:\n"
        "***• Admin က topup ကို approve လုပ်ပေးတဲ့အထိ စောင့်ပါ။***\n"
        "***• Approve ရပြီးမှ command တွေကို ပြန်အသုံးပြုနိုင်ပါမယ်။***\n\n"
        "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***\n\n"
        "💡 /balance ***နဲ့ status စစ်ကြည့်နိုင်ပါတယ်။***",
        parse_mode="Markdown"
    )

async def check_maintenance_mode(command_type):
    """Check if specific command type is in maintenance mode"""
    return bot_maintenance.get(command_type, True)

async def send_maintenance_message(update: Update, command_type):
    """Send maintenance mode message with beautiful UI"""
    user_name = update.effective_user.first_name or "User"

    if command_type == "orders":
        msg = (
            f"မင်္ဂလာပါ {user_name}! 👋\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏸️ ***Bot အော်ဒါတင်ခြင်းအား ခေတ္တ ယာယီပိတ်ထားပါသည်** ⏸️***\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "***🔄 Admin မှ ပြန်လည်ဖွင့်ပေးမှ အသုံးပြုနိုင်ပါမည်။***\n\n"
            "📞 အရေးပေါ်ဆိုရင် Admin ကို ဆက်သွယ်ပါ။"
        )
    elif command_type == "topups":
        msg = (
            f"မင်္ဂလာပါ {user_name}! 👋\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏸️ ***Bot ငွေဖြည့်ခြင်းအား ခေတ္တ ယာယီပိတ်ထားပါသည်*** ⏸️\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "***🔄 Admin မှ ပြန်လည်ဖွင့်ပေးမှ အသုံးပြုနိုင်ပါမည်။***\n\n"
            "📞 ***အရေးပေါ်ဆိုရင် Admin ကို ဆက်သွယ်ပါ။***"
        )
    else:
        msg = (
            f"***မင်္ဂလာပါ*** {user_name}! 👋\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏸️ ***Bot အား ခေတ္တ ယာယီပိတ်ထားပါသည်*** ⏸️\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "***🔄 Admin မှ ပြန်လည်ဖွင့်ပေးမှ အသုံးပြုနိုင်ပါမည်။***\n\n"
            "📞 ***အရေးပေါ်ဆိုရင် Admin ကို ဆက်သွယ်ပါ။***"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    username = user.username or "-"
    name = f"{user.first_name} {user.last_name or ''}".strip()

    # Load authorized users
    load_authorized_users()

    # Check if user is authorized
    if not is_user_authorized(user_id):
        #board Create keyboard with Register button only
        keyboard = [
            [InlineKeyboardButton("📝 Register တောင်းဆိုမယ်", callback_data="request_register")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🚫 ***Bot အသုံးပြုခွင့် မရှိပါ!***\n\n"
            f"👋 ***မင်္ဂလာပါ*** `{name}`!\n"
            f"🆔 Your ID: `{user_id}`\n\n"
            "❌ ***သင်သည် ဤ bot ကို အသုံးပြုခွင့် မရှိသေးပါ။***\n\n"
            "***လုပ်ရမည့်အရာများ***:\n"
            "***• အောက်က 'Register တောင်းဆိုမယ်' button ကို နှိပ်ပါ***\n"
            "***• သို့မဟုတ်*** /register ***command သုံးပါ။***\n"
            "***• Owner က approve လုပ်တဲ့အထိ စောင့်ပါ။***\n\n"
            "✅ ***Owner က approve လုပ်ပြီးမှ bot ကို အသုံးပြုနိုင်ပါမယ်။***\n\n",

            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return

    data = load_data()

    # Check for pending topups first
    if await check_pending_topup(user_id):
        await send_pending_topup_warning(update)
        return

    if user_id not in data["users"]:
        data["users"][user_id] = {
            "name": name,
            "username": username,
            "balance": 0,
            "orders": [],
            "topups": []
        }
        save_data(data)

    # Clear any restricted state when starting
    if user_id in user_states:
        del user_states[user_id]

    # Create clickable name
    clickable_name = f"[{name}](tg://user?id={user_id})"

    msg = (
        f"👋 ***မင်္ဂလာပါ*** {clickable_name}!\n"
        f"🆔 ***Telegram User ID:*** `{user_id}`\n\n"
        "💎 ***𝙆𝙀𝘼 𝙈𝙇𝘽𝘽 𝘼𝙐𝙏𝙊 𝙏𝙊𝙋 𝙐𝙋 𝘽𝙊𝙏*** မှ ကြိုဆိုပါတယ်။\n\n"
        "***အသုံးပြုနိုင်တဲ့ command များ***:\n"
        "➤ /mmb gameid serverid amount\n"
        "➤ /balance - ဘယ်လောက်လက်ကျန်ရှိလဲ စစ်မယ်\n"
        "➤ /topup amount - ငွေဖြည့်မယ် (screenshot တင်ပါ)\n"
        "➤ /price - Diamond များရဲ့ ဈေးနှုန်းများ\n"
        "➤ /history - အော်ဒါမှတ်တမ်းကြည့်မယ်\n\n"
        "***📌 ဥပမာ***:\n"
        "`/mmb 123456789 12345 wp1`\n"
        "`/mmb 123456789 12345 86`\n\n"
        "***လိုအပ်တာရှိရင် Owner ကို ဆက်သွယ်နိုင်ပါတယ်။***"
    )

    # Try to send with user's profile photo
    try:
        user_photos = await context.bot.get_user_profile_photos(user_id=int(user_id), limit=1)
        if user_photos.total_count > 0:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=user_photos.photos[0][0].file_id,
                caption=msg,
                parse_mode="Markdown"
            )
        else:
            # No profile photo, send text only
            await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        # If error getting photo, send text only
        await update.message.reply_text(msg, parse_mode="Markdown")

async def mmb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check authorization
    load_authorized_users()
    if not is_user_authorized(user_id):
        keyboard = [[InlineKeyboardButton("👑 Contact Owner", url=f"tg://user?id={ADMIN_ID}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 အသုံးပြုခွင့် မရှိပါ!\n\n"
            "Owner ထံ bot အသုံးပြုခွင့် တောင်းဆိုပါ။",
            reply_markup=reply_markup
        )
        return

    # Check maintenance mode
    if not await check_maintenance_mode("orders"):
        await send_maintenance_message(update, "orders")
        return

    # Check if user is restricted after screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await update.message.reply_text(
            "⏳ ***Screenshot ပို့ပြီးပါပြီ!***\n\n"
            "❌ ***Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ commands တွေ အသုံးပြုလို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n"
            "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Check for pending topups first
    if await check_pending_topup(user_id):
        await send_pending_topup_warning(update)
        return

    # Check if user has pending topup process
    if user_id in pending_topups:
        await update.message.reply_text(
            "⏳ ***Topup လုပ်ငန်းစဉ် အရင်ပြီးဆုံးပါ!***\n\n"
            "❌ ***လက်ရှိ topup လုပ်ငန်းစဉ်ကို မပြီးသေးပါ။***\n\n"
            "***လုပ်ရမည့်အရာများ***:\n"
            "***• Payment app ရွေးပြီး screenshot တင်ပါ***\n"
            "***• သို့မဟုတ် /cancel နှိပ်ပြီး ပယ်ဖျက်ပါ***\n\n"
            "💡 ***Topup ပြီးမှ order တင်နိုင်ပါမယ်။***",
            parse_mode="Markdown"
        )
        return

    args = context.args

    if len(args) != 3:
        await update.message.reply_text(
            "❌ အမှားရှိပါတယ်!\n\n"
            "***မှန်ကန်တဲ့ format***:\n"
            "/mmb gameid serverid amount\n\n"
            "***ဥပမာ***:\n"
            "`/mmb 123456789 12345 wp1`\n"
            "`/mmb 123456789 12345 86`",
            parse_mode="Markdown"
        )
        return

    game_id, server_id, amount = args

    # Validate Game ID
    if not validate_game_id(game_id):
        await update.message.reply_text(
            "❌ ***Game ID မှားနေပါတယ်!***\n\n"
            "***Game ID requirements***:\n"
            "***• ကိန်းဂဏန်းများသာ ပါရမည်။***\n"
            "***• 6-10 digits ရှိရမည်။***\n\n"
            "***ဥပမာ***: `123456789`",
            parse_mode="Markdown"
        )
        return

    # Validate Server ID
    if not validate_server_id(server_id):
        await update.message.reply_text(
            "❌ ***Server ID မှားနေပါတယ်!***\n\n"
            "***Server ID requirements***:\n"
            "***• ကိန်းဂဏန်းများသာ ပါရမည်။***\n"
            "***• 3-5 digits ရှိရမည်။***\n\n"
            "***ဥပမာ***: `8662`, `12345`",
            parse_mode="Markdown"
        )
        return

    # Check if account is banned
    if is_banned_account(game_id):
        await update.message.reply_text(
            "🚫 ***Account Ban ဖြစ်နေပါတယ်!***\n\n"
            f"🎮 Game ID: `{game_id}`\n"
            f"🌐 Server ID: `{server_id}`\n\n"
            "❌ ဒီ account မှာ diamond topup လုပ်လို့ မရပါ။\n\n"
            "***အကြောင်းရင်းများ***:\n"
            "***• Account suspended/banned ဖြစ်နေခြင်း***\n"
            "***• Invalid account pattern***\n"
            "***• MLBB မှ ပိတ်ပင်ထားခြင်း***\n\n"
            "🔄 ***အခြား account သုံးပြီး ထပ်ကြိုးစားကြည့်ပါ။***\n\n\n"
            "📞 ***ပြဿနာရှိရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )

        # Notify admin about banned account attempt
        admin_msg = (
            f"🚫 ***Banned Account Topup ကြိုးစားမှု***\n\n"
            f"👤 ***User:*** [{update.effective_user.first_name}](tg://user?id={user_id})\n\n"
            f"🆔 ***User ID:*** `{user_id}`\n"
            f"🎮 ***Game ID:*** `{game_id}`\n"
            f"🌐 ***Server ID:*** `{server_id}`\n"
            f"💎 ***Amount:*** {amount}\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "***⚠️ ဒီ account မှာ topup လုပ်လို့ မရပါ။***"
        )

        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        except:
            pass

        return

    price = get_price(amount)

    if not price:
        await update.message.reply_text(
            "❌ Diamond amount မှားနေပါတယ်!\n\n"
            "***ရရှိနိုင်တဲ့ amounts***:\n"
            "***• Weekly Pass:*** wp1-wp10\n\n"
            "***• Diamonds:*** 11, 22, 33, 56, 86, 112, 172, 257, 343, 429, 514, 600, 706, 878, 963, 1049, 1135, 1412, 2195, 3688, 5532, 9288, 12976",
            parse_mode="Markdown"
        )
        return

    data = load_data()
    user_balance = data["users"].get(user_id, {}).get("balance", 0)

    if user_balance < price:
        keyboard = [[InlineKeyboardButton("💳 ငွေဖြည့်မယ်", callback_data="topup_button")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"❌ ***လက်ကျန်ငွေ မလုံလောက်ပါ!***\n\n"
            f"💰 ***လိုအပ်တဲ့ငွေ***: {price:,} MMK\n"
            f"💳 ***သင့်လက်ကျန်***: {user_balance:,} MMK\n"
            f"❗ ***လိုအပ်သေးတာ***: {price - user_balance:,} MMK\n\n"
            "***ငွေဖြည့်ရန်*** `/topup amount` ***သုံးပါ။***",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return

    # Process order
    order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}"
    order = {
        "order_id": order_id,
        "game_id": game_id,
        "server_id": server_id,
        "amount": amount,
        "price": price,
        "status": "pending",
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "chat_id": update.effective_chat.id  # Store chat ID where order was placed
    }

    # Deduct balance
    data["users"][user_id]["balance"] -= price
    data["users"][user_id]["orders"].append(order)
    save_data(data)

    # Create confirm/cancel buttons for admin
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"order_confirm_{order_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"order_cancel_{order_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Get user name
    user_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()

    # Notify admin
    admin_msg = (
        f"🔔 ***အော်ဒါအသစ်ရောက်ပါပြီ!***\n\n"
        f"📝 ***Order ID:*** `{order_id}`\n"
        f"👤 ***User Name:*** [{user_name}](tg://user?id={user_id})\n\n"
        f"🆔 ***User ID:*** `{user_id}`\n"
        f"🎮 ***Game ID:*** `{game_id}`\n"
        f"🌐 ***Server ID:*** `{server_id}`\n"
        f"💎 ***Amount:*** {amount}\n"
        f"💰 ***Price:*** {price:,} MMK\n"
        f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 Status: ⏳ ***စောင့်ဆိုင်းနေသည်***"
    )

    # Send to all admins (with buttons for everyone)
    data = load_data()
    admin_list = data.get("admin_ids", [ADMIN_ID])
    for admin_id in admin_list:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_msg,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except:
            pass

    # Notify admin group (only if bot is admin in group)
    try:
        bot = Bot(token=BOT_TOKEN)
        if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
            group_msg = (
                f"🛒 ***အော်ဒါအသစ် ရောက်ပါပြီ!***\n\n"
                f"📝 ***Order ID:*** `{order_id}`\n"
                f"👤 ***User Name:*** [{user_name}](tg://user?id={user_id})\n"
                f"🎮 ***Game ID:*** `{game_id}`\n"
                f"🌐 ***Server ID:*** `{server_id}`\n"
                f"💎 ***Amount:*** {amount}\n"
                f"💰 ***Price:*** {price:,} MMK\n"
                f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📊 ***Status:*** ⏳ စောင့်ဆိုင်းနေသည်\n\n"
                f"#NewOrder #MLBB"
            )
            await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
    except Exception as e:
        pass

    await update.message.reply_text(
        f"✅ ***အော်ဒါ အောင်မြင်ပါပြီ!***\n\n"
        f"📝 ***Order ID:*** `{order_id}`\n"
        f"🎮 ***Game ID:*** `{game_id}`\n"
        f"🌐 ***Server ID:*** `{server_id}`\n"
        f"💎 ***Diamond:*** {amount}\n"
        f"💰 ***ကုန်ကျစရိတ်:*** {price:,} MMK\n"
        f"💳 ***လက်ကျန်ငွေ:*** {data['users'][user_id]['balance']:,} MMK\n"
        f"📊 Status: ⏳ ***စောင့်ဆိုင်းနေသည်***\n\n"
        "⚠️ ***Admin က confirm လုပ်ပြီးမှ diamonds များ ရရှိပါမယ်။***\n"
        "📞 ***ပြဿနာရှိရင် admin ကို ဆက်သွယ်ပါ။***",
        parse_mode="Markdown"
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check authorization
    load_authorized_users()
    if not is_user_authorized(user_id):
        keyboard = [[InlineKeyboardButton("👑 Contact Owner", url=f"tg://user?id={ADMIN_ID}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 အသုံးပြုခွင့် မရှိပါ!\n\n"
            "Owner ထံ bot အသုံးပြုခွင့် တောင်းဆိုပါ။",
            reply_markup=reply_markup
        )
        return

    # Check if user is restricted after screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await update.message.reply_text(
            "⏳ ***Screenshot ပို့ပြီးပါပြီ!***\n\n"
            "❌ ***Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ commands တွေ အသုံးပြုလို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n\n"
            "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Check if user has pending topup process
    if user_id in pending_topups:
        await update.message.reply_text(
            "⏳ ***Topup လုပ်ငန်းစဉ် ဆက်လက်လုပ်ဆောင်ပါ!***\n\n"
            "❌ ***လက်ရှိ topup လုပ်ငန်းစဉ်ကို မပြီးသေးပါ။***\n\n"
            "***လုပ်ရမည့်အရာများ***:\n"
            "***• Payment app ရွေးပြီး screenshot တင်ပါ***\n"
            "***• သို့မဟုတ် /cancel နှိပ်ပြီး ပယ်ဖျက်ပါ***\n\n"
            "💡 ***ပယ်ဖျက်ပြီးမှ အခြား commands များ အသုံးပြုနိုင်ပါမယ်။***",
            parse_mode="Markdown"
        )
        return

    # Check for pending topups in data (already submitted, waiting for approval)
    if await check_pending_topup(user_id):
        await send_pending_topup_warning(update)
        return

    data = load_data()
    user_data = data["users"].get(user_id)

    if not user_data:
        await update.message.reply_text("❌ အရင်ဆုံး /start နှိပ်ပါ။")
        return

    balance = user_data.get("balance", 0)
    total_orders = len(user_data.get("orders", []))
    total_topups = len(user_data.get("topups", []))

    # Check for pending topups
    pending_topups_count = 0
    pending_amount = 0

    for topup in user_data.get("topups", []):
        if topup.get("status") == "pending":
            pending_topups_count += 1
            pending_amount += topup.get("amount", 0)

    # Escape special characters in name and username
    name = user_data.get('name', 'Unknown')
    username = user_data.get('username', 'None')

    # Remove or escape problematic characters for Markdown
    name = name.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
    username = username.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')

    status_msg = ""
    if pending_topups_count > 0:
        status_msg = f"\n⏳ ***Pending Topups***: {pending_topups_count} ခု ({pending_amount:,} MMK)\n❗ ***Diamond order ထားလို့မရပါ။ Admin approve စောင့်ပါ။***"

    # Create inline keyboard with topup button
    keyboard = [[InlineKeyboardButton("💳 ငွေဖြည့်မယ်", callback_data="topup_button")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    balance_text = (
        f"💳 ***သင့်ရဲ့ Account အချက်အလက်များ***\n\n"
        f"💰 ***လက်ကျန်ငွေ***: `{balance:,} MMK`\n"
        f"📦 ***စုစုပေါင်း အော်ဒါများ***: {total_orders}\n"
        f"💳 ***စုစုပေါင်း ငွေဖြည့်မှုများ***: {total_topups}{status_msg}\n\n"
        f"***👤 နာမည်***: {name}\n"
        f"***🆔 Username***: @{username}"
    )

    # Try to get user's profile photo
    try:
        user_photos = await context.bot.get_user_profile_photos(user_id=int(user_id), limit=1)
        if user_photos.total_count > 0:
            # Send photo with balance info as caption
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=user_photos.photos[0][0].file_id,
                caption=balance_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            # No profile photo, send text only
            await update.message.reply_text(
                balance_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except:
        # If error getting photo, send text only
        await update.message.reply_text(
            balance_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

async def topup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check authorization
    load_authorized_users()
    if not is_user_authorized(user_id):
        keyboard = [[InlineKeyboardButton("👑 Contact Owner", url=f"tg://user?id={ADMIN_ID}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 အသုံးပြုခွင့် မရှိပါ!\n\n"
            "Owner ထံ bot အသုံးပြုခွင့် တောင်းဆိုပါ။",
            reply_markup=reply_markup
        )
        return

    # Check maintenance mode
    if not await check_maintenance_mode("topups"):
        await send_maintenance_message(update, "topups")
        return

    # Check if user is restricted after screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await update.message.reply_text(
            "⏳ ***Screenshot ပို့ပြီးပါပြီ!***\n\n"
            "❌ ***Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ commands တွေ အသုံးပြုလို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n\n"
            "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Check for pending topups first
    if await check_pending_topup(user_id):
        await send_pending_topup_warning(update)
        return

    # Check if user has pending topup process
    if user_id in pending_topups:
        await update.message.reply_text(
            "⏳ ***Topup လုပ်ငန်းစဉ် ဆက်လက်လုပ်ဆောင်ပါ!***\n\n"
            "❌ ***လက်ရှိ topup လုပ်ငန်းစဉ်ကို မပြီးသေးပါ။***\n\n"
            "***လုပ်ရမည့်အရာများ***:\n"
            "***• Payment app ရွေးပြီး screenshot တင်ပါ***\n"
            "***• သို့မဟုတ် /cancel နှိပ်ပြီး ပယ်ဖျက်ပါ***\n\n"
            "💡 ***ပယ်ဖျက်ပြီးမှ အသစ် topup လုပ်နိုင်ပါမယ်။***",
            parse_mode="Markdown"
        )
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ ***အမှားရှိပါတယ်!***\n\n"
            "***မှန်ကန်တဲ့ format***: `/topup <amount>`\n\n"
            "**ဥပမာ**:\n"
            "• `/topup 1000`\n"
            "• `/topup 5000`\n"
            "• `/topup 50000`\n\n"
            "💡 ***အနည်းဆုံး 1,000 MMK ဖြည့်ရပါမည်။***",
            parse_mode="Markdown"
        )
        return

    try:
        amount = int(args[0])
        if amount < 1000:
            await update.message.reply_text(
                "❌ ***ငွေပမာဏ နည်းလွန်းပါတယ်!***\n\n"
                "💰 ***အနည်းဆုံး 1,000 MMK ဖြည့်ရပါမည်။***",
                parse_mode="Markdown"
            )
            return
    except ValueError:
        await update.message.reply_text(
            "❌ ***ငွေပမာဏ မှားနေပါတယ်!***\n\n"
            "💰 ***ကိန်းဂဏန်းများသာ ရေးပါ။***\n\n"
            "***ဥပမာ***: `/topup 5000`",
            parse_mode="Markdown"
        )
        return

    # Store pending topup
    pending_topups[user_id] = {
        "amount": amount,
        "timestamp": datetime.now().isoformat()
    }

    # Show payment method selection
    keyboard = [
        [InlineKeyboardButton("📱 KBZ Pay", callback_data=f"topup_pay_kpay_{amount}")],
        [InlineKeyboardButton("📱 Wave Money", callback_data=f"topup_pay_wave_{amount}")],
        [InlineKeyboardButton("❌ ငြင်းပယ်မယ်", callback_data="topup_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
        f"***✅ ပမာဏ***: `{amount:,} MMK`\n\n"
        f"***အဆင့် 1***: Payment method ရွေးချယ်ပါ\n\n"
        f"***⬇️ ငွေလွှဲမည့် app ရွေးချယ်ပါ***:\n\n"
        f"***ℹ️ ပယ်ဖျက်ရန်*** /cancel ***နှိပ်ပါ***",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check authorization
    load_authorized_users()
    if not is_user_authorized(user_id):
        keyboard = [[InlineKeyboardButton("👑 Contact Owner", url=f"tg://user?id={ADMIN_ID}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 အသုံးပြုခွင့် မရှိပါ!\n\n"
            "Owner ထံ bot အသုံးပြုခွင့် တောင်းဆိုပါ။",
            reply_markup=reply_markup
        )
        return

    # Check if user is restricted after screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await update.message.reply_text(
            "⏳ ***Screenshot ပို့ပြီးပါပြီ!***\n\n"
            "❌ ***Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ commands တွေ အသုံးပြုလို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n"
            "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Check if user has pending topup process
    if user_id in pending_topups:
        await update.message.reply_text(
            "⏳ ***Topup လုပ်ငန်းစဉ် ဆက်လက်လုပ်ဆောင်ပါ!***\n\n"
            "❌ ***လက်ရှိ topup လုပ်ငန်းစဉ်ကို မပြီးသေးပါ။***\n\n"
            "***လုပ်ရမည့်အရာများ***:\n"
            "***• Payment app ရွေးပြီး screenshot တင်ပါ***\n"
            "***• သို့မဟုတ် /cancel နှိပ်ပြီး ပယ်ဖျက်ပါ***\n\n"
            "💡 ***ပယ်ဖျက်ပြီးမှ အခြား commands များ အသုံးပြုနိုင်ပါမယ်။***",
            parse_mode="Markdown"
        )
        return

    # Get custom prices
    custom_prices = load_prices()

    # Default prices
    default_prices = {
        # Weekly Pass
        "wp1": 6000, "wp2": 12000, "wp3": 18000, "wp4": 24000, "wp5": 30000,
        "wp6": 36000, "wp7": 42000, "wp8": 48000, "wp9": 54000, "wp10": 60000,
        # Regular Diamonds
        "11": 950, "22": 1900, "33": 2850, "56": 4200, "86": 5100, "112": 8200,
        "172": 10200, "257": 15300, "343": 20400, "429": 25500, "514": 30600,
        "600": 35700, "706": 40800, "878": 51000, "963": 56100, "1049": 61200,
        "1135": 66300, "1412": 81600, "2195": 122400, "3688": 204000,
        "5532": 306000, "9288": 510000, "12976": 714000,
        # 2X Diamond Pass
        "55": 3500, "165": 10000, "275": 16000, "565": 33000
    }

    # Merge custom prices with defaults (custom overrides default)
    current_prices = {**default_prices, **custom_prices}

    price_msg = "💎 ***MLBB Diamond ဈေးနှုန်းများ***\n\n"

    # Weekly Pass section
    price_msg += "🎟️ ***Weekly Pass***:\n"
    for i in range(1, 11):
        wp_key = f"wp{i}"
        if wp_key in current_prices:
            price_msg += f"• {wp_key} = {current_prices[wp_key]:,} MMK\n"
    price_msg += "\n"

    # Regular Diamonds section
    price_msg += "💎 ***Regular Diamonds***:\n"
    regular_diamonds = ["11", "22", "33", "56", "86", "112", "172", "257", "343",
                       "429", "514", "600", "706", "878", "963", "1049", "1135",
                       "1412", "2195", "3688", "5532", "9288", "12976"]

    for diamond in regular_diamonds:
        if diamond in current_prices:
            price_msg += f"• {diamond} = {current_prices[diamond]:,} MMK\n"
    price_msg += "\n"

    # 2X Diamond Pass section
    price_msg += "💎 ***2X Diamond Pass***:\n"
    double_pass = ["55", "165", "275", "565"]
    for dp in double_pass:
        if dp in current_prices:
            price_msg += f"• {dp} = {current_prices[dp]:,} MMK\n"
    price_msg += "\n"

    # Show any other custom items not in default categories
    other_customs = {k: v for k, v in custom_prices.items()
                    if k not in default_prices}
    if other_customs:
        price_msg += "🔥 ***Special Items***:\n"
        for item, price in other_customs.items():
            price_msg += f"• {item} = {price:,} MMK\n"
        price_msg += "\n"

    price_msg += (
        "***📝 အသုံးပြုနည်း***:\n"
        "`/mmb gameid serverid amount`\n\n"
        "***ဥပမာ***:\n"
        "`/mmb 123456789 12345 wp1`\n"
        "`/mmb 123456789 12345 86`"
    )

    await update.message.reply_text(price_msg, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check authorization
    load_authorized_users()
    if not is_user_authorized(user_id):
        return

    # Clear pending topup if exists
    if user_id in pending_topups:
        del pending_topups[user_id]
        await update.message.reply_text(
            "✅ ***ငွေဖြည့်ခြင်း ပယ်ဖျက်ပါပြီ!***\n\n"
            "💡 ***ပြန်ဖြည့်ချင်ရင်*** /topup ***နှိပ်ပါ။***",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "***ℹ️ လက်ရှိ ငွေဖြည့်မှု လုပ်ငန်းစဉ် မရှိပါ။***\n\n"
            "***💡 ငွေဖြည့်ရန် /topup ***နှိပ်ပါ။***",
            parse_mode="Markdown"
        )

async def c_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calculator command - /c <expression>"""
    import re

    user_id = str(update.effective_user.id)

    # Check if user is restricted after screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await update.message.reply_text(
            "❌ ***အသုံးပြုမှု ကန့်သတ်ထားပါ!***\n\n"
            "🔒 ***Screenshot ပို့ပြီးပါပြီ။ Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ:***\n\n"
            "❌ ***Calculator အပါအဝင် commands အသုံးပြုလို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***",
            parse_mode="Markdown"
        )
        return

    args = context.args

    if not args:
        await update.message.reply_text(
            "🧮 ***Calculator အသုံးပြုနည်း***\n\n"
            "***Format***: `/c <expression>`\n\n"
            "**ဥပမာ**:\n"
            "• `/c 2+2`\n"
            "• `/c 2 + 2`\n"
            "• `/c 100*5`\n"
            "• `/c 4-5+6`\n"
            "• `/c 100/4`\n\n"
            "**Operators**: `+`, `-`, `*`, `/`",
            parse_mode="Markdown"
        )
        return

    # Join all args and remove spaces
    expression = ''.join(args).replace(' ', '')

    # Validate expression contains only allowed characters
    pattern = r'^[0-9+\-*/().]+$'
    if not re.match(pattern, expression):
        await update.message.reply_text(
            "❌ ***မှားယွင်းသော expression! ဂဏန်းနဲ့ (+, -, *, /) ပဲ သုံးပါ။***",
            parse_mode="Markdown"
        )
        return

    # Must contain at least one operator
    if not any(op in expression for op in ['+', '-', '*', '/']):
        await update.message.reply_text(
            "❌ ***Operator မရှိပါ!*** (+, -, *, /) သုံးပါ။",
            parse_mode="Markdown"
        )
        return

    operators = {'+': 'ပေါင်းခြင်း', '-': 'နုတ်ခြင်း', '*': 'မြှောက်ခြင်း', '/': 'စားခြင်း'}
    operator_found = None
    for op in operators:
        if op in expression:
            operator_found = operators[op]
            break

    try:
        result = eval(expression)
        await update.message.reply_text(
            f"🧮 ***Calculator ရလဒ်***\n\n"
            f"📊 `{expression}` = ***{result:,}***\n\n"
            f"***⚙️ လုပ်ဆောင်ချက်***: {operator_found}",
            parse_mode="Markdown"
        )
    except ZeroDivisionError:
        await update.message.reply_text(
            "❌ ***သုညဖြင့် စားလို့ မရပါ!***",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text(
            "❌ မှားယွင်းသော expression!",
            parse_mode="Markdown"
        )

async def daily_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Daily report - /d YYYY-MM-DD or /d YYYY-MM-DD YYYY-MM-DD for range"""
    user_id = str(update.effective_user.id)

    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ ကြည့်နိုင်ပါတယ်!")
        return

    args = context.args
    data = load_data()

    if len(args) == 0:
        # Show date filter buttons
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        keyboard = [
            [InlineKeyboardButton("📅 ဒီနေ့", callback_data=f"report_day_{today.strftime('%Y-%m-%d')}")],
            [InlineKeyboardButton("📅 မနေ့က", callback_data=f"report_day_{yesterday.strftime('%Y-%m-%d')}")],
            [InlineKeyboardButton("📅 လွန်ခဲ့သော ၇ ရက်", callback_data=f"report_day_range_{week_ago.strftime('%Y-%m-%d')}_{today.strftime('%Y-%m-%d')}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📊 ***ရက်စွဲ ရွေးချယ်ပါ***\n\n"
            "***သို့မဟုတ် manual ရိုက်ပါ***:\n\n"
            "• `/d 2025-01-15` - သတ်မှတ်ရက်\n"
            "• `/d 2025-01-15 2025-01-20` - ရက်အပိုင်းအခြား",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return

    elif len(args) == 1:
        # Single date
        start_date = end_date = args[0]
        period_text = f"ရက် ({start_date})"
    elif len(args) == 2:
        # Date range
        start_date = args[0]
        end_date = args[1]
        period_text = f"ရက် ({start_date} မှ {end_date})"
    else:
        await update.message.reply_text(
            "❌ ***Format မှားနေပါတယ်!***\n\n"
            "***ဥပမာ***:\n"
            "• `/d` - Filter buttons\n"
            "• `/d 2025-01-15` - သတ်မှတ်ရက်\n"
            "• `/d 2025-01-15 2025-01-20` - ရက်အပိုင်းအခြား",
            parse_mode="Markdown"
        )
        return

    total_sales = 0
    total_orders = 0
    total_topups = 0
    topup_count = 0

    for user_data in data["users"].values():
        for order in user_data.get("orders", []):
            if order.get("status") == "confirmed":
                order_date = order.get("confirmed_at", order.get("timestamp", ""))[:10]
                if start_date <= order_date <= end_date:
                    total_sales += order["price"]
                    total_orders += 1

        for topup in user_data.get("topups", []):
            if topup.get("status") == "approved":
                topup_date = topup.get("approved_at", topup.get("timestamp", ""))[:10]
                if start_date <= topup_date <= end_date:
                    total_topups += topup["amount"]
                    topup_count += 1

    await update.message.reply_text(
        f"📊 ***ရောင်းရငွေ & ငွေဖြည့် မှတ်တမ်း***\n\n"
        f"📅 ကာလ: {period_text}\n\n"
        f"🛒 ***Order Confirmed စုစုပေါင်း***:\n"
        f"💰 ***ငွေ***: `{total_sales:,} MMK`\n"
        f"📦 ***အရေအတွက်***: {total_orders}\n\n"
        f"💳 ***Topup Approved စုစုပေါင်း***:\n"
        f"💰 ***ငွေ***: `{total_topups:,} MMK`\n"
        f"📦 ***အရေအတွက်***: {topup_count}",
        parse_mode="Markdown"
    )

async def monthly_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Monthly report - /m YYYY-MM or /m YYYY-MM YYYY-MM for range"""
    user_id = str(update.effective_user.id)

    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ ကြည့်နိုင်ပါတယ်!")
        return

    args = context.args
    data = load_data()

    if len(args) == 0:
        # Show month filter buttons
        today = datetime.now()
        this_month = today.strftime("%Y-%m")
        last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        three_months_ago = (today.replace(day=1) - timedelta(days=90)).strftime("%Y-%m")

        keyboard = [
            [InlineKeyboardButton("📅 ဒီလ", callback_data=f"report_month_{this_month}")],
            [InlineKeyboardButton("📅 ပြီးခဲ့သောလ", callback_data=f"report_month_{last_month}")],
            [InlineKeyboardButton("📅 လွန်ခဲ့သော ၃ လ", callback_data=f"report_month_range_{three_months_ago}_{this_month}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📊 ***လ ရွေးချယ်ပါ***\n\n"
            "***သို့မဟုတ် manual ရိုက်ပါ:***\n"
            "• `/m 2025-01` - သတ်မှတ်လ\n"
            "• `/m 2025-01 2025-03` - လအပိုင်းအခြား",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return

    elif len(args) == 1:
        # Single month
        start_month = end_month = args[0]
        period_text = f"လ ({start_month})"
    elif len(args) == 2:
        # Month range
        start_month = args[0]
        end_month = args[1]
        period_text = f"လ ({start_month} မှ {end_month})"
    else:
        await update.message.reply_text(
            "❌ ***Format မှားနေပါတယ်!***\n\n"
            "***ဥပမာ***:\n"
            "• `/m` - Filter buttons\n"
            "• `/m 2025-01` - သတ်မှတ်လ\n"
            "• `/m 2025-01 2025-03` - လအပိုင်းအခြား",
            parse_mode="Markdown"
        )
        return

    total_sales = 0
    total_orders = 0
    total_topups = 0
    topup_count = 0

    for user_data in data["users"].values():
        for order in user_data.get("orders", []):
            if order.get("status") == "confirmed":
                order_month = order.get("confirmed_at", order.get("timestamp", ""))[:7]
                if start_month <= order_month <= end_month:
                    total_sales += order["price"]
                    total_orders += 1
        for topup in user_data.get("topups", []):
            if topup.get("status") == "approved":
                topup_month = topup.get("approved_at", topup.get("timestamp", ""))[:7]
                if start_month <= topup_month <= end_month:
                    total_topups += topup["amount"]
                    topup_count += 1

    await update.message.reply_text(
        f"📊 ***ရောင်းရငွေ & ငွေဖြည့် မှတ်တမ်း***\n\n"
        f"📅 ကာလ: {period_text}\n\n"
        f"🛒 ***Order Confirmed စုစုပေါင်း***:\n"
        f"💰 ***ငွေ:*** `{total_sales:,} MMK`\n"
        f"📦 ***အရေအတွက်:*** {total_orders}\n\n"
        f"💳 ***Topup Approved စုစုပေါင်း***:\n"
        f"💰 ***ငွေ:*** `{total_topups:,} MMK`\n"
        f"📦 ***အရေအတွက်:*** {topup_count}",
        parse_mode="Markdown"
    )

async def yearly_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yearly report - /y YYYY or /y YYYY YYYY for range"""
    user_id = str(update.effective_user.id)

    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ ကြည့်နိုင်ပါတယ်!")
        return

    args = context.args
    data = load_data()

    if len(args) == 0:
        # Show year filter buttons
        today = datetime.now()
        this_year = today.strftime("%Y")
        last_year = str(int(this_year) - 1)

        keyboard = [
            [InlineKeyboardButton("📅 ဒီနှစ်", callback_data=f"report_year_{this_year}")],
            [InlineKeyboardButton("📅 ပြီးခဲ့သောနှစ်", callback_data=f"report_year_{last_year}")],
            [InlineKeyboardButton("📅 ၂ နှစ်စလုံး", callback_data=f"report_year_range_{last_year}_{this_year}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📊 ***နှစ် ရွေးချယ်ပါ***\n\n"
            "***သို့မဟုတ် manual ရိုက်ပါ:***\n"
            "• `/y 2025` - သတ်မှတ်နှစ်\n"
            "• `/y 2024 2025` - နှစ်အပိုင်းအခြား",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return

    elif len(args) == 1:
        # Single year
        start_year = end_year = args[0]
        period_text = f"နှစ် ({start_year})"
    elif len(args) == 2:
        # Year range
        start_year = args[0]
        end_year = args[1]
        period_text = f"နှစ် ({start_year} မှ {end_year})"
    else:
        await update.message.reply_text(
            "❌ Format မှားနေပါတယ်!\n\n"
            "***ဥပမာ***:\n"
            "• `/y` - Filter buttons\n"
            "• `/y 2025` - သတ်မှတ်နှစ်\n"
            "• `/y 2024 2025` - နှစ်အပိုင်းအခြား",
            parse_mode="Markdown"
        )
        return

    total_sales = 0
    total_orders = 0
    total_topups = 0
    topup_count = 0

    for user_data in data["users"].values():
        for order in user_data.get("orders", []):
            if order.get("status") == "confirmed":
                order_year = order.get("confirmed_at", order.get("timestamp", ""))[:4]
                if start_year <= order_year <= end_year:
                    total_sales += order["price"]
                    total_orders += 1
        for topup in user_data.get("topups", []):
            if topup.get("status") == "approved":
                topup_year = topup.get("approved_at", topup.get("timestamp", ""))[:4]
                if start_year <= topup_year <= end_year:
                    total_topups += topup["amount"]
                    topup_count += 1

    await update.message.reply_text(
        f"📊 ***ရောင်းရငွေ & ငွေဖြည့် မှတ်တမ်း***\n\n"
        f"📅 ကာလ: {period_text}\n\n"
        f"🛒 ***Order Confirmed စုစုပေါင်း***:\n"
        f"💰 ***ငွေ***: `{total_sales:,} MMK`\n"
        f"📦 ***အရေအတွက်***: {total_orders}\n\n"
        f"💳 ***Topup Approved စုစုပေါင်း***:\n"
        f"💰 ***ငွေ***: `{total_topups:,} MMK`\n"
        f"📦 ***အရေအတွက်***: {topup_count}",
        parse_mode="Markdown"
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check authorization
    load_authorized_users()
    if not is_user_authorized(user_id):
        keyboard = [[InlineKeyboardButton("👑 Contact Owner", url=f"tg://user?id={ADMIN_ID}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 အသုံးပြုခွင့် မရှိပါ!\n\n"
            "Owner ထံ bot အသုံးပြုခွင့် တောင်းဆိုပါ။",
            reply_markup=reply_markup
        )
        return

    # Check if user is restricted after screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await update.message.reply_text(
            "⏳ ***Screenshot ပို့ပြီးပါပြီ!***\n\n"
            "❌ ***Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ commands တွေ အသုံးပြုလို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n\n"
            "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Check if user has pending topup process
    if user_id in pending_topups:
        await update.message.reply_text(
            "⏳ ***Topup လုပ်ငန်းစဉ် ဆက်လက်လုပ်ဆောင်ပါ!***\n\n"
            "❌ ***လက်ရှိ topup လုပ်ငန်းစဉ်ကို မပြီးသေးပါ။***\n\n"
            "***လုပ်ရမည့်အရာများ***:\n"
            "***• Payment app ရွေးပြီး screenshot တင်ပါ***\n"
            "***• သို့မဟုတ် /cancel နှိပ်ပြီး ပယ်ဖျက်ပါ***\n\n"
            "💡 ***ပယ်ဖျက်ပြီးမှ အခြား commands များ အသုံးပြုနိုင်ပါမယ်။***",
            parse_mode="Markdown"
        )
        return

    # Check for pending topups in data (already submitted, waiting for approval)
    if await check_pending_topup(user_id):
        await send_pending_topup_warning(update)
        return

    data = load_data()
    user_data = data["users"].get(user_id)

    if not user_data:
        await update.message.reply_text("❌ အရင်ဆုံး /start နှိပ်ပါ။")
        return

    orders = user_data.get("orders", [])
    topups = user_data.get("topups", [])

    if not orders and not topups:
        await update.message.reply_text("📋 သင့်မှာ မည်သည့် မှတ်တမ်းမှ မရှိသေးပါ။")
        return

    msg = "📋 သင့်ရဲ့ မှတ်တမ်းများ\n\n"

    if orders:
        msg += "🛒 အော်ဒါများ (နောက်ဆုံး 5 ခု):\n"
        for order in orders[-5:]:
            status_emoji = "✅" if order.get("status") == "completed" else "⏳"
            msg += f"{status_emoji} {order['order_id']} - {order['amount']} ({order['price']:,} MMK)\n"
        msg += "\n"

    if topups:
        msg += "💳 ငွေဖြည့်များ (နောက်ဆုံး 5 ခု):\n"
        for topup in topups[-5:]:
            status_emoji = "✅" if topup.get("status") == "approved" else "⏳"
            msg += f"{status_emoji} {topup['amount']:,} MMK - {topup.get('timestamp', 'Unknown')[:10]}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")



async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ အမှားရှိပါတယ်!\n\n"
            "မှန်ကန်တဲ့ format: `/approve user_id amount`\n"
            "ဥပမာ: `/approve 123456789 50000`"
        )
        return

    try:
        target_user_id = args[0]
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ ငွေပမာဏမှားနေပါတယ်!")
        return

    data = load_data()

    if target_user_id not in data["users"]:
        await update.message.reply_text("❌ User မတွေ့ရှိပါ!")
        return

    # Add balance to user
    data["users"][target_user_id]["balance"] += amount

    # Update topup status
    topups = data["users"][target_user_id]["topups"]
    for topup in reversed(topups):
        if topup["status"] == "pending" and topup["amount"] == amount:
            topup["status"] = "approved"
            topup["approved_by"] = admin_name
            topup["approved_at"] = datetime.now().isoformat()
            break

    save_data(data)

    # Clear user restriction state after approval
    if target_user_id in user_states:
        del user_states[target_user_id]

    # Notify user
    try:
        user_balance = data['users'][target_user_id]['balance']

        # Create order button
        keyboard = [[InlineKeyboardButton("💎 Order တင်မယ်", url=f"https://t.me/{context.bot.username}?start=order")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=int(target_user_id),
            text=f"✅ ***ငွေဖြည့်မှု အတည်ပြုပါပြီ!*** 🎉\n\n"
                 f"💰 ***ပမာဏ:*** `{amount:,} MMK`\n"
                 f"💳 ***လက်ကျန်ငွေ:*** `{user_balance:,} MMK`\n"
                 f"👤 ***Approved by:*** [{admin_name}](tg://user?id={user_id})\n"
                 f"⏰ ***အချိန်:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                 f"🎉 ***ယခုအခါ diamonds များ ဝယ်ယူနိုင်ပါပြီ!***\n"
                 f"🔓 ***Bot လုပ်ဆောင်ချက်များ ပြန်လည် အသုံးပြုနိုင်ပါပြီ!***\n\n"
                 f"💎 ***Order တင်ရန်:***\n"
                 f"`/mmb gameid serverid amount`",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except:
        pass

    # Confirm to admin
    await update.message.reply_text(
        f"✅ ***Approve အောင်မြင်ပါပြီ!***\n\n"
        f"👤 ***User ID:*** `{target_user_id}`\n"
        f"💰 ***Amount:*** `{amount:,} MMK`\n"
        f"💳 ***User's new balance:*** `{data['users'][target_user_id]['balance']:,} MMK`\n"
        f"🔓 ***User restrictions cleared!***",
        parse_mode="Markdown"
    )

async def deduct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ အမှားရှိပါတယ်!\n\n"
            "မှန်ကန်တဲ့ format: `/deduct user_id amount`\n"
            "ဥပမာ: `/deduct 123456789 10000`"
        )
        return

    try:
        target_user_id = args[0]
        amount = int(args[1])
        if amount <= 0:
            await update.message.reply_text("❌ ငွေပမာဏသည် သုညထက် ကြီးရမည်!")
            return
    except ValueError:
        await update.message.reply_text("❌ ငွေပမာဏမှားနေပါတယ်!")
        return

    data = load_data()

    if target_user_id not in data["users"]:
        await update.message.reply_text("❌ User မတွေ့ရှိပါ!")
        return

    current_balance = data["users"][target_user_id]["balance"]

    if current_balance < amount:
        await update.message.reply_text(
            f"❌ ***နှုတ်လို့မရပါ!***\n\n"
            f"👤 User ID: `{target_user_id}`\n"
            f"💰 ***နှုတ်ချင်တဲ့ပမာဏ***: `{amount:,} MMK`\n"
            f"💳 ***User လက်ကျန်ငွေ***: `{current_balance:,} MMK`\n"
            f"❗ ***လိုအပ်သေးတာ***: `{amount - current_balance:,} MMK`",
            parse_mode="Markdown"
        )
        return

    # Deduct balance from user
    data["users"][target_user_id]["balance"] -= amount
    save_data(data)

    # Notify user
    try:
        user_msg = (
            f"⚠️ ***လက်ကျန်ငွေ နှုတ်ခံရမှု***\n\n"
            f"💰 ***နှုတ်ခံရတဲ့ပမာဏ***: `{amount:,} MMK`\n"
            f"💳 ***လက်ကျန်ငွေ***: `{data['users'][target_user_id]['balance']:,} MMK`\n"
            f"⏰ ***အချိန်***: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "📞 မေးခွန်းရှိရင် admin ကို ဆက်သွယ်ပါ။"
        )
        await context.bot.send_message(chat_id=int(target_user_id), text=user_msg, parse_mode="Markdown")
    except:
        pass

    # Confirm to admin
    await update.message.reply_text(
        f"✅ ***Balance နှုတ်ခြင်း အောင်မြင်ပါပြီ!***\n\n"
        f"👤 User ID: `{target_user_id}`\n"
        f"💰 ***နှုတ်ခဲ့တဲ့ပမာဏ***: `{amount:,} MMK`\n"
        f"💳 ***User လက်ကျန်ငွေ***: `{data['users'][target_user_id]['balance']:,} MMK`",
        parse_mode="Markdown"
    )

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("❌ မှန်ကန်တဲ့အတိုင်း: /done <user_id>")
        return

    target_user_id = int(args[0])
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text="🙏 ဝယ်ယူအားပေးမှုအတွက် ကျေးဇူးအများကြီးတင်ပါတယ်။\n\n✅ Order Done! 🎉"
        )
        await update.message.reply_text("✅ User ထံ message ပေးပြီးပါပြီ။")
    except:
        await update.message.reply_text("❌ User ID မှားနေပါတယ်။ Message မပို့နိုင်ပါ။")

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) < 2 or not args[0].isdigit():
        await update.message.reply_text("❌ မှန်ကန်တဲ့အတိုင်း: /reply <user_id> <message>")
        return

    target_user_id = int(args[0])
    message = " ".join(args[1:])
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=message
        )
        await update.message.reply_text("✅ Message ပေးပြီးပါပြီ။")
    except:
        await update.message.reply_text("❌ Message မပို့နိုင်ပါ။")

async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User registration request"""
    user_id = str(update.effective_user.id)
    user = update.effective_user
    username = user.username or "-"
    name = f"{user.first_name} {user.last_name or ''}".strip()

    # Escape special Markdown characters for username
    def escape_markdown(text):
        """Escape special characters for Markdown"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text

    username_escaped = escape_markdown(username)

    # Load authorized users
    load_authorized_users()

    # Check if already authorized
    if is_user_authorized(user_id):
        await update.message.reply_text(
            "✅ သင်သည် အသုံးပြုခွင့် ရပြီးသား ဖြစ်ပါတယ်!\n\n"
            "🚀 /start နှိပ်ပြီး bot ကို အသုံးပြုနိုင်ပါပြီ။",
            parse_mode="Markdown"
        )
        return

    # Send registration request to owner with approve button
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"register_approve_{user_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"register_reject_{user_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    owner_msg = (
        f"📝 ***Registration Request***\n\n"
        f"👤 ***User Name:*** [{name}](tg://user?id={user_id})\n"
        f"🆔 ***User ID:*** `{user_id}`\n"
        f"📱 ***Username:*** @{username_escaped}\n"
        f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"***အသုံးပြုခွင့် ပေးမလား?***"
    )

    user_confirm_msg = (
        f"✅ ***Registration တောင်းဆိုမှု ပို့ပြီးပါပြီ!***\n\n"
        f"👤 ***သင့်အမည်:*** {name}\n"
        f"🆔 ***သင့် User ID:*** `{user_id}`\n\n"
        f"⏳ ***Owner က approve လုပ်တဲ့အထိ စောင့်ပါ။***\n"
        f"📞 ***အရေးပေါ်ဆိုရင် owner ကို ဆက်သွယ်ပါ။***"
    )

    try:
        # Send to owner with user's profile photo
        try:
            user_photos = await context.bot.get_user_profile_photos(user_id=int(user_id), limit=1)
            if user_photos.total_count > 0:
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=user_photos.photos[0][0].file_id,
                    caption=owner_msg,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=owner_msg,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
        except:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=owner_msg,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except Exception as e:
        print(f"Error sending registration request to owner: {e}")

    # Send confirmation to user with their profile photo
    try:
        user_photos = await context.bot.get_user_profile_photos(user_id=int(user_id), limit=1)
        if user_photos.total_count > 0:
            await update.message.reply_photo(
                photo=user_photos.photos[0][0].file_id,
                caption=user_confirm_msg,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(user_confirm_msg, parse_mode="Markdown")
    except:
        await update.message.reply_text(user_confirm_msg, parse_mode="Markdown")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    admin_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()

    # Admin can ban
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("❌ မှန်ကန်တဲ့အတိုင်း: /ban <user\\_id>", parse_mode="Markdown")
        return

    target_user_id = args[0]
    load_authorized_users()

    if target_user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("ℹ️ User သည် authorize မလုပ်ထားပါ။")
        return

    AUTHORIZED_USERS.remove(target_user_id)
    save_authorized_users()

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text="🚫 Bot အသုံးပြုခွင့် ပိတ်ပင်ခံရမှု\n\n"
                 "❌ Admin က သင့်ကို ban လုပ်လိုက်ပါပြီ။\n\n"
                 "📞 အကြောင်းရင်း သိရှိရန် Admin ကို ဆက်သွယ်ပါ။",
            parse_mode="Markdown"
        )
    except:
        pass

    # Notify owner
    try:
        data = load_data()
        user_name = data["users"].get(target_user_id, {}).get("name", "Unknown")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚫 *User Ban Notification*\n\n"
                 f"👤 Admin: [{admin_name}](tg://user?id={user_id})\n"
                 f"🆔 Admin ID: `{user_id}`\n"
                 f"🎯 Banned User: [{user_name}](tg://user?id={target_user_id})\n"
                 f"🎯 Banned User ID: `{target_user_id}`\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="Markdown"
        )
    except:
        pass

    # Notify admin group
    try:
        bot = Bot(token=BOT_TOKEN)
        if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
            data = load_data()
            user_name = data["users"].get(target_user_id, {}).get("name", "Unknown")
            group_msg = (
                f"🚫 ***User Ban ဖြစ်ပါပြီ!***\n\n"
                f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                f"🆔 ***User ID:*** `{target_user_id}`\n"
                f"👤 ***Ban လုပ်သူ:*** {admin_name}\n"
                f"📊 ***Status:*** 🚫 Ban ဖြစ်ပြီး\n\n"
                f"#UserBanned"
            )
            await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
    except:
        pass

    await update.message.reply_text(
        f"✅ User Ban အောင်မြင်ပါပြီ!\n\n"
        f"👤 User ID: `{target_user_id}`\n"
        f"🎯 Status: Banned\n"
        f"📝 Total authorized users: {len(AUTHORIZED_USERS)}",
        parse_mode="Markdown"
    )

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    admin_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()

    # Admin can unban
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("❌ မှန်ကန်တဲ့အတိုင်း: /unban <user\\_id>", parse_mode="Markdown")
        return

    target_user_id = args[0]
    load_authorized_users()

    if target_user_id in AUTHORIZED_USERS:
        await update.message.reply_text("ℹ️ User သည် authorize ပြုလုပ်ထားပြီးပါပြီ။")
        return

    AUTHORIZED_USERS.add(target_user_id)
    save_authorized_users()

    # Clear any restrictions when unbanning
    if target_user_id in user_states:
        del user_states[target_user_id]

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text="🎉 *Bot အသုံးပြုခွင့် ပြန်လည်ရရှိပါပြီ!*\n\n"
                 "✅ Admin က သင့် ban ကို ဖြုတ်ပေးလိုက်ပါပြီ။\n\n"
                 "🚀 ယခုအခါ /start နှိပ်ပြီး bot ကို အသုံးပြုနိုင်ပါပြီ!",
            parse_mode="Markdown"
        )
    except:
        pass

    # Notify owner
    try:
        data = load_data()
        user_name = data["users"].get(target_user_id, {}).get("name", "Unknown")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"✅ *User Unban Notification*\n\n"
                 f"👤 Admin: [{admin_name}](tg://user?id={user_id})\n"
                 f"🆔 Admin ID: `{user_id}`\n"
                 f"🎯 Unbanned User: [{user_name}](tg://user?id={target_user_id})\n"
                 f"🎯 Unbanned User ID: `{target_user_id}`\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="Markdown"
        )
    except:
        pass

    # Notify admin group
    try:
        bot = Bot(token=BOT_TOKEN)
        if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
            data = load_data()
            user_name = data["users"].get(target_user_id, {}).get("name", "Unknown")
            group_msg = (
                f"✅ ***User Unban ဖြစ်ပါပြီ!***\n\n"
                f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                f"🆔 ***User ID:*** `{target_user_id}`\n"
                f"👤 ***Unban လုပ်သူ:*** {admin_name}\n"
                f"📊 ***Status:*** ✅ Unban ဖြစ်ပြီး\n\n"
                f"#UserUnbanned"
            )
            await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
    except:
        pass

    await update.message.reply_text(
        f"✅ User Unban အောင်မြင်ပါပြီ!\n\n"
        f"👤 User ID: `{target_user_id}`\n"
        f"🎯 Status: Unbanned\n"
        f"📝 Total authorized users: {len(AUTHORIZED_USERS)}",
        parse_mode="Markdown"
    )

async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့အတိုင်း: /maintenance <feature> <on/off>\n\n"
            "Features:\n"
            "• `orders` - အော်ဒါလုပ်ဆောင်ချက်\n"
            "• `topups` - ငွေဖြည့်လုပ်ဆောင်ချက်\n"
            "• `general` - ယေဘူယျ လုပ်ဆောင်ချက်\n\n"
            "ဥပမာ:\n"
            "• `/maintenance orders off`\n"
            "• `/maintenance topups on`"
        )
        return

    feature = args[0].lower()
    status = args[1].lower()

    if feature not in ["orders", "topups", "general"]:
        await update.message.reply_text("❌ Feature မှားနေပါတယ်! orders, topups, general ထဲမှ ရွေးပါ။")
        return

    if status not in ["on", "off"]:
        await update.message.reply_text("❌ Status မှားနေပါတယ်! on သို့မဟုတ် off ရွေးပါ။")
        return

    bot_maintenance[feature] = (status == "on")

    status_text = "🟢 ***ဖွင့်ထား***" if status == "on" else "🔴 ***ပိတ်ထား***"
    feature_text = {
        "orders": "***အော်ဒါလုပ်ဆောင်ချက်***",
        "topups": "***ငွေဖြည့်လုပ်ဆောင်ချက်***",
        "general": "***ယေဘူယျလုပ်ဆောင်ချက်***"
    }

    await update.message.reply_text(
        f"✅ ***Maintenance Mode ပြောင်းလဲပါပြီ!***\n\n"
        f"🔧 Feature: {feature_text[feature]}\n"
        f"📊 Status: {status_text}\n\n"
        f"***လက်ရှိ Maintenance Status:***\n"
        f"***• အော်ဒါများ:*** {'🟢 ***ဖွင့်ထား***' if bot_maintenance['orders'] else '🔴 ***ပိတ်ထား***'}\n"
        f"***• ငွေဖြည့်များ:*** {'🟢 ***ဖွင့်ထား***' if bot_maintenance['topups'] else '🔴 ***ပိတ်ထား***'}\n"
        f"***• ယေဘူယျ:*** {'🟢 ဖွင့်ထား' if bot_maintenance['general'] else '🔴 ***ပိတ်ထား***'}",
        parse_mode="Markdown"
    )

async def testgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test admin group connection"""
    user_id = str(update.effective_user.id)

    # Only admin can test
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    # Check bot admin status in group
    is_admin_in_group = await is_bot_admin_in_group(context.bot, ADMIN_GROUP_ID)

    # Try to send test message
    try:
        if is_admin_in_group:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=f"✅ **Test Notification**\n\n"
                     f"🔔 Bot ကနေ group ထဲကို message ပို့နိုင်ပါပြီ!\n"
                     f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                f"✅ **Group Test အောင်မြင်ပါပြီ!**\n\n"
                f"📱 Group ID: `{ADMIN_GROUP_ID}`\n"
                f"🤖 Bot Status: Admin ✅\n"
                f"📨 Test message ပို့ပြီးပါပြီ။ Group မှာ ကြည့်ပါ!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ **Group Connection Failed!**\n\n"
                f"📱 Group ID: `{ADMIN_GROUP_ID}`\n"
                f"🤖 Bot Status: Not Admin ❌\n\n"
                f"**ပြင်ဆင်ရန်:**\n"
                f"1️⃣ Group မှာ bot ကို add လုပ်ပါ\n"
                f"2️⃣ Bot ကို Administrator လုပ်ပါ\n"
                f"3️⃣ 'Post Messages' permission ပေးပါ",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error!**\n\n"
            f"📱 Group ID: `{ADMIN_GROUP_ID}`\n"
            f"⚠️ Error: `{str(e)}`\n\n"
            f"**ဖြစ်နိုင်တဲ့ အကြောင်းရင်းများ:**\n"
            f"• Bot ကို group မှာ မထည့်ထားသေး\n"
            f"• Group ID မှားနေတယ်\n"
            f"• Bot permission မလုံလောက်ဘူး",
            parse_mode="Markdown"
        )

async def setprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ ***မှန်ကန်တဲ့အတိုင်း***:\n\n"
            "***တစ်ခုချင်း***:\n"
            "• `/setprice <item> <price>`\n"
            "• `/setprice wp1 7000`\n"
            "• `/setprice 86 5500`\n\n"
            "***အစုလိုက် (Weekly Pass)***:\n"
            "• `/setprice wp1 7000` - wp1-wp10 အားလုံး auto update\n\n"
            "***အစုလိုက် (Normal Diamonds)***:\n"
            "• `/setprice normal 1000 2000 3000...` - သတ်မှတ်ဈေးများ\n"
            "• အစဉ်: 11,22,33,56,86,112,172,257,343,429,514,600,706,878,963,1049,1135,1412,2195,3688,5532,9288,12976\n\n"
            "***အစုလိုက် (2X Diamonds)***:\n"
            "• `/setprice 2x 3500 10000 16000 33000`\n"
            "• အစဉ်: 55,165,275,565",
            parse_mode="Markdown"
        )
        return

    custom_prices = load_prices()
    item = args[0].lower()

    # Handle batch updates
    if item == "normal":
        # Batch update for normal diamonds
        normal_diamonds = ["11", "22", "33", "56", "86", "112", "172", "257", "343",
                          "429", "514", "600", "706", "878", "963", "1049", "1135",
                          "1412", "2195", "3688", "5532", "9288", "12976"]
        
        if len(args) - 1 != len(normal_diamonds):
            await update.message.reply_text(
                f"❌ ***Normal diamonds {len(normal_diamonds)} ခု လိုအပ်ပါတယ်!***\n\n"
                f"***အစဉ်***: 11,22,33,56,86,112,172,257,343,429,514,600,706,878,963,1049,1135,1412,2195,3688,5532,9288,12976\n\n"
                f"***ဥပမာ***:\n"
                f"`/setprice normal 1000 2000 3000 4200 5100 8200 10200 15300 20400 25500 30600 35700 40800 51000 56100 61200 66300 81600 122400 204000 306000 510000 714000`",
                parse_mode="Markdown"
            )
            return
        
        updated_items = []
        try:
            for i, diamond in enumerate(normal_diamonds):
                price = int(args[i + 1])
                if price < 0:
                    await update.message.reply_text(f"❌ ဈေးနှုန်း ({diamond}) သုညထက် ကြီးရမည်!")
                    return
                custom_prices[diamond] = price
                updated_items.append(f"{diamond}={price:,}")
        except ValueError:
            await update.message.reply_text("❌ ဈေးနှုန်းများ ကိန်းဂဏန်းဖြင့် ထည့်ပါ!")
            return
        
        save_prices(custom_prices)
        await update.message.reply_text(
            f"✅ ***Normal Diamonds ဈေးနှုန်းများ ပြောင်းလဲပါပြီ!***\n\n"
            f"💎 ***Update လုပ်ပြီး***: {len(updated_items)} items\n\n"
            f"📝 Users တွေ /price ***နဲ့ အသစ်တွေ့မယ်။***",
            parse_mode="Markdown"
        )
        return

    elif item == "2x":
        # Batch update for 2X diamonds
        double_pass = ["55", "165", "275", "565"]
        
        if len(args) - 1 != len(double_pass):
            await update.message.reply_text(
                f"❌ ***2X diamonds {len(double_pass)} ခု လိုအပ်ပါတယ်!***\n\n"
                f"***အစဉ်***: 55,165,275,565\n\n"
                f"***ဥပမာ***:\n"
                f"`/setprice 2x 3500 10000 16000 33000`",
                parse_mode="Markdown"
            )
            return
        
        updated_items = []
        try:
            for i, diamond in enumerate(double_pass):
                price = int(args[i + 1])
                if price < 0:
                    await update.message.reply_text(f"❌ ဈေးနှုန်း ({diamond}) သုညထက် ကြီးရမည်!")
                    return
                custom_prices[diamond] = price
                updated_items.append(f"{diamond}={price:,}")
        except ValueError:
            await update.message.reply_text("❌ ဈေးနှုန်းများ ကိန်းဂဏန်းဖြင့် ထည့်ပါ!")
            return
        
        save_prices(custom_prices)
        await update.message.reply_text(
            f"✅ ***2X Diamonds ဈေးနှုန်းများ ပြောင်းလဲပါပြီ!***\n\n"
            f"💎 ***Update လုပ်ပြီး***: {len(updated_items)} items\n\n"
            f"📝 Users တွေ /price ***နဲ့ အသစ်တွေ့မယ်။***",
            parse_mode="Markdown"
        )
        return

    # Handle single item or weekly pass auto-update
    if len(args) != 2:
        await update.message.reply_text("❌ တစ်ခုချင်း update မှာ 2 arguments လိုပါတယ်!")
        return

    try:
        price = int(args[1])
        if price < 0:
            await update.message.reply_text("❌ ဈေးနှုန်း သုညထက် ကြီးရမည်!")
            return
    except ValueError:
        await update.message.reply_text("❌ ဈေးနှုန်း ကိန်းဂဏန်းဖြင့် ထည့်ပါ!")
        return

    # Check if it's a weekly pass (wp1-wp10)
    if item.startswith("wp") and len(item) > 2:
        try:
            wp_num = int(item[2:])
            if 1 <= wp_num <= 10:
                # Auto-update all weekly passes
                updated_items = []
                for i in range(1, 11):
                    wp_key = f"wp{i}"
                    wp_price = price * i
                    custom_prices[wp_key] = wp_price
                    updated_items.append(f"{wp_key}={wp_price:,}")
                
                save_prices(custom_prices)
                
                items_text = "\n".join([f"• {item}" for item in updated_items])
                await update.message.reply_text(
                    f"✅ ***Weekly Pass ဈေးနှုန်းများ Auto Update ပြီးပါပြီ!***\n\n"
                    f"💎 ***Base Price (wp1)***: `{price:,} MMK`\n\n"
                    f"***Updated Items***:\n{items_text}\n\n"
                    f"📝 Users တွေ /price ***နဲ့ အသစ်တွေ့မယ်။***",
                    parse_mode="Markdown"
                )
                return
        except ValueError:
            pass

    # Single item update
    custom_prices[item] = price
    save_prices(custom_prices)

    await update.message.reply_text(
        f"✅ ***ဈေးနှုန်း ပြောင်းလဲပါပြီ!***\n\n"
        f"💎 Item: `{item}`\n"
        f"💰 New Price: `{price:,} MMK`\n\n"
        f"📝 Users တွေ /price ***နဲ့ အသစ်တွေ့မယ်။***",
        parse_mode="Markdown"
    )

async def removeprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့အတိုင်း: /removeprice <item>\n\n"
            "ဥပမာ: `/removeprice wp1`"
        )
        return

    item = args[0]
    custom_prices = load_prices()

    if item not in custom_prices:
        await update.message.reply_text(f"❌ `{item}` မှာ custom price မရှိပါ!")
        return

    del custom_prices[item]
    save_prices(custom_prices)

    await update.message.reply_text(
        f"✅ ***Custom Price ဖျက်ပါပြီ!***\n\n"
        f"💎 Item: `{item}`\n"
        f"🔄 ***Default price ကို ပြန်သုံးပါမယ်။***",
        parse_mode="Markdown"
    )

async def setwavenum_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /setwavenum <phone_number>\n\n"
            "ဥပမာ: `/setwavenum 09123456789`"
        )
        return

    new_number = args[0]
    payment_info["wave_number"] = new_number

    await update.message.reply_text(
        f"✅ ***Wave နံပါတ် ပြောင်းလဲပါပြီ!***\n\n"
        f"📱 ***အသစ်:*** `{new_number}`\n\n"
        f"💳 ***လက်ရှိ Wave ငွေလွှဲ အချက်အလက်:***\n"
        f"📱 ***နံပါတ်:*** `{payment_info['wave_number']}`\n"
        f"👤 ***နာမည်***: {payment_info['wave_name']}",
        parse_mode="Markdown"
    )

async def setkpaynum_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /setkpaynum <phone_number>\n\n"
            "ဥပမာ: `/setkpaynum 09123456789`"
        )
        return

    new_number = args[0]
    payment_info["kpay_number"] = new_number

    await update.message.reply_text(
        f"✅ ***KPay နံပါတ် ပြောင်းလဲပါပြီ!***\n\n"
        f"📱 ***အသစ်:*** `{new_number}`\n\n"
        f"💳 ***လက်ရှိ KPay ငွေလွှဲ အချက်အလက်:***\n"
        f"📱 ***နံပါတ်:*** `{payment_info['kpay_number']}`\n"
        f"👤 နာမည်: {payment_info['kpay_name']}",
        parse_mode="Markdown"
    )

async def setwavename_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /setwavename <name>\n\n"
            "ဥပမာ: `/setwavename Ma Thidar Win`"
        )
        return

    new_name = " ".join(args)
    payment_info["wave_name"] = new_name

    await update.message.reply_text(
        f"✅ ***Wave နာမည် ပြောင်းလဲပါပြီ!***\n\n"
        f"👤 ***အသစ်:*** {new_name}\n\n"
        f"💳 ***လက်ရှိ Wave ငွေလွှဲ အချက်အလက်:***\n"
        f"📱 ***နံပါတ်:*** `{payment_info['wave_number']}`\n"
        f"👤 ***နာမည်:*** {payment_info['wave_name']}",
        parse_mode="Markdown"
    )

async def setkpayname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /setkpayname <name>\n\n"
            "ဥပမာ: `/setkpayname Ma Thidar Win`"
        )
        return

    new_name = " ".join(args)
    payment_info["kpay_name"] = new_name

    await update.message.reply_text(
        f"✅ ***KPay နံပါတ် ပြောင်းလဲပါပြီ!***\n\n"
        f"👤 ***အသစ်:*** {new_name}\n\n"
        f"💳 ***လက်ရှိ KPay ငွေလွှဲ အချက်အလက်:***\n"
        f"📱 ***နံပါတ်:*** `{payment_info['kpay_number']}`\n"
        f"👤 ***နာမည်:*** {payment_info['kpay_name']}",
        parse_mode="Markdown"
    )

async def setkpayqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can set payment QR
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ payment QR ထည့်နိုင်ပါတယ်!")
        return

    # Check if message is a reply to a photo
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "❌ ပုံကို reply လုပ်ပြီး /setkpayqr command သုံးပါ။\n\n"
            "အဆင့်များ:\n"
            "1. KPay QR code ပုံကို ပို့ပါ။\n"
            "2. ပုံကို reply လုပ်ပါ။\n"
            "3. /setkpayqr ရိုက်ပါ"
        )
        return

    photo = update.message.reply_to_message.photo[-1].file_id
    payment_info["kpay_image"] = photo

    await update.message.reply_text(
        "✅ KPay QR Code ထည့်သွင်းပြီးပါပြီ!\n\n"
        "📱 Users တွေ topup လုပ်တဲ့အခါ ဒီ QR code ကို မြင်ရပါမယ်။\n\n"
        "🗑️ ဖျက်ရန်: /removekpayqr",
        parse_mode="Markdown"
    )

async def removekpayqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can remove payment QR
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ payment QR ဖျက်နိုင်ပါတယ်!")
        return

    if not payment_info.get("kpay_image"):
        await update.message.reply_text("ℹ️ KPay QR code မရှိသေးပါ။")
        return

    payment_info["kpay_image"] = None

    await update.message.reply_text(
        "✅ KPay QR Code ဖျက်ပြီးပါပြီ!\n\n"
        "📝 Users တွေ number သာ မြင်ရပါမယ်။",
        parse_mode="Markdown"
    )

async def setwaveqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can set payment QR
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ payment QR ထည့်နိုင်ပါတယ်!")
        return

    # Check if message is a reply to a photo
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "❌ ပုံကို reply လုပ်ပြီး /setwaveqr command သုံးပါ။\n\n"
            "အဆင့်များ:\n"
            "1. Wave QR code ပုံကို ပို့ပါ။\n"
            "2. ပုံကို reply လုပ်ပါ။\n"
            "3. /setwaveqr ရိုက်ပါ"
        )
        return

    photo = update.message.reply_to_message.photo[-1].file_id
    payment_info["wave_image"] = photo

    await update.message.reply_text(
        "✅ Wave QR Code ထည့်သွင်းပြီးပါပြီ!\n\n"
        "📱 Users တွေ topup လုပ်တဲ့အခါ ဒီ QR code ကို မြင်ရပါမယ်။\n\n"
        "🗑️ ဖျက်ရန်: /removewaveqr",
        parse_mode="Markdown"
    )

async def removewaveqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can remove payment QR
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ payment QR ဖျက်နိုင်ပါတယ်!")
        return

    if not payment_info.get("wave_image"):
        await update.message.reply_text("ℹ️ Wave QR code မရှိသေးပါ။")
        return

    payment_info["wave_image"] = None

    await update.message.reply_text(
        "✅ Wave QR Code ဖျက်ပြီးပါပြီ!\n\n"
        "📝 Users တွေ number သာ မြင်ရပါမယ်။",
        parse_mode="Markdown"
    )


def is_owner(user_id):
    """Check if user is the owner"""
    return int(user_id) == ADMIN_ID

def is_admin(user_id):
    """Check if user is any admin (owner or appointed admin)"""
    # Owner is always admin
    if int(user_id) == ADMIN_ID:
        return True
    # Check other admins
    data = load_data()
    admin_list = data.get("admin_ids", [])
    return int(user_id) in admin_list

async def addadm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can add admins
    if not is_owner(user_id):
        await update.message.reply_text("❌ ***Owner သာ admin ခန့်အပ်နိုင်ပါတယ်!***")
        return

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /addadm <user_id>\n\n"
            "ဥပမာ: `/addadm 123456789`"
        )
        return

    new_admin_id = int(args[0])

    # Load data
    data = load_data()
    admin_list = data.get("admin_ids", [ADMIN_ID])

    if new_admin_id in admin_list:
        await update.message.reply_text("ℹ️ User သည် admin ဖြစ်နေပြီးပါပြီ။")
        return

    admin_list.append(new_admin_id)
    data["admin_ids"] = admin_list
    save_data(data)

    # Notify new admin
    try:
        await context.bot.send_message(
            chat_id=new_admin_id,
            text="🎉 Admin ရာထူးရရှိမှု\n\n"
                 "✅ Owner က သင့်ကို Admin အဖြစ် ခန့်အပ်ပါပြီ။\n\n"
                 "🔧 Admin commands များကို /adminhelp နှိပ်၍ ကြည့်နိုင်ပါတယ်။\n\n"
                 "⚠️ သတိပြုရန်:\n"
                 "• Admin အသစ် ခန့်အပ်လို့ မရပါ။\n"
                 "• Admin များကို ဖြုတ်လို့ မရပါ။\n"
                 "• ကျန်တဲ့ commands တွေ အသုံးပြုလို့ ရပါတယ်။"
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ ***Admin ထပ်မံထည့်သွင်းပါပြီ!***\n\n"
        f"👤 ***User ID:*** `{new_admin_id}`\n"
        f"🎯 ***Status:*** Admin\n"
        f"📝 ***Total admins:*** {len(admin_list)}",
        parse_mode="Markdown"
    )

async def unadm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can remove admins
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ admin ဖြုတ်နိုင်ပါတယ်!")
        return

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /unadm <user_id>\n\n"
            "ဥပမာ: `/unadm 123456789`"
        )
        return

    target_admin_id = int(args[0])

    # Cannot remove owner
    if target_admin_id == ADMIN_ID:
        await update.message.reply_text("❌ Owner ကို ဖြုတ်လို့ မရပါ!")
        return

    # Load data
    data = load_data()
    admin_list = data.get("admin_ids", [ADMIN_ID])

    if target_admin_id not in admin_list:
        await update.message.reply_text("ℹ️ User သည် admin မဟုတ်ပါ။")
        return

    admin_list.remove(target_admin_id)
    data["admin_ids"] = admin_list
    save_data(data)

    # Notify removed admin
    try:
        await context.bot.send_message(
            chat_id=target_admin_id,
            text="⚠️ Admin ရာထူး ရုပ်သိမ်းခံရမှု\n\n"
                 "❌ Owner က သင့်ရဲ့ admin ရာထူးကို ရုပ်သိမ်းလိုက်ပါပြီ။\n\n"
                 "📞 အကြောင်းရင်း သိရှိရန် Owner ကို ဆက်သွယ်ပါ။"
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ ***Admin ဖြုတ်ခြင်း အောင်မြင်ပါပြီ!***\n\n"
        f"👤 User ID: `{target_admin_id}`\n"
        f"🎯 Status: Removed from Admin\n"
        f"📝 Total admins: {len(admin_list)}",
        parse_mode="Markdown"
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can use broadcast
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ broadcast လုပ်နိုင်ပါတယ်!")
        return

    args = context.args

    # Check if reply to message exists
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ ***မှန်ကန်တဲ့ format:***\n\n"
            "***စာ သို့မဟုတ် ပုံကို reply လုပ်ပြီး:***\n"
            "• `/broadcast user gp` - ***Users နဲ့ Groups နှစ်ခုလုံး***\n"
            "• `/broadcast user` - ***Users သာ***\n"
            "• `/broadcast gp` - ***Groups သာ***\n\n"
            "***ဥပမာ:***\n"
            "• ***စာကို reply လုပ်ပြီး*** `/broadcast user gp`\n"
            "• ***ပုံကို reply လုပ်ပြီး*** `/broadcast user gp`",
            parse_mode="Markdown"
        )
        return

    # Parse targets
    if len(args) == 0:
        await update.message.reply_text(
            "❌ Target မရှိပါ!\n\n"
            "• `/broadcast user` - Users သာ\n"
            "• `/broadcast gp` - Groups သာ\n"
            "• `/broadcast user gp` - နှစ်ခုလုံး",
            parse_mode="Markdown"
        )
        return

    send_to_users = "user" in args
    send_to_groups = "gp" in args

    if not send_to_users and not send_to_groups:
        await update.message.reply_text(
            "❌ ***Target မှားနေပါတယ်!***\n\n"
            "• `user` - ***Users ကို ပို့မယ်။***\n"
            "• `gp` - ***Groups ကို ပို့မယ်။***\n"
            "• `user gp` - ***နှစ်ခုလုံး ပို့မယ်။***",
            parse_mode="Markdown"
        )
        return

    data = load_data()
    replied_msg = update.message.reply_to_message

    # Count successful sends
    user_success = 0
    user_fail = 0
    group_success = 0
    group_fail = 0

    # Check message type and broadcast accordingly
    if replied_msg.photo:
        # Photo with caption
        photo_file_id = replied_msg.photo[-1].file_id
        caption = replied_msg.caption or ""
        caption_entities = replied_msg.caption_entities or None

        # Send to users
        if send_to_users:
            for uid in data["users"].keys():
                try:
                    await context.bot.send_photo(
                        chat_id=int(uid),
                        photo=photo_file_id,
                        caption=caption,
                        caption_entities=caption_entities
                    )
                    user_success += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    print(f"Failed to send photo to user {uid}: {e}")
                    user_fail += 1

        # Send to groups
        if send_to_groups:
            group_chats = set()
            for uid, user_data in data["users"].items():
                for order in user_data.get("orders", []):
                    chat_id = order.get("chat_id")
                    if chat_id and chat_id < 0:
                        group_chats.add(chat_id)
                for topup in user_data.get("topups", []):
                    chat_id = topup.get("chat_id")
                    if chat_id and chat_id < 0:
                        group_chats.add(chat_id)

            for chat_id in group_chats:
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_file_id,
                        caption=caption,
                        caption_entities=caption_entities
                    )
                    group_success += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    print(f"Failed to send photo to group {chat_id}: {e}")
                    group_fail += 1

    elif replied_msg.text:
        # Text only
        message = replied_msg.text
        entities = replied_msg.entities or None

        # Send to users
        if send_to_users:
            for uid in data["users"].keys():
                try:
                    await context.bot.send_message(
                        chat_id=int(uid),
                        text=message,
                        entities=entities
                    )
                    user_success += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    print(f"Failed to send to user {uid}: {e}")
                    user_fail += 1

        # Send to groups
        if send_to_groups:
            group_chats = set()
            for uid, user_data in data["users"].items():
                for order in user_data.get("orders", []):
                    chat_id = order.get("chat_id")
                    if chat_id and chat_id < 0:
                        group_chats.add(chat_id)
                for topup in user_data.get("topups", []):
                    chat_id = topup.get("chat_id")
                    if chat_id and chat_id < 0:
                        group_chats.add(chat_id)

            for chat_id in group_chats:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        entities=entities
                    )
                    group_success += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    print(f"Failed to send to group {chat_id}: {e}")
                    group_fail += 1
    else:
        await update.message.reply_text(
            "❌ Text သို့မဟုတ် Photo သာ broadcast လုပ်နိုင်ပါတယ်!",
            parse_mode="Markdown"
        )
        return

    # Report results
    targets = []
    if send_to_users:
        targets.append(f"Users: {user_success} အောင်မြင်, {user_fail} မအောင်မြင်")
    if send_to_groups:
        targets.append(f"Groups: {group_success} အောင်မြင်, {group_fail} မအောင်မြင်")

    await update.message.reply_text(
        f"✅ Broadcast အောင်မြင်ပါပြီ!\n\n"
        f"👥 {chr(10).join(targets)}\n\n"
        f"📊 စုစုပေါင်း: {user_success + group_success} ပို့ပြီး",
        parse_mode="Markdown"
    )

async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ သင်သည် admin မဟုတ်ပါ!")
        return

    # Check if user is owner
    is_user_owner = is_owner(user_id)

    help_msg = "🔧 *Admin Commands List* 🔧\n\n"

    if is_user_owner:
        help_msg += (
            "👑 *Owner Commands:*\n"
            "• /addadm <user\\_id> - Admin ထပ်မံထည့်သွင်း\n"
            "• /unadm <user\\_id> - Admin ဖြုတ်ခြင်း\n"
            "• /ban <user\\_id> - User ban လုပ်\n"
            "• /unban <user\\_id> - User unban လုပ်\n\n"
        )

    help_msg += (
        "💰 *Balance Management:*\n"
        "• /approve <user\\_id> <amount> - Topup approve လုပ်\n"
        "• /deduct <user\\_id> <amount> - Balance နှုတ်ခြင်း\n\n"
        "💬 *Communication:*\n"
        "• /reply <user\\_id> <message> - User ကို message ပို့\n"
        "• /done <user\\_id> - Order complete message ပို့\n"
        "• /sendgroup <message> - Admin group ကို message ပို့\n"
        "• စာ/ပုံကို reply လုပ်ပြီး /broadcast user gp - Users နဲ့ Groups ပို့\n"
        "• စာ/ပုံကို reply လုပ်ပြီး /broadcast user - Users သာပို့\n"
        "• စာ/ပုံကို reply လုပ်ပြီး /broadcast gp - Groups သာပို့\n\n"
        "🔧 *Bot Maintenance:*\n"
        "• /maintenance <orders/topups/general> <on/off> - Features ဖွင့်ပိတ်\n\n"
        "💎 *Price Management:*\n"
        "• /setprice <item> <price> - Custom price ထည့်\n"
        "• /removeprice <item> - Custom price ဖျက်\n\n"
        "💳 *Payment Management:*\n"
        "• /setwavenum <number> - Wave နံပါတ် ပြောင်း\n"
        "• /setkpaynum <number> - KPay နံပါတ် ပြောင်း\n"
        "• /setwavename <name> - Wave နာမည် ပြောင်း\n"
        "• /setkpayname <name> - KPay နာမည် ပြောင်း\n\n"
    )

    if is_user_owner:
        help_msg += (
            "📱 *Payment QR Management (Owner Only):*\n"
            "• ပုံကို reply လုပ်ပြီး /setkpayqr - KPay QR ထည့်\n"
            "• /removekpayqr - KPay QR ဖျက်\n"
            "• ပုံကို reply လုပ်ပြီး /setwaveqr - Wave QR ထည့်\n"
            "• /removewaveqr - Wave QR ဖျက်\n\n"
        )

    help_msg += (
        "📊 *Current Status:*\n"
        f"• Orders: {'🟢 Enabled' if bot_maintenance['orders'] else '🔴 Disabled'}\n"
        f"• Topups: {'🟢 Enabled' if bot_maintenance['topups'] else '🔴 Disabled'}\n"
        f"• General: {'🟢 Enabled' if bot_maintenance['general'] else '🔴 Disabled'}\n"
        f"• Authorized Users: {len(AUTHORIZED_USERS)}\n\n"
        f"💳 *Current Payment Info:*\n"
        f"• Wave: {payment_info['wave_number']} ({payment_info['wave_name']})\n"
        f"• KPay: {payment_info['kpay_number']} ({payment_info['kpay_name']})"
    )

    await update.message.reply_text(help_msg, parse_mode="Markdown")

# Clone Bot Management
clone_bot_apps = {}
order_queue = asyncio.Queue()

def load_clone_bots():
    """Load clone bots from data file"""
    data = load_data()
    return data.get("clone_bots", {})

def save_clone_bot(bot_id, bot_data):
    """Save clone bot to data file"""
    data = load_data()
    if "clone_bots" not in data:
        data["clone_bots"] = {}
    data["clone_bots"][bot_id] = bot_data
    save_data(data)

def remove_clone_bot(bot_id):
    """Remove clone bot from data file"""
    data = load_data()
    if "clone_bots" in data and bot_id in data["clone_bots"]:
        del data["clone_bots"][bot_id]
        save_data(data)
        return True
    return False

async def addbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only admins can add bots
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin များသာ bot များထည့်နိုင်ပါတယ်!")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /addbot <bot_token>\n\n"
            "ဥပမာ: `/addbot 1234567890:ABCdefGHI...`\n\n"
            "💡 Bot token ကို @BotFather ဆီက ယူပါ။",
            parse_mode="Markdown"
        )
        return

    bot_token = args[0]

    # Verify bot token
    try:
        temp_bot = Bot(token=bot_token)
        bot_info = await temp_bot.get_me()
        bot_username = bot_info.username
        bot_id = str(bot_info.id)

        # Check if bot already exists
        clone_bots = load_clone_bots()
        if bot_id in clone_bots:
            await update.message.reply_text(
                f"ℹ️ ဒီ bot (@{bot_username}) ထည့်ပြီးသားပါ!"
            )
            return

        # Save clone bot
        bot_data = {
            "token": bot_token,
            "username": bot_username,
            "owner_id": user_id,  # Clone bot admin
            "balance": 0,
            "status": "active",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_clone_bot(bot_id, bot_data)

        # Start clone bot instance
        asyncio.create_task(run_clone_bot(bot_token, bot_id, user_id))

        await update.message.reply_text(
            f"✅ Bot ထပ်မံထည့်သွင်းပြီးပါပြီ!\n\n"
            f"🤖 Username: @{bot_username}\n"
            f"🆔 Bot ID: `{bot_id}`\n"
            f"👤 Admin: `{user_id}`\n"
            f"💰 Balance: 0 MMK\n"
            f"🟢 Status: Running\n\n"
            f"📝 Bot က အခု စတင်အလုပ်လုပ်နေပါပြီ။\n"
            f"💎 Orders များ main bot ဆီ ရောက်ရှိလာပါမယ်။",
            parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Bot token မှားနေပါတယ်!\n\n"
            f"Error: {str(e)}\n\n"
            f"💡 @BotFather ဆီက မှန်ကန်တဲ့ token ယူပါ။"
        )

async def listbots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin များသာ bot list ကြည့်နိုင်ပါတယ်!")
        return

    clone_bots = load_clone_bots()

    if not clone_bots:
        await update.message.reply_text("ℹ️ Clone bot များ မရှိသေးပါ။")
        return

    msg = "🤖 ***Clone Bots List***\n\n"

    for bot_id, bot_data in clone_bots.items():
        status_icon = "🟢" if bot_data.get("status") == "active" else "🔴"
        msg += (
            f"{status_icon} @{bot_data.get('username', 'Unknown')}\n"
            f"├ ID: `{bot_id}`\n"
            f"├ Admin: `{bot_data.get('owner_id', 'Unknown')}`\n"
            f"├ Balance: {bot_data.get('balance', 0):,} MMK\n"
            f"└ Created: {bot_data.get('created_at', 'Unknown')}\n\n"
        )

    msg += f"📊 စုစုပေါင်း: {len(clone_bots)} bots"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def removebot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can remove bots
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ bot များ ဖျက်နိုင်ပါတယ်!")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /removebot <bot_id>\n\n"
            "ဥပမာ: `/removebot 123456789`",
            parse_mode="Markdown"
        )
        return

    bot_id = args[0]

    # Remove bot
    if remove_clone_bot(bot_id):
        # Stop bot if running
        if bot_id in clone_bot_apps:
            try:
                await clone_bot_apps[bot_id].stop()
                del clone_bot_apps[bot_id]
            except:
                pass

        await update.message.reply_text(
            f"✅ Bot ဖျက်ပြီးပါပြီ!\n\n"
            f"🆔 Bot ID: `{bot_id}`\n"
            f"🔴 Bot က ရပ်သွားပါပြီ။",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Bot ID `{bot_id}` မတွေ့ပါ!",
            parse_mode="Markdown"
        )

async def addfund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can add funds to clone bots
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ clone bot များကို balance ဖြည့်နိုင်ပါတယ်!")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /addfund <admin_id> <amount>\n\n"
            "ဥပမာ: `/addfund 123456789 100000`\n\n"
            "💡 Clone bot admin ထံ balance ဖြည့်ပေးမည်။",
            parse_mode="Markdown"
        )
        return

    admin_id = args[0]
    try:
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount က ဂဏန်းဖြစ်ရမယ်!")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount က 0 ထက် ကြီးရမယ်!")
        return

    # Find clone bot by admin_id
    clone_bots = load_clone_bots()
    bot_found = None
    bot_id_found = None

    for bot_id, bot_data in clone_bots.items():
        if bot_data.get("owner_id") == admin_id:
            bot_found = bot_data
            bot_id_found = bot_id
            break

    if not bot_found:
        await update.message.reply_text(
            f"❌ Admin ID `{admin_id}` နဲ့ bot မတွေ့ပါ!",
            parse_mode="Markdown"
        )
        return

    # Add balance
    current_balance = bot_found.get("balance", 0)
    new_balance = current_balance + amount
    bot_found["balance"] = new_balance
    save_clone_bot(bot_id_found, bot_found)

    # Notify admin
    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"💰 Balance ဖြည့်သွင်းခြင်း\n\n"
                f"✅ Main owner က သင့် bot ထံ balance ဖြည့်ပေးပါပြီ!\n\n"
                f"📥 ဖြည့်သွင်းငွေ: `{amount:,} MMK`\n"
                f"💳 လက်ကျန်ငွေ: `{new_balance:,} MMK`\n\n"
                f"🤖 Bot: @{bot_found.get('username', 'Unknown')}\n"
                f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            parse_mode="Markdown"
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ Balance ဖြည့်ပြီးပါပြီ!\n\n"
        f"👤 Admin: `{admin_id}`\n"
        f"🤖 Bot: @{bot_found.get('username', 'Unknown')}\n"
        f"💰 ဖြည့်သွင်းငွေ: `{amount:,} MMK`\n"
        f"💳 လက်ကျန်ငွေ: `{new_balance:,} MMK`",
        parse_mode="Markdown"
    )

async def deductfund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Only owner can deduct funds from clone bots
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner သာ clone bot များ၏ balance နှုတ်နိုင်ပါတယ်!")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /deductfund <admin_id> <amount>\n\n"
            "ဥပမာ: `/deductfund 123456789 50000`\n\n"
            "💡 Clone bot admin ထံမှ balance နှုတ်မည်။",
            parse_mode="Markdown"
        )
        return

    admin_id = args[0]
    try:
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount က ဂဏန်းဖြစ်ရမယ်!")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount က 0 ထက် ကြီးရမယ်!")
        return

    # Find clone bot by admin_id
    clone_bots = load_clone_bots()
    bot_found = None
    bot_id_found = None

    for bot_id, bot_data in clone_bots.items():
        if bot_data.get("owner_id") == admin_id:
            bot_found = bot_data
            bot_id_found = bot_id
            break

    if not bot_found:
        await update.message.reply_text(
            f"❌ Admin ID `{admin_id}` နဲ့ bot မတွေ့ပါ!",
            parse_mode="Markdown"
        )
        return

    # Deduct balance
    current_balance = bot_found.get("balance", 0)
    if current_balance < amount:
        await update.message.reply_text(
            f"❌ Balance မလုံလောက်ပါ!\n\n"
            f"💳 လက်ကျန်ငွေ: `{current_balance:,} MMK`\n"
            f"📤 နှုတ်မည့်ငွေ: `{amount:,} MMK`",
            parse_mode="Markdown"
        )
        return

    new_balance = current_balance - amount
    bot_found["balance"] = new_balance
    save_clone_bot(bot_id_found, bot_found)

    # Notify admin
    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"💸 Balance နှုတ်ခြင်း\n\n"
                f"⚠️ Main owner က သင့် bot ထံမှ balance နှုတ်လိုက်ပါပြီ!\n\n"
                f"📤 နှုတ်သွားသော ငွေ: `{amount:,} MMK`\n"
                f"💳 လက်ကျန်ငွေ: `{new_balance:,} MMK`\n\n"
                f"🤖 Bot: @{bot_found.get('username', 'Unknown')}\n"
                f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            parse_mode="Markdown"
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ Balance နှုတ်ပြီးပါပြီ!\n\n"
        f"👤 Admin: `{admin_id}`\n"
        f"🤖 Bot: @{bot_found.get('username', 'Unknown')}\n"
        f"💸 နှုတ်သွားသော ငွေ: `{amount:,} MMK`\n"
        f"💳 လက်ကျန်ငွေ: `{new_balance:,} MMK`",
        parse_mode="Markdown"
    )



async def run_clone_bot(bot_token, bot_id, admin_id):
    """Run a clone bot instance within the existing event loop"""
    try:
        app = Application.builder().token(bot_token).build()

        # Add handlers for clone bot
        app.add_handler(CommandHandler("start", lambda u, c: clone_bot_start(u, c, admin_id)))
        app.add_handler(CommandHandler("mmb", lambda u, c: clone_bot_mmb(u, c, bot_id, admin_id)))
        app.add_handler(CallbackQueryHandler(lambda u, c: clone_bot_callback(u, c, bot_id, admin_id)))

        # Store app reference
        clone_bot_apps[bot_id] = app

        # Initialize and start bot (don't use run_polling - we're in an existing loop)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        print(f"✅ Clone bot {bot_id} started successfully")

    except Exception as e:
        print(f"❌ Clone bot {bot_id} failed to start: {e}")
        import traceback
        traceback.print_exc()

async def clone_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id):
    """Start command for clone bot"""
    user = update.effective_user

    await update.message.reply_text(
        f"👋 မင်္ဂလာပါ {user.first_name}!\n\n"
        f"🤖 JB MLBB AUTO TOP UP BOT မှ ကြိုဆိုပါတယ်!\n\n"
        f"💎 Diamond ဝယ်ယူရန်: /mmb gameid serverid amount\n"
        f"💰 ဈေးနှုန်းများ: /price\n\n"
        f"📞 Admin: `{admin_id}`",
        parse_mode="Markdown"
    )

async def clone_bot_mmb(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id, admin_id):
    """MMB command for clone bot - forward order to admin"""
    user = update.effective_user
    user_id = str(user.id)
    args = context.args

    if len(args) != 3:
        await update.message.reply_text(
            "❌ မှန်ကန်တဲ့ format: /mmb gameid serverid amount\n\n"
            "ဥပမာ: `/mmb 123456789 1234 56`",
            parse_mode="Markdown"
        )
        return

    game_id, server_id, diamonds = args

    # Validate inputs
    if not validate_game_id(game_id):
        await update.message.reply_text("❌ Game ID မမှန်ကန်ပါ! (6-10 ဂဏန်းများသာ)")
        return

    if not validate_server_id(server_id):
        await update.message.reply_text("❌ Server ID မမှန်ကန်ပါ! (3-5 ဂဏန်းများသာ)")
        return

    price = get_price(diamonds)
    if not price:
        await update.message.reply_text(f"❌ {diamonds} diamonds မရရှိနိုင်ပါ!")
        return

    # Send order to clone bot admin with 3 buttons
    order_data = {
        "bot_id": bot_id,
        "user_id": user_id,
        "username": user.username or user.first_name,
        "game_id": game_id,
        "server_id": server_id,
        "diamonds": diamonds,
        "price": price,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Create buttons for admin
    keyboard = [
        [
            InlineKeyboardButton("✅ လက်ခံမယ်", callback_data=f"clone_accept_{user_id}_{bot_id}"),
            InlineKeyboardButton("❌ ငြင်းမယ်", callback_data=f"clone_reject_{user_id}_{bot_id}")
        ],
        [
            InlineKeyboardButton("📦 Order တင်မယ်", callback_data=f"clone_order_{user_id}_{bot_id}_{game_id}_{server_id}_{diamonds}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send to clone bot admin
    try:
        bot = context.bot
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"📦 ***Clone Bot Order***\n\n"
                f"🤖 Bot: {bot_id}\n"
                f"👤 User: @{user.username or user.first_name} (`{user_id}`)\n"
                f"🎮 Game ID: `{game_id}`\n"
                f"🌐 Server ID: `{server_id}`\n"
                f"💎 Diamonds: {diamonds}\n"
                f"💰 Price: {price:,} MMK\n"
                f"⏰ Time: {order_data['timestamp']}"
            ),
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

        await update.message.reply_text(
            f"✅ Order ပို့ပြီးပါပြီ!\n\n"
            f"💎 Diamonds: {diamonds}\n"
            f"💰 Price: {price:,} MMK\n\n"
            f"⏰ Admin က confirm လုပ်တဲ့အထိ စောင့်ပါ။"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Order ပို့မရပါ: {str(e)}")

async def clone_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id, admin_id):
    """Handle callback queries from clone bot admin"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("clone_accept_"):
        # Admin accepts user order
        parts = data.split("_")
        user_id = parts[2]

        try:
            bot = context.bot
            await bot.send_message(
                chat_id=user_id,
                text="✅ သင့် order ကို လက်ခံလိုက်ပါပြီ!\n\n⏰ မကြာမီ diamonds ရောက်ရှိပါမယ်။"
            )
            await query.edit_message_text(
                f"{query.message.text}\n\n✅ ***User ကို လက်ခံကြောင်း အကြောင်းကြားပြီး***"
            )
        except:
            pass

    elif data.startswith("clone_reject_"):
        # Admin rejects user order
        parts = data.split("_")
        user_id = parts[2]

        try:
            bot = context.bot
            await bot.send_message(
                chat_id=user_id,
                text="❌ သင့် order ကို ငြင်းပယ်လိုက်ပါပြီ！\n\nအကြောင်းရင်း သိရှိရန် admin ကို ဆက်သွယ်ပါ။"
            )
            await query.edit_message_text(
                f"{query.message.text}\n\n❌ ***User ကို ငြင်းကြောင်း အကြောင်းကြားပြီး***"
            )
        except:
            pass

    elif data.startswith("clone_order_"):
        # Admin forwards order to main bot owner
        parts = data.split("_")
        user_id = parts[2]
        bot_id_from_data = parts[3]
        game_id = parts[4]
        server_id = parts[5]
        diamonds = parts[6]

        price = get_price(diamonds)

        # Forward to main bot owner (ADMIN_ID)
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"main_approve_{admin_id}_{game_id}_{server_id}_{diamonds}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"main_reject_{admin_id}")
            ],
            [
                InlineKeyboardButton("📦 Order တင်မယ်", callback_data=f"clone_order_{user_id}_{bot_id}_{game_id}_{server_id}_{diamonds}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            bot = context.bot
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"📦 ***Main Order Request***\n\n"
                    f"👤 Clone Bot Admin: `{admin_id}`\n"
                    f"🤖 Bot ID: {bot_id_from_data}\n"
                    f"👥 End User: `{user_id}`\n"
                    f"🎮 Game ID: `{game_id}`\n"
                    f"🌐 Server ID: `{server_id}`\n"
                    f"💎 Diamonds: {diamonds}\n"
                    f"💰 Price: {price:,} MMK\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                parse_mode="Markdown",
                reply_markup=reply_markup
            )

            await query.edit_message_text(
                f"{query.message.text}\n\n📤 ***Main bot owner ဆီ order ပို့ပြီး***"
            )
        except Exception as e:
            await query.edit_message_text(
                f"{query.message.text}\n\n❌ ***Order ပို့မရပါ: {str(e)}***"
            )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is authorized
    load_authorized_users()
    if not is_user_authorized(user_id):
        return

    # Validate if it's a payment screenshot
    if not is_payment_screenshot(update):
        await update.message.reply_text(
            "❌ ***သင့်ပုံ လက်မခံပါ!***\n\n"
            "🔍 ***Payment screenshot သာ လက်ခံပါတယ်။***\n"
            "💳 ***KPay, Wave လွှဲမှု screenshot များသာ တင်ပေးပါ။***\n\n"
            "📷 ***Payment app ရဲ့ transfer confirmation screenshot ကို တင်ပေးပါ။***",
            parse_mode="Markdown"
        )
        return

    if user_id not in pending_topups:
        await update.message.reply_text(
            "❌ ***Topup process မရှိပါ!***\n\n"
            "🔄 ***အရင်ဆုံး `/topup amount` command ကို သုံးပါ။***\n"
            "💡 ***ဥပမာ:*** `/topup 50000`",
            parse_mode="Markdown"
        )
        return

    pending = pending_topups[user_id]
    amount = pending["amount"]
    payment_method = pending.get("payment_method", "Unknown")

    # Check if payment method was selected
    if payment_method == "Unknown":
        await update.message.reply_text(
            "❌ ***Payment app ကို အရင်ရွေးပါ!***\n\n"
            "📱 ***KPay သို့မဟုတ် Wave ကို ရွေးချယ်ပြီးမှ screenshot တင်ပါ။***\n\n"
            "🔄 ***အဆင့်များ***:\n"
            "1. `/topup amount` နှိပ်ပါ\n"
            "2. ***Payment app ရွေးပါ (KPay/Wave)***\n"
            "3. ***Screenshot တင်ပါ***",
            parse_mode="Markdown"
        )
        return

    # Set user state to restricted
    user_states[user_id] = "waiting_approval"

    # Generate unique topup ID
    topup_id = f"TOP{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id[-4:]}"

    # Get user name
    user_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()

    # Notify admin about topup request with payment screenshot
    admin_msg = (
        f"💳 ***ငွေဖြည့်တောင်းဆိုမှု***\n\n"
        f"👤 User Name: [{user_name}](tg://user?id={user_id})\n"
        f"🆔 User ID: `{user_id}`\n"
        f"💰 Amount: `{amount:,} MMK`\n"
        f"📱 Payment: {payment_method.upper()}\n"
        f"🔖 Topup ID: `{topup_id}`\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 ***Status:*** ⏳ စောင့်ဆိုင်းနေသည်\n\n"
        f"***Screenshot စစ်ဆေးပြီး လုပ်ဆောင်ပါ။***"
    )

    # Create approve/reject buttons for admins
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"topup_approve_{topup_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"topup_reject_{topup_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Save topup request first with topup_id
    data = load_data()
    if user_id not in data["users"]:
        data["users"][user_id] = {"name": "", "username": "", "balance": 0, "orders": [], "topups": []}

    topup_request = {
        "topup_id": topup_id,
        "amount": amount,
        "payment_method": payment_method,
        "status": "pending",
        "timestamp": datetime.now().isoformat()
    }
    data["users"][user_id]["topups"].append(topup_request)
    save_data(data)

    # Get all admins
    data_load = load_data()
    admin_list = data_load.get("admin_ids", [ADMIN_ID])

    try:
        # Send to all admins - send payment screenshot with caption
        for admin_id in admin_list:
            try:
                # Send payment screenshot with admin message as caption
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=update.message.photo[-1].file_id,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            except:
                pass

        # Send to admin group - send payment screenshot with caption (only if bot is admin in group)
        try:
            if await is_bot_admin_in_group(context.bot, ADMIN_GROUP_ID):
                group_msg = (
                    f"💳 ***ငွေဖြည့်တောင်းဆိုမှု***\n\n"
                    f"👤 User Name: [{user_name}](tg://user?id={user_id})\n"
                    f"🆔 ***User ID:*** `{user_id}`\n"
                    f"💰 ***Amount:*** `{amount:,} MMK`\n"
                    f"📱 Payment: {payment_method.upper()}\n"
                    f"🔖 ***Topup ID:*** `{topup_id}`\n"
                    f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"📊 ***Status:*** ⏳ စောင့်ဆိုင်းနေသည်\n\n"
                    f"***Approve လုပ်ရန်:*** `/approve {user_id} {amount}`\n\n"
                    f"#TopupRequest #Payment"
                )
                # Use application's bot instead of creating new Bot instance
                await context.bot.send_photo(
                    chat_id=ADMIN_GROUP_ID,
                    photo=update.message.photo[-1].file_id,
                    caption=group_msg,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
        except Exception as e:
            pass
    except Exception as e:
        print(f"Error in topup process: {e}")

    del pending_topups[user_id]

    await update.message.reply_text(
        f"✅ ***Screenshot လက်ခံပါပြီ!***\n\n"
        f"💰 ***ပမာဏ:*** `{amount:,} MMK`\n"
        f"⏰ ***အချိန်:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "🔒 ***အသုံးပြုမှု ယာယီ ကန့်သတ်ပါ***\n"
        "❌ ***Screenshot ပို့ပြီးပါပြီ။ Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ:***\n\n"
        "❌ ***Commands အသုံးပြုလို့ မရပါ။***\n"
        "❌ ***စာသား ပို့လို့ မရပါ။***\n"
        "❌ ***Voice, Sticker, GIF, Video ပို့လို့ မရပါ။***\n"
        "❌ ***Emoji ပို့လို့ မရပါ။***\n\n"
        "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n"
        "📞 ***ပြဿနာရှိရင် admin ကို ဆက်သွယ်ပါ။***",
        parse_mode="Markdown"
    )

async def send_to_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Check if user is any admin
    if not is_admin(user_id):
        await update.message.reply_text("❌ ***သင်သည် admin မဟုတ်ပါ!***")
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ ***မှန်ကန်တဲ့အတိုင်း:*** /sendgroup <message>\n"
            "***ဥပမာ***: `/sendgroup Bot test လုပ်နေပါတယ်`"
        )
        return

    message = " ".join(args)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=f"📢 ***Admin Message***\n\n{message}",
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ ***Group ထဲကို message ပေးပြီးပါပြီ။***")
    except Exception as e:
        await update.message.reply_text(f"❌ ***Group ထဲကို message မပို့နိုင်ပါ။***\nError: {str(e)}")

async def notify_group_order(order_data, user_name, user_id):
    """Notify admin group about new order (only if bot is admin in group)"""
    try:
        bot = Bot(token=BOT_TOKEN)
        if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
            message = (
                f"🛒 ***အော်ဒါအသစ် ရောက်ပါပြီ!***\n\n"
                f"📝 ***Order ID:*** `{order_data['order_id']}`\n"
                f"👤 ***User Name:*** [{user_name}](tg://user?id={user_id})\n"
                f"🎮 ***Game ID:*** `{order_data['game_id']}`\n"
                f"🌐 ***Server ID:*** `{order_data['server_id']}`\n"
                f"💎 ***Amount:*** {order_data['amount']}\n"
                f"💰 ***Price:*** {order_data['price']:,} MMK\n"
                f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#NewOrder #MLBB"
            )
            await bot.send_message(chat_id=ADMIN_GROUP_ID, text=message, parse_mode="Markdown")
    except Exception as e:
        pass

async def notify_group_topup(topup_data, user_name, user_id):
    """Notify admin group about new topup request (only if bot is admin in group)"""
    try:
        bot = Bot(token=BOT_TOKEN)
        if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
            message = (
                f"💳 ***ငွေဖြည့်တောင်းဆိုမှု***\n\n"
                f"👤 ***User Name:*** [{user_name}](tg://user?id={user_id})\n"
                f"🆔 ***User ID:*** `{user_id}`\n"
                f"💰 ***Amount:*** `{topup_data['amount']:,} MMK`\n"
                f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"***Approve လုပ်ရန်:*** `/approve {user_id} {topup_data['amount']}`\n\n"
                f"#TopupRequest #Payment"
            )
            await bot.send_message(chat_id=ADMIN_GROUP_ID, text=message, parse_mode="Markdown")
    except Exception as e:
        pass

async def handle_restricted_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all non-command messages for restricted users"""
    user_id = str(update.effective_user.id)

    # Check if user is authorized first
    load_authorized_users()
    if not is_user_authorized(user_id):
        # For unauthorized users, give AI reply
        if update.message.text:
            reply = simple_reply(update.message.text)
            await update.message.reply_text(reply, parse_mode="Markdown")
        return

    # Check if user is restricted after sending screenshot
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        # Block everything except photos for restricted users
        if update.message.photo:
            await handle_photo(update, context)
            return

        # Block all other content types
        await update.message.reply_text(
            "❌ ***အသုံးပြုမှု ကန့်သတ်ထားပါ!***\n\n"
            "🔒 ***Screenshot ပို့ပြီးပါပြီ။ Admin က လက်ခံပြီးကြောင်း အတည်ပြုတဲ့အထိ:***\n\n"
            "❌ ***Commands အသုံးပြုလို့ မရပါ။***\n"
            "❌ ***စာသား ပို့လို့ မရပါ။***\n"
            "❌ ***Voice, Sticker, GIF, Video အသုံးပြုလို့ မရပါ။***\n"
            "❌ ***Emoji ပို့လို့ မရပါ။***\n\n"
            "⏰ ***Admin က approve လုပ်ပြီးမှ ပြန်လည် အသုံးပြုနိုင်ပါမယ်။***\n"
            "📞 ***အရေးပေါ်ဆိုရင် admin ကို ဆက်သွယ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # For authorized users - handle different message types
    if update.message.text:
        text = update.message.text.strip()
        # Provide simple auto-reply for text messages
        reply = simple_reply(text)
        await update.message.reply_text(reply, parse_mode="Markdown")

    # Handle sticker, voice, gif, video, audio, document, forward, poll
    else:
        await update.message.reply_text(
            "📱 ***MLBB Diamond Top-up Bot***\n\n"
            "💎 Diamond ဝယ်ယူရန် /mmb command သုံးပါ\n"
            "💰 ဈေးနှုန်းများ သိရှိရန် /price နှိပ်ပါ\n"
            "🆘 အကူအညီ လိုရင် /start နှိပ်ပါ",
            parse_mode="Markdown"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    admin_name = query.from_user.first_name or "Admin"

    # Handle payment method selection
    if query.data.startswith("topup_pay_"):
        parts = query.data.split("_")
        payment_method = parts[2]  # kpay or wave
        amount = int(parts[3])

        # Update pending topup with payment method
        if user_id in pending_topups:
            pending_topups[user_id]["payment_method"] = payment_method

        payment_name = "KBZ Pay" if payment_method == "kpay" else "Wave Money"
        payment_num = payment_info['kpay_number'] if payment_method == "kpay" else payment_info['wave_number']
        payment_acc_name = payment_info['kpay_name'] if payment_method == "kpay" else payment_info['wave_name']
        payment_qr = payment_info.get('kpay_image') if payment_method == "kpay" else payment_info.get('wave_image')

        # Send QR if available
        if payment_qr:
            try:
                await query.message.reply_photo(
                    photo=payment_qr,
                    caption=f"📱 **{payment_name} QR Code**\n\n"
                            f"📞 နံပါတ်: `{payment_num}`\n"
                            f"👤 နာမည်: {payment_acc_name}",
                    parse_mode="Markdown"
                )
            except:
                pass

        await query.edit_message_text(
            f"💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
            f"✅ ***ပမာဏ:*** `{amount:,} MMK`\n"
            f"✅ ***Payment:*** {payment_name}\n\n"
            f"***အဆင့် 3: ငွေလွှဲပြီး Screenshot တင်ပါ။***\n\n"
            f"📱 {payment_name}\n"
            f"📞 ***နံပါတ်:*** `{payment_num}`\n"
            f"👤 ***အမည်:*** {payment_acc_name}\n\n"
            f"⚠️ ***အရေးကြီးသော သတိပေးချက်:***\n"
            f"***ငွေလွှဲ note/remark မှာ သင့်ရဲ့ {payment_name} အကောင့်နာမည်ကို ရေးပေးပါ။***\n"
            f"***မရေးရင် ငွေဖြည့်မှု ငြင်းပယ်ခံရနိုင်ပါတယ်။***\n\n"
            f"💡 ***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n"
            f"⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***\n\n"
            f"ℹ️ ***ပယ်ဖျက်ရန် /cancel နှိပ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Handle registration request button
    elif query.data == "request_register":
        # Call register logic directly instead of command
        user = query.from_user
        user_id = str(user.id)
        username = user.username or "-"
        name = f"{user.first_name} {user.last_name or ''}".strip()

        # Load authorized users
        load_authorized_users()

        # Check if already authorized
        if is_user_authorized(user_id):
            await query.answer("✅ သင်သည် အသုံးပြုခွင့် ရပြီးသား ဖြစ်ပါတယ်!", show_alert=True)
            return

        # Send registration request to owner with approve button
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"register_approve_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"register_reject_{user_id}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        owner_msg = (
            f"📝 ***Registration Request***\n\n"
            f"👤 ***User Name:*** [{name}](tg://user?id={user_id})\n"
            f"🆔 ***User ID:*** `{user_id}`\n"
            f"📱 ***Username:*** @{username}\n"
            f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"***အသုံးပြုခွင့် ပေးမလား?***"
        )

        try:
            # Try to send user's profile photo first
            try:
                user_photos = await context.bot.get_user_profile_photos(user_id=int(user_id), limit=1)
                if user_photos.total_count > 0:
                    await context.bot.send_photo(
                        chat_id=ADMIN_ID,
                        photo=user_photos.photos[0][0].file_id,
                        caption=owner_msg,
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=owner_msg,
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
            except:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=owner_msg,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
        except Exception as e:
            print(f"Error sending registration request to owner: {e}")

        await query.answer("✅ Registration တောင်းဆိုမှု ပို့ပြီးပါပြီ!", show_alert=True)
        try:
            await query.edit_message_text(
                "✅ ***Registration တောင်းဆိုမှု ပို့ပြီးပါပြီ!***\n\n"
                "⏳ ***Owner က approve လုပ်တဲ့အထိ စောင့်ပါ။***\n"
                "📞 ***အရေးပေါ်ဆိုရင် owner ကို ဆက်သွယ်ပါ။***\n\n"
                f"🆔 ***သင့် User ID:*** `{user_id}`",
                parse_mode="Markdown"
            )
        except:
            pass
        return

    # Handle registration approve (admins can approve)
    elif query.data.startswith("register_approve_"):
        if not is_admin(user_id):
            await query.answer("❌ Admin များသာ registration approve လုပ်နိုင်ပါတယ်!", show_alert=True)
            return

        target_user_id = query.data.replace("register_approve_", "")
        load_authorized_users()

        if target_user_id in AUTHORIZED_USERS:
            await query.answer("ℹ️ User ကို approve လုပ်ပြီးပါပြီ!", show_alert=True)
            return

        AUTHORIZED_USERS.add(target_user_id)
        save_authorized_users()

        # Clear any restrictions
        if target_user_id in user_states:
            del user_states[target_user_id]

        # Remove buttons
        await query.edit_message_reply_markup(reply_markup=None)

        # Update message
        try:
            await query.edit_message_text(
                text=query.message.text + f"\n\n✅ Approved by {admin_name}",
                parse_mode="Markdown"
            )
        except:
            pass

        # Notify user
        try:
            data = load_data()
            user_name = data["users"].get(target_user_id, {}).get("name", "User")

            await context.bot.send_message(
                chat_id=int(target_user_id),
                text=f"🎉 Registration Approved!\n\n"
                     f"✅ Admin က သင့် registration ကို လက်ခံပါပြီ။\n\n"
                     f"🚀 ယခုအခါ /start နှိပ်ပြီး bot ကို အသုံးပြုနိုင်ပါပြီ!"
            )
        except:
            pass

        # Notify admin group
        try:
            bot = Bot(token=BOT_TOKEN)
            if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
                user_name = data["users"].get(target_user_id, {}).get("name", "Unknown")
                group_msg = (
                    f"✅ ***Registration လက်ခံပြီး!***\n\n"
                    f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                    f"🆔 ***User ID:*** `{target_user_id}`\n"
                    f"👤 ***လက်ခံသူ:*** {admin_name}\n"
                    f"📊 ***Status:*** ✅ လက်ခံပြီး\n\n"
                    f"#RegistrationApproved"
                )
                await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
        except:
            pass

        await query.answer("✅ User approved!", show_alert=True)
        return

    # Handle registration reject (admins can reject)
    elif query.data.startswith("register_reject_"):
        if not is_admin(user_id):
            await query.answer("❌ Admin များသာ registration reject လုပ်နိုင်ပါတယ်!", show_alert=True)
            return

        target_user_id = query.data.replace("register_reject_", "")

        # Remove buttons
        await query.edit_message_reply_markup(reply_markup=None)

        # Update message
        try:
            await query.edit_message_text(
                text=query.message.text + f"\n\n❌ Rejected by {admin_name}",
                parse_mode="Markdown"
            )
        except:
            pass

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=int(target_user_id),
                text="❌ Registration Rejected\n\n"
                     "Admin က သင့် registration ကို ငြင်းပယ်လိုက်ပါပြီ။\n\n"
                     "📞 အကြောင်းရင်း သိရှိရန် Admin ကို ဆက်သွယ်ပါ။\n\n"
            )
        except:
            pass

        # Notify admin group
        try:
            bot = Bot(token=BOT_TOKEN)
            if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
                data = load_data()
                user_name = data["users"].get(target_user_id, {}).get("name", "Unknown")
                group_msg = (
                    f"❌ ***Registration ငြင်းပယ်ပြီး!***\n\n"
                    f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                    f"🆔 ***User ID:*** `{target_user_id}`\n"
                    f"👤 ***ငြင်းပယ်သူ:*** {admin_name}\n"
                    f"📊 ***Status:*** ❌ ငြင်းပယ်ပြီး\n\n"
                    f"#RegistrationRejected"
                )
                await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
        except:
            pass

        await query.answer("❌ User rejected!", show_alert=True)
        return

    # Handle topup cancel
    elif query.data == "topup_cancel":
        if user_id in pending_topups:
            del pending_topups[user_id]

        await query.edit_message_text(
            "✅ ***ငွေဖြည့်ခြင်း ပယ်ဖျက်ပါပြီ!***\n\n"
            "💡 ***ပြန်ဖြည့်ချင်ရင်*** /topup ***နှိပ်ပါ။***",
            parse_mode="Markdown"
        )
        return

    # Handle topup approve/reject (one-time use)
    elif query.data.startswith("topup_approve_"):
        # Check if user is admin
        if not is_admin(user_id):
            await query.answer("❌ ***သင်သည် admin မဟုတ်ပါ!***")
            return

        topup_id = query.data.replace("topup_approve_", "")
        data = load_data()

        # Find and approve topup
        topup_found = False
        target_user_id = None
        topup_amount = 0

        for uid, user_data in data["users"].items():
            for topup in user_data.get("topups", []):
                if topup.get("topup_id") == topup_id and topup.get("status") == "pending":
                    topup["status"] = "approved"
                    topup["approved_by"] = admin_name
                    topup["approved_at"] = datetime.now().isoformat()
                    topup_amount = topup["amount"]
                    topup_found = True
                    target_user_id = uid

                    # Add balance to user
                    data["users"][uid]["balance"] += topup_amount

                    # Clear user restriction
                    if uid in user_states:
                        del user_states[uid]
                    break
            if topup_found:
                break

        if topup_found:
            save_data(data)

            # Remove buttons (one-time use)
            await query.edit_message_reply_markup(reply_markup=None)

            # Update message - handle both text and photo messages
            try:
                original_text = query.message.text or query.message.caption or ""
                updated_text = original_text.replace("pending", "approved") if original_text else "✅ Approved"
                updated_text += f"\n\n✅ Approved by: {admin_name}"

                if query.message.text:
                    await query.edit_message_text(
                        text=updated_text,
                        parse_mode="Markdown"
                    )
                elif query.message.caption:
                    await query.edit_message_caption(
                        caption=updated_text,
                        parse_mode="Markdown"
                    )
            except:
                pass

            # Notify user with order button
            try:
                user_balance = data['users'][target_user_id]['balance']

                # Create order button
                keyboard = [[InlineKeyboardButton("💎 Order တင်မယ်", url=f"https://t.me/{context.bot.username}?start=order")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await context.bot.send_message(
                    chat_id=int(target_user_id),
                    text=f"✅ ငွေဖြည့်မှု အတည်ပြုပါပြီ! 🎉\n\n"
                         f"💰 ပမာဏ: `{topup_amount:,} MMK`\n"
                         f"💳 လက်ကျန်ငွေ: `{user_balance:,} MMK`\n"
                         f"👤 Approved by: [{admin_name}](tg://user?id={user_id})\n"
                         f"⏰ အချိန်: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                         f"🎉 ယခုအခါ diamonds များ ဝယ်ယူနိုင်ပါပြီ!\n"
                         f"🔓 Bot လုပ်ဆောင်ချက်များ ပြန်လည် အသုံးပြုနိုင်ပါပြီ!\n\n"
                         f"💎 Order တင်ရန်:\n"
                         f"`/mmb gameid serverid amount`",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            except:
                pass

            # Notify all admins about approval
            admin_list = data.get("admin_ids", [ADMIN_ID])
            for admin_id in admin_list:
                if admin_id != int(user_id):  # Don't notify the admin who approved
                    try:
                        if admin_id == ADMIN_ID:
                            notification_msg = (
                                f"✅ ***Topup Approved!***\n\n"
                                f"🔖 ***Topup ID:*** `{topup_id}`\n"
                                f"👤 ***User Name:*** [{data['users'][target_user_id].get('name', 'Unknown')}](tg://user?id={target_user_id})\n"
                                f"🆔 ***User ID:*** `{target_user_id}`\n"
                                f"💰 ***Amount:*** `{topup_amount:,} MMK`\n"
                                f"💳 ***New Balance:*** `{data['users'][target_user_id]['balance']:,} MMK`\n"
                                f"👤 ***Approved by:*** {admin_name}\n"
                                f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                        else:
                            notification_msg = (
                                f"✅ ***Topup Approved!***\n\n"
                                f"🔖 ***Topup ID:*** `{topup_id}`\n"
                                f"👤 ***User Name:*** [{data['users'][target_user_id].get('name', 'Unknown')}](tg://user?id={target_user_id})\n"
                                f"💰 ***Amount:*** `{topup_amount:,} MMK`\n"
                                f"💳 ***New Balance:*** `{data['users'][target_user_id]['balance']:,} MMK`\n"
                                f"👤 ***Approved by:*** {admin_name}"
                            )
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=notification_msg,
                            parse_mode="Markdown"
                        )
                    except:
                        pass

            # Notify admin group about approval
            try:
                bot = Bot(token=BOT_TOKEN)
                if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
                    user_name = data['users'][target_user_id].get('name', 'Unknown')
                    group_msg = (
                        f"✅ ***Topup လက်ခံပြီး!***\n\n"
                        f"🔖 ***Topup ID:*** `{topup_id}`\n"
                        f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                        f"💰 ***Amount:*** `{topup_amount:,} MMK`\n"
                        f"💳 ***New Balance:*** `{data['users'][target_user_id]['balance']:,} MMK`\n"
                        f"👤 ***လက်ခံသူ:*** {admin_name}\n"
                        f"📊 ***Status:*** ✅ လက်ခံပြီး\n\n"
                        f"#TopupApproved"
                    )
                    await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
            except:
                pass

            await query.answer("✅ Topup approved!", show_alert=True)
        else:
            await query.answer("❌ Topup မတွေ့ရှိပါ သို့မဟုတ် လုပ်ဆောင်ပြီးပါပြီ!")
        return

    elif query.data.startswith("topup_reject_"):
        # Check if user is admin
        if not is_admin(user_id):
            await query.answer("❌ သင်သည် admin မဟုတ်ပါ!")
            return

        topup_id = query.data.replace("topup_reject_", "")
        data = load_data()

        # Find and reject topup
        topup_found = False
        target_user_id = None
        topup_amount = 0

        for uid, user_data in data["users"].items():
            for topup in user_data.get("topups", []):
                if topup.get("topup_id") == topup_id and topup.get("status") == "pending":
                    topup["status"] = "rejected"
                    topup["rejected_by"] = admin_name
                    topup["rejected_at"] = datetime.now().isoformat()
                    topup_amount = topup["amount"]
                    topup_found = True
                    target_user_id = uid

                    # Clear user restriction
                    if uid in user_states:
                        del user_states[uid]
                    break
            if topup_found:
                break

        if topup_found:
            save_data(data)

            # Remove buttons (one-time use)
            await query.edit_message_reply_markup(reply_markup=None)

            # Update message - handle both text and photo messages
            try:
                original_text = query.message.text or query.message.caption or ""
                updated_text = original_text.replace("pending", "rejected") if original_text else "❌ Rejected"
                updated_text += f"\n\n❌ Rejected by: {admin_name}"

                if query.message.text:
                    await query.edit_message_text(
                        text=updated_text,
                        parse_mode="Markdown"
                    )
                elif query.message.caption:
                    await query.edit_message_caption(
                        caption=updated_text,
                        parse_mode="Markdown"
                    )
            except:
                pass

            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=int(target_user_id),
                    text=f"❌ ***ငွေဖြည့်မှု ငြင်းပယ်ခံရပါပြီ!***\n\n"
                         f"💰 ***ပမာဏ:*** `{topup_amount:,} MMK`\n"
                         f"👤 ***Rejected by:*** {admin_name}\n"
                         f"⏰ ***အချိန်:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                         f"📞 ***အကြောင်းရင်း သိရှိရန် admin ကို ဆက်သွယ်ပါ။***\n"
                         f"💡 ***ပြန်လည် ငွေဖြည့်ရန် /topup နှိပ်ပါ။***\n"
                         f"🔓 ***Bot လုပ်ဆောင်ချက်များ ပြန်လည် အသုံးပြုနိုင်ပါပြီ!***",
                    parse_mode="Markdown"
                )
            except:
                pass

            # Notify all admins about rejection
            admin_list = data.get("admin_ids", [ADMIN_ID])
            for admin_id in admin_list:
                if admin_id != int(user_id):  # Don't notify the admin who rejected
                    try:
                        user_name = data['users'][target_user_id].get('name', 'Unknown')
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"❌ ***Topup Rejected!***\n\n"
                                 f"🔖 ***Topup ID:*** `{topup_id}`\n"
                                 f"👤 ***User Name:*** [{user_name}](tg://user?id={target_user_id})\n"
                                 f"🆔 ***User ID:*** `{target_user_id}`\n"
                                 f"💰 ***Amount:*** `{topup_amount:,} MMK`\n"
                                 f"👤 ***Rejected by:*** {admin_name}\n"
                                 f"⏰ ***Time:*** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            parse_mode="Markdown"
                        )
                    except:
                        pass

            # Notify admin group about rejection
            try:
                bot = Bot(token=BOT_TOKEN)
                if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
                    user_name = data['users'][target_user_id].get('name', 'Unknown')
                    group_msg = (
                        f"❌ ***Topup ငြင်းပယ်ပြီး!***\n\n"
                        f"🔖 ***Topup ID:*** `{topup_id}`\n"
                        f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                        f"💰 ***Amount:*** `{topup_amount:,} MMK`\n"
                        f"👤 ***ငြင်းပယ်သူ:*** {admin_name}\n"
                        f"📊 ***Status:*** ❌ ငြင်းပယ်ပြီး\n\n"
                        f"#TopupRejected"
                    )
                    await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
            except:
                pass

            await query.answer("❌ Topup rejected!", show_alert=True)
        else:
            await query.answer("❌ Topup မတွေ့ရှိပါ သို့မဟုတ် လုပ်ဆောင်ပြီးပါပြီ!")
        return

    # Handle order confirm/cancel
    if query.data.startswith("order_confirm_"):
        order_id = query.data.replace("order_confirm_", "")
        data = load_data()

        # Check if order already processed
        order_found = False
        target_user_id = None
        order_details = None

        for uid, user_data in data["users"].items():
            for order in user_data.get("orders", []):
                if order["order_id"] == order_id:
                    # Check if already processed
                    if order.get("status") in ["confirmed", "cancelled"]:
                        await query.answer("⚠️ Order ကို လုပ်ဆောင်ပြီးပါပြီ!", show_alert=True)
                        # Remove buttons from current message
                        try:
                            await query.edit_message_reply_markup(reply_markup=None)
                        except:
                            pass
                        return

                    order["status"] = "confirmed"
                    order["confirmed_by"] = admin_name
                    order["confirmed_at"] = datetime.now().isoformat()
                    order_found = True
                    target_user_id = uid
                    order_details = order
                    break
            if order_found:
                break

        if order_found:
            save_data(data)

            # Remove buttons from current admin's message
            try:
                await query.edit_message_text(
                    text=query.message.text.replace("⏳ စောင့်ဆိုင်းနေသည်", "✅ လက်ခံပြီး"),
                    parse_mode="Markdown",
                    reply_markup=None
                )
            except:
                pass

            # Notify all other admins and remove their buttons
            admin_list = data.get("admin_ids", [ADMIN_ID])
            for admin_id in admin_list:
                if admin_id != int(user_id):
                    try:
                        if admin_id == ADMIN_ID:
                            notification_msg = (
                                f"✅ ***Order Confirmed!***\n\n"
                                f"📝 ***Order ID:*** `{order_id}`\n"
                                f"👤 ***Confirmed by:*** {admin_name}\n"
                                f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                                f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                                f"💎 ***Amount:*** {order_details['amount']}\n"
                                f"💰 ***Price:*** {order_details['price']:,} MMK\n"
                                f"📊 Status: ✅ ***လက်ခံပြီး***"
                            )
                        else:
                            notification_msg = (
                                f"✅ ***Order Confirmed!***\n\n"
                                f"📝 ***Order ID:*** `{order_id}`\n"
                                f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                                f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                                f"💎 ***Amount:*** {order_details['amount']}\n"
                                f"💰 ***Price:*** {order_details['price']:,} MMK\n"
                                f"📊 Status: ✅ ***လက်ခံပြီး***"
                            )
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=notification_msg,
                            parse_mode="Markdown"
                        )
                    except:
                        pass

            # Notify admin group about confirmation
            try:
                bot = Bot(token=BOT_TOKEN)
                if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
                    user_name = data['users'][target_user_id].get('name', 'Unknown')
                    group_msg = (
                        f"✅ ***Order လက်ခံပြီး!***\n\n"
                        f"📝 ***Order ID:*** `{order_id}`\n"
                        f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                        f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                        f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                        f"💎 ***Amount:*** {order_details['amount']}\n"
                        f"💰 ***Price:*** {order_details['price']:,} MMK\n"
                        f"👤 ***လက်ခံသူ:*** {admin_name}\n"
                        f"📊 ***Status:*** ✅ လက်ခံပြီး\n\n"
                        f"#OrderConfirmed"
                    )
                    await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
            except:
                pass

            # Update status in the chat where order was placed
            try:
                chat_id = order_details.get("chat_id", int(target_user_id))
                user_name = data['users'][target_user_id].get('name', 'Unknown')
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ ***Order လက်ခံပြီးပါပြီ!***\n\n"
                         f"📝 ***Order ID:*** `{order_id}`\n"
                         f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                         f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                         f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                         f"💎 ***Amount:*** {order_details['amount']}\n"
                         f"📊 Status: ✅ ***လက်ခံပြီး***\n\n"
                         "💎 ***Diamonds များကို ထည့်သွင်းပေးလိုက်ပါပြီ။မိမိ၏ဂိမ်းအကောင့်အား Diamold များ မရောက်ပါက မိနစ်အနည်းငယ်အတွင်း Admin အကောင့်အားဆက်သွယ်ပေးပါ။***",
                    parse_mode="Markdown"
                )
            except:
                pass

            await query.answer("✅ Order လက်ခံပါပြီ!", show_alert=True)
        else:
            await query.answer("❌ Order မတွေ့ရှိပါ!", show_alert=True)
        return

    elif query.data.startswith("order_cancel_"):
        order_id = query.data.replace("order_cancel_", "")
        data = load_data()

        # Check if order already processed
        order_found = False
        target_user_id = None
        refund_amount = 0
        order_details = None

        for uid, user_data in data["users"].items():
            for order in user_data.get("orders", []):
                if order["order_id"] == order_id:
                    # Check if already processed
                    if order.get("status") in ["confirmed", "cancelled"]:
                        await query.answer("⚠️ Order ကို လုပ်ဆောင်ပြီးပါပြီ!", show_alert=True)
                        # Remove buttons from current message
                        try:
                            await query.edit_message_reply_markup(reply_markup=None)
                        except:
                            pass
                        return

                    order["status"] = "cancelled"
                    order["cancelled_by"] = admin_name
                    order["cancelled_at"] = datetime.now().isoformat()
                    refund_amount = order["price"]
                    order_found = True
                    target_user_id = uid
                    order_details = order
                    # Refund balance
                    data["users"][uid]["balance"] += refund_amount
                    break
            if order_found:
                break

        if order_found:
            save_data(data)

            # Remove buttons from current admin's message
            try:
                await query.edit_message_text(
                    text=query.message.text.replace("⏳ စောင့်ဆိုင်းနေသည်", "❌ ငြင်းပယ်ပြီး"),
                    parse_mode="Markdown",
                    reply_markup=None
                )
            except:
                pass

            # Notify all other admins and remove their buttons
            admin_list = data.get("admin_ids", [ADMIN_ID])
            for admin_id in admin_list:
                if admin_id != int(user_id):
                    try:
                        if admin_id == ADMIN_ID:
                            notification_msg = (
                                f"❌ ***Order Cancelled!***\n\n"
                                f"📝 ***Order ID:*** `{order_id}`\n"
                                f"👤 ***Cancelled by:*** {admin_name}\n"
                                f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                                f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                                f"💎 ***Amount:*** {order_details['amount']}\n"
                                f"💰 ***Refunded:*** {refund_amount:,} MMK\n"
                                f"📊 Status: ❌ ***ငြင်းပယ်ပြီး***"
                            )
                        else:
                            notification_msg = (
                                f"❌ ***Order Cancelled!***\n\n"
                                f"📝 ***Order ID:*** `{order_id}`\n"
                                f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                                f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                                f"💎 ***Amount:*** {order_details['amount']}\n"
                                f"💰 ***Refunded:*** {refund_amount:,} MMK\n"
                                f"📊 Status: ❌ ***ငြင်းပယ်ပြီး***"
                            )
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=notification_msg,
                            parse_mode="Markdown"
                        )
                    except:
                        pass

            # Notify admin group about cancellation
            try:
                bot = Bot(token=BOT_TOKEN)
                if await is_bot_admin_in_group(bot, ADMIN_GROUP_ID):
                    user_name = data['users'][target_user_id].get('name', 'Unknown')
                    group_msg = (
                        f"❌ ***Order ငြင်းပယ်ပြီး!***\n\n"
                        f"📝 ***Order ID:*** `{order_id}`\n"
                        f"👤 ***User:*** [{user_name}](tg://user?id={target_user_id})\n"
                        f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                        f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                        f"💎 ***Amount:*** {order_details['amount']}\n"
                        f"💰 ***Refunded:*** {refund_amount:,} MMK\n"
                        f"👤 ***ငြင်းပယ်သူ:*** {admin_name}\n"
                        f"📊 ***Status:*** ❌ ငြင်းပယ်ပြီး\n\n"
                        f"#OrderCancelled"
                    )
                    await bot.send_message(chat_id=ADMIN_GROUP_ID, text=group_msg, parse_mode="Markdown")
            except:
                pass

            # Update status in the chat where order was placed
            try:
                chat_id = order_details.get("chat_id", int(target_user_id))
                user_name = data['users'][target_user_id].get('name', 'Unknown')
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ ***Order ငြင်းပယ်ခံရပါပြီ!***\n\n"
                         f"📝 ***Order ID:*** `{order_id}`\n"
                         f"👤 ***User Name:*** [{user_name}](tg://user?id={target_user_id})\n"
                         f"🎮 ***Game ID:*** `{order_details['game_id']}`\n"
                         f"🌐 ***Server ID:*** `{order_details['server_id']}`\n"
                         f"💎 ***Amount:*** {order_details['amount']}\n"
                         f"📊 Status: ❌ ငြင်းပယ်ပြီး\n"
                         f"💰 ***ငွေပြန်အမ်း:*** {refund_amount:,} MMK\n\n"
                         "📞 ***အကြောင်းရင်း သိရှိရန် admin ကို ဆက်သွယ်ပါ။***",
                    parse_mode="Markdown"
                )
            except:
                pass

            await query.answer("❌ ***Order ငြင်းပယ်ပြီး ငွေပြန်အမ်းပါပြီ!**", show_alert=True)
        else:
            await query.answer("❌ Order မတွေ့ရှိပါ!", show_alert=True)
        return

    # Handle report filter callbacks
    elif query.data.startswith("report_day_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ ကြည့်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.replace("report_day_", "").split("_")
        if len(parts) == 1:
            # Single day
            start_date = end_date = parts[0]
            period_text = f"ရက် ({start_date})"
        else:
            # Range
            start_date = parts[1]
            end_date = parts[2]
            period_text = f"ရက် ({start_date} မှ {end_date})"

        data = load_data()
        total_sales = total_orders = total_topups = topup_count = 0

        for user_data in data["users"].values():
            for order in user_data.get("orders", []):
                if order.get("status") == "confirmed":
                    order_date = order.get("confirmed_at", order.get("timestamp", ""))[:10]
                    if start_date <= order_date <= end_date:
                        total_sales += order["price"]
                        total_orders += 1
            for topup in user_data.get("topups", []):
                if topup.get("status") == "approved":
                    topup_date = topup.get("approved_at", topup.get("timestamp", ""))[:10]
                    if start_date <= topup_date <= end_date:
                        total_topups += topup["amount"]
                        topup_count += 1

        await query.edit_message_text(
            f"📊 ***ရောင်းရငွေ & ငွေဖြည့် မှတ်တမ်း***\n\n"
            f"***📅 ကာလ:*** {period_text}\n\n"
            f"🛒 ***Order Confirmed စုစုပေါင်း***:\n"
            f"💰 ***ငွေ:*** `{total_sales:,} MMK`\n"
            f"📦 ***အရေအတွက်:*** {total_orders}\n\n"
            f"💳 ***Topup Approved စုစုပေါင်း***:\n"
            f"💰 ***ငွေ:*** `{total_topups:,} MMK`\n"
            f"📦 ***အရေအတွက်:*** {topup_count}",
            parse_mode="Markdown"
        )
        return

    elif query.data.startswith("report_month_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ ကြည့်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.replace("report_month_", "").split("_")
        if len(parts) == 1:
            # Single month
            start_month = end_month = parts[0]
            period_text = f"လ ({start_month})"
        else:
            # Range
            start_month = parts[1]
            end_month = parts[2]
            period_text = f"လ ({start_month} မှ {end_month})"

        data = load_data()
        total_sales = total_orders = total_topups = topup_count = 0

        for user_data in data["users"].values():
            for order in user_data.get("orders", []):
                if order.get("status") == "confirmed":
                    order_month = order.get("confirmed_at", order.get("timestamp", ""))[:7]
                    if start_month <= order_month <= end_month:
                        total_sales += order["price"]
                        total_orders += 1
            for topup in user_data.get("topups", []):
                if topup.get("status") == "approved":
                    topup_month = topup.get("approved_at", topup.get("timestamp", ""))[:7]
                    if start_month <= topup_month <= end_month:
                        total_topups += topup["amount"]
                        topup_count += 1

        await query.edit_message_text(
            f"📊 ***ရောင်းရငွေ & ငွေဖြည့် မှတ်တမ်း***\n\n"
            f"📅 ကာလ: {period_text}\n\n"
            f"🛒 ***Order Confirmed စုစုပေါင်း***:\n"
            f"💰 ***ငွေ:*** `{total_sales:,} MMK`\n"
            f"📦 ***အရေအတွက်:*** {total_orders}\n\n"
            f"💳 ***Topup Approved စုစုပေါင်း***:\n"
            f"💰 ***ငွေ:*** `{total_topups:,} MMK`\n"
            f"📦 ***အရေအတွက်:*** {topup_count}",
            parse_mode="Markdown"
        )
        return

    elif query.data.startswith("report_year_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ ကြည့်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.replace("report_year_", "").split("_")
        if len(parts) == 1:
            # Single year
            start_year = end_year = parts[0]
            period_text = f"နှစ် ({start_year})"
        else:
            # Range
            start_year = parts[1]
            end_year = parts[2]
            period_text = f"နှစ် ({start_year} မှ {end_year})"

        data = load_data()
        total_sales = total_orders = total_topups = topup_count = 0

        for user_data in data["users"].values():
            for order in user_data.get("orders", []):
                if order.get("status") == "confirmed":
                    order_year = order.get("confirmed_at", order.get("timestamp", ""))[:4]
                    if start_year <= order_year <= end_year:
                        total_sales += order["price"]
                        total_orders += 1
            for topup in user_data.get("topups", []):
                if topup.get("status") == "approved":
                    topup_year = topup.get("approved_at", topup.get("timestamp", ""))[:4]
                    if start_year <= topup_year <= end_year:
                        total_topups += topup["amount"]
                        topup_count += 1

        await query.edit_message_text(
            f"📊 ***ရောင်းရငွေ & ငွေဖြည့် မှတ်တမ်း***\n\n"
            f"📅 ကာလ: {period_text}\n\n"
            f"🛒 ***Order Confirmed စုစုပေါင်း***:\n"
            f"💰 ***ငွေ***: `{total_sales:,} MMK`\n"
            f"📦 ***အရေအတွက်***: {total_orders}\n\n"
            f"💳 ***Topup Approved စုစုပေါင်း***:\n"
            f"💰 ***ငွေ***: `{total_topups:,} MMK`\n"
            f"📦 ***အရေအတွက်***: {topup_count}",
            parse_mode="Markdown"
        )
        return

    # Check if user is restricted
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await query.answer("❌ Screenshot ပို့ပြီးပါပြီ! Admin approve စောင့်ပါ။", show_alert=True)
        return

    if query.data == "copy_kpay":
        await query.answer(f"📱 KPay Number copied! {payment_info['kpay_number']}", show_alert=True)
        await query.message.reply_text(
            "📱 ***KBZ Pay Number***\n\n"
            f"`{payment_info['kpay_number']}`\n\n"
            f"👤 Name: ***{payment_info['kpay_name']}***\n"
            "📋 ***Number ကို အပေါ်မှ copy လုပ်ပါ***",
            parse_mode="Markdown"
        )

    elif query.data == "copy_wave":
        await query.answer(f"📱 Wave Number copied! {payment_info['wave_number']}", show_alert=True)
        await query.message.reply_text(
            "📱 ***Wave Money Number***\n\n"
            f"`{payment_info['wave_number']}`\n\n"
            f"👤 Name: ***{payment_info['wave_name']}***\n"
            "📋 ***Number ကို အပေါ်မှ copy လုပ်ပါ***",
            parse_mode="Markdown"
        )

    elif query.data == "topup_button":
        try:
            keyboard = [
                [InlineKeyboardButton("📱 Copy KPay Number", callback_data="copy_kpay")],
                [InlineKeyboardButton("📱 Copy Wave Number", callback_data="copy_wave")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text="💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
                     "***အဆင့် 1: ငွေပမာဏ ရေးပါ***\n"
                     "`/topup amount` ဥပမာ: `/topup 50000`\n\n"
                     "***အဆင့် 2: ငွေလွှဲပါ***\n"
                     f"📱 ***KBZ Pay:*** `{payment_info['kpay_number']}` ({payment_info['kpay_name']})\n"
                     f"📱 ***Wave Money:*** `{payment_info['wave_number']}` ({payment_info['wave_name']})\n\n"
                     "***အဆင့် 3: Screenshot တင်ပါ***\n"
                     "***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n\n"
                     "⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            # If edit fails, send new message
            keyboard = [
                [InlineKeyboardButton("📱 Copy KPay Number", callback_data="copy_kpay")],
                [InlineKeyboardButton("📱 Copy Wave Number", callback_data="copy_wave")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.reply_text(
                text="💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
                     "***အဆင့် 1: ငွေပမာဏ ရေးပါ***\n"
                     "`/topup amount` ဥပမာ: `/topup 50000`\n\n"
                     "***အဆင့် 2: ငွေလွှဲပါ***\n"
                     f"📱 ***KBZ Pay:*** `{payment_info['kpay_number']}` ({payment_info['kpay_name']})\n"
                     f"📱 ***Wave Money:*** `{payment_info['wave_number']}` ({payment_info['wave_name']})\n\n"
                     "***အဆင့် 3: Screenshot တင်ပါ***\n"
                     "***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n\n"
                     "⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )

    # Handle main owner approve/reject clone bot orders
    elif query.data.startswith("main_approve_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ order approve လုပ်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.split("_")
        clone_admin_id = parts[2]
        game_id = parts[3]
        server_id = parts[4]
        diamonds = parts[5]

        price = get_price(diamonds)

        # Remove buttons
        await query.edit_message_reply_markup(reply_markup=None)

        # Update message
        try:
            await query.edit_message_text(
                f"{query.message.text}\n\n✅ ***Order Approved by Main Owner***",
                parse_mode="Markdown"
            )
        except:
            pass

        # Notify clone bot admin
        try:
            await context.bot.send_message(
                chat_id=clone_admin_id,
                text=(
                    f"✅ Order Approved!\n\n"
                    f"🎮 Game ID: `{game_id}`\n"
                    f"🌐 Server ID: `{server_id}`\n"
                    f"💎 Diamonds: {diamonds}\n"
                    f"💰 Price: {price:,} MMK\n\n"
                    f"📝 Main owner က approve လုပ်ပါပြီ။\n"
                    f"💎 Diamonds များကို user ထံ ပို့ပေးပါ။"
                ),
                parse_mode="Markdown"
            )
        except:
            pass

        await query.answer("✅ Order approved!", show_alert=True)
        return

    elif query.data.startswith("main_reject_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ order reject လုပ်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.split("_")
        clone_admin_id = parts[2]

        # Remove buttons
        await query.edit_message_reply_markup(reply_markup=None)

        # Update message
        try:
            await query.edit_message_text(
                f"{query.message.text}\n\n❌ ***Order Rejected by Main Owner***",
                parse_mode="Markdown"
            )
        except:
            pass

        # Notify clone bot admin
        try:
            await context.bot.send_message(
                chat_id=clone_admin_id,
                text="❌ Order Rejected!\n\nMain owner က order ကို ငြင်းပယ်လိုက်ပါပြီ။"
            )
        except:
            pass

        await query.answer("❌ Order rejected!", show_alert=True)
        return

    # Check if user is restricted
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await query.answer("❌ Screenshot ပို့ပြီးပါပြီ! Admin approve စောင့်ပါ။", show_alert=True)
        return

    if query.data == "copy_kpay":
        await query.answer(f"📱 KPay Number copied! {payment_info['kpay_number']}", show_alert=True)
        await query.message.reply_text(
            "📱 ***KBZ Pay Number***\n\n"
            f"`{payment_info['kpay_number']}`\n\n"
            f"👤 Name: ***{payment_info['kpay_name']}***\n"
            "📋 ***Number ကို အပေါ်မှ copy လုပ်ပါ***",
            parse_mode="Markdown"
        )

    elif query.data == "copy_wave":
        await query.answer(f"📱 Wave Number copied! {payment_info['wave_number']}", show_alert=True)
        await query.message.reply_text(
            "📱 ***Wave Money Number***\n\n"
            f"`{payment_info['wave_number']}`\n\n"
            f"👤 Name: ***{payment_info['wave_name']}***\n"
            "📋 ***Number ကို အပေါ်မှ copy လုပ်ပါ***",
            parse_mode="Markdown"
        )

    elif query.data == "topup_button":
        try:
            keyboard = [
                [InlineKeyboardButton("📱 Copy KPay Number", callback_data="copy_kpay")],
                [InlineKeyboardButton("📱 Copy Wave Number", callback_data="copy_wave")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text="💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
                     "***အဆင့် 1: ငွေပမာဏ ရေးပါ***\n"
                     "`/topup amount` ဥပမာ: `/topup 50000`\n\n"
                     "***အဆင့် 2: ငွေလွှဲပါ***\n"
                     f"📱 ***KBZ Pay:*** `{payment_info['kpay_number']}` ({payment_info['kpay_name']})\n"
                     f"📱 ***Wave Money:*** `{payment_info['wave_number']}` ({payment_info['wave_name']})\n\n"
                     "***အဆင့် 3: Screenshot တင်ပါ***\n"
                     "***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n\n"
                     "⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            # If edit fails, send new message
            keyboard = [
                [InlineKeyboardButton("📱 Copy KPay Number", callback_data="copy_kpay")],
                [InlineKeyboardButton("📱 Copy Wave Number", callback_data="copy_wave")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.reply_text(
                text="💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
                     "***အဆင့် 1: ငွေပမာဏ ရေးပါ***\n"
                     "`/topup amount` ဥပမာ: `/topup 50000`\n\n"
                     "***အဆင့် 2: ငွေလွှဲပါ***\n"
                     f"📱 ***KBZ Pay:*** `{payment_info['kpay_number']}` ({payment_info['kpay_name']})\n"
                     f"📱 ***Wave Money:*** `{payment_info['wave_number']}` ({payment_info['wave_name']})\n\n"
                     "***အဆင့် 3: Screenshot တင်ပါ***\n"
                     "***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n\n"
                     "⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )

    # Handle main owner approve/reject clone bot orders
    elif query.data.startswith("main_approve_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ order approve လုပ်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.split("_")
        clone_admin_id = parts[2]
        game_id = parts[3]
        server_id = parts[4]
        diamonds = parts[5]

        price = get_price(diamonds)

        # Remove buttons
        await query.edit_message_reply_markup(reply_markup=None)

        # Update message
        try:
            await query.edit_message_text(
                f"{query.message.text}\n\n✅ ***Order Approved by Main Owner***",
                parse_mode="Markdown"
            )
        except:
            pass

        # Notify clone bot admin
        try:
            await context.bot.send_message(
                chat_id=clone_admin_id,
                text=(
                    f"✅ Order Approved!\n\n"
                    f"🎮 Game ID: `{game_id}`\n"
                    f"🌐 Server ID: `{server_id}`\n"
                    f"💎 Diamonds: {diamonds}\n"
                    f"💰 Price: {price:,} MMK\n\n"
                    f"📝 Main owner က approve လုပ်ပါပြီ။\n"
                    f"💎 Diamonds များကို user ထံ ပို့ပေးပါ။"
                ),
                parse_mode="Markdown"
            )
        except:
            pass

        await query.answer("✅ Order approved!", show_alert=True)
        return

    elif query.data.startswith("main_reject_"):
        if not is_owner(user_id):
            await query.answer("❌ Owner သာ order reject လုပ်နိုင်ပါတယ်!", show_alert=True)
            return

        parts = query.data.split("_")
        clone_admin_id = parts[2]

        # Remove buttons
        await query.edit_message_reply_markup(reply_markup=None)

        # Update message
        try:
            await query.edit_message_text(
                f"{query.message.text}\n\n❌ ***Order Rejected by Main Owner***",
                parse_mode="Markdown"
            )
        except:
            pass

        # Notify clone bot admin
        try:
            await context.bot.send_message(
                chat_id=clone_admin_id,
                text="❌ Order Rejected!\n\nMain owner က order ကို ငြင်းပယ်လိုက်ပါပြီ။"
            )
        except:
            pass

        await query.answer("❌ Order rejected!", show_alert=True)
        return

    # Check if user is restricted
    if user_id in user_states and user_states[user_id] == "waiting_approval":
        await query.answer("❌ Screenshot ပို့ပြီးပါပြီ! Admin approve စောင့်ပါ။", show_alert=True)
        return

    if query.data == "copy_kpay":
        await query.answer(f"📱 KPay Number copied! {payment_info['kpay_number']}", show_alert=True)
        await query.message.reply_text(
            "📱 ***KBZ Pay Number***\n\n"
            f"`{payment_info['kpay_number']}`\n\n"
            f"👤 Name: ***{payment_info['kpay_name']}***\n"
            "📋 ***Number ကို အပေါ်မှ copy လုပ်ပါ***",
            parse_mode="Markdown"
        )

    elif query.data == "copy_wave":
        await query.answer(f"📱 Wave Number copied! {payment_info['wave_number']}", show_alert=True)
        await query.message.reply_text(
            "📱 ***Wave Money Number***\n\n"
            f"`{payment_info['wave_number']}`\n\n"
            f"👤 Name: ***{payment_info['wave_name']}***\n"
            "📋 ***Number ကို အပေါ်မှ copy လုပ်ပါ***",
            parse_mode="Markdown"
        )

    elif query.data == "topup_button":
        try:
            keyboard = [
                [InlineKeyboardButton("📱 Copy KPay Number", callback_data="copy_kpay")],
                [InlineKeyboardButton("📱 Copy Wave Number", callback_data="copy_wave")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text="💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
                     "***အဆင့် 1: ငွေပမာဏ ရေးပါ***\n"
                     "`/topup amount` ဥပမာ: `/topup 50000`\n\n"
                     "***အဆင့် 2: ငွေလွှဲပါ***\n"
                     f"📱 ***KBZ Pay:*** `{payment_info['kpay_number']}` ({payment_info['kpay_name']})\n"
                     f"📱 ***Wave Money:*** `{payment_info['wave_number']}` ({payment_info['wave_name']})\n\n"
                     "***အဆင့် 3: Screenshot တင်ပါ***\n"
                     "***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n\n"
                     "⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            # If edit fails, send new message
            keyboard = [
                [InlineKeyboardButton("📱 Copy KPay Number", callback_data="copy_kpay")],
                [InlineKeyboardButton("📱 Copy Wave Number", callback_data="copy_wave")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.reply_text(
                text="💳 ***ငွေဖြည့်လုပ်ငန်းစဉ်***\n\n"
                     "***အဆင့် 1: ငွေပမာဏ ရေးပါ***\n"
                     "`/topup amount` ဥပမာ: `/topup 50000`\n\n"
                     "***အဆင့် 2: ငွေလွှဲပါ***\n"
                     f"📱 ***KBZ Pay:*** `{payment_info['kpay_number']}` ({payment_info['kpay_name']})\n"
                     f"📱 ***Wave Money:*** `{payment_info['wave_number']}` ({payment_info['wave_name']})\n\n"
                     "***အဆင့် 3: Screenshot တင်ပါ***\n"
                     "***ငွေလွှဲပြီးရင် screenshot ကို ဒီမှာ တင်ပေးပါ။***\n\n"
                     "⏰ ***24 နာရီအတွင်း confirm လုပ်ပါမယ်။***",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )


async def post_init(application: Application):
    """Called after application initialization - start clone bots here"""
    clone_bots = load_clone_bots()
    for bot_id, bot_data in clone_bots.items():
        bot_token = bot_data.get("token")
        admin_id = bot_data.get("owner_id")
        if bot_token and admin_id:
            # Create task to run clone bot
            asyncio.create_task(run_clone_bot(bot_token, bot_id, admin_id))
            print(f"🔄 Starting clone bot {bot_id}...")

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN environment variable မရှိပါ!")
        return

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Load authorized users on startup
    load_authorized_users()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mmb", mmb_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("topup", topup_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("c", c_command))
    application.add_handler(CommandHandler("d", daily_report_command))
    application.add_handler(CommandHandler("m", monthly_report_command))
    application.add_handler(CommandHandler("y", yearly_report_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("history", history_command))


    # Admin commands
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("deduct", deduct_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("reply", reply_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("addadm", addadm_command))
    application.add_handler(CommandHandler("unadm", unadm_command))
    application.add_handler(CommandHandler("sendgroup", send_to_group_command))
    application.add_handler(CommandHandler("maintenance", maintenance_command))
    application.add_handler(CommandHandler("testgroup", testgroup_command))
    application.add_handler(CommandHandler("setprice", setprice_command))
    application.add_handler(CommandHandler("removeprice", removeprice_command))
    application.add_handler(CommandHandler("setwavenum", setwavenum_command))
    application.add_handler(CommandHandler("setkpaynum", setkpaynum_command))
    application.add_handler(CommandHandler("setwavename", setwavename_command))
    application.add_handler(CommandHandler("setkpayname", setkpayname_command))
    application.add_handler(CommandHandler("setkpayqr", setkpayqr_command))
    application.add_handler(CommandHandler("removekpayqr", removekpayqr_command))
    application.add_handler(CommandHandler("setwaveqr", setwaveqr_command))
    application.add_handler(CommandHandler("removewaveqr", removewaveqr_command))
    application.add_handler(CommandHandler("adminhelp", adminhelp_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))

    # Clone Bot Management commands
    application.add_handler(CommandHandler("addbot", addbot_command))
    application.add_handler(CommandHandler("listbots", listbots_command))
    application.add_handler(CommandHandler("removebot", removebot_command))
    application.add_handler(CommandHandler("addfund", addfund_command))
    application.add_handler(CommandHandler("deductfund", deductfund_command))

    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))

    # Photo handler (for payment screenshots)
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Handle all other message types (text, voice, sticker, video, etc.)
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.VOICE | filters.Sticker.ALL | filters.VIDEO |
         filters.ANIMATION | filters.AUDIO | filters.Document.ALL |
         filters.FORWARDED | filters.Entity("url") | filters.POLL) & ~filters.COMMAND,
        handle_restricted_content
    ))

    print("🤖 Bot စတင်နေပါသည် - 24/7 Running Mode")
    print("✅ Orders, Topups နဲ့ AI စလုံးအဆင်သင့်ပါ")
    print("🔧 Admin commands များ အသုံးပြုနိုင်ပါပြီ")

    # Run main bot
    application.run_polling()

if __name__ == "__main__":
    main()

