import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7638967663").split(",")]
GROUP_LINK = os.getenv("GROUP_LINK", "Ваша ссылка на канал")
