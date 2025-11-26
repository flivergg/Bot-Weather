import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, WEATHER_API_KEY, ADMIN_IDS, GROUP_LINK
from database import Database
from weather_service import WeatherService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

db = Database()
weather_service = WeatherService(WEATHER_API_KEY)

class WeatherStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_broadcast = State()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤️ Погода"), KeyboardButton(text="👕 Что надеть?")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="👥 Группа")]
        ],
        resize_keyboard=True
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("👋 Введите ваш город:")
    await state.set_state(WeatherStates.waiting_for_city)

@dp.message(WeatherStates.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    weather_data = weather_service.get_weather(city)
    
    if not weather_data:
        await message.answer("❌ Город не найден. Введите снова:")
        return
    
    db.add_user(message.from_user.id, city)
    await message.answer(f"✅ Город {weather_data['city']} установлен!", reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(F.text == "🌤️ Погода")
async def weather_today(message: types.Message):
    user_id = message.from_user.id
    city = db.get_user_city(user_id)
    
    if not city:
        await message.answer("❌ Сначала укажите город")
        return
    
    weather_data = weather_service.get_weather(city)
    
    if weather_data:
        message_text = (
            f"🌤️ Погода в {weather_data['city']}:\n"
            f"🌡️ {weather_data['temperature']}°C (ощущается {weather_data['feels_like']}°C)\n"
            f"📝 {weather_data['description']}\n"
            f"💧 Влажность: {weather_data['humidity']}%\n"
            f"💨 Ветер: {weather_data['wind_speed']:.1f} м/с"
        )
        await message.answer(message_text)
    else:
        await message.answer("❌ Ошибка получения погоды")

@dp.message(F.text == "👕 Что надеть?")
async def wardrobe_advice(message: types.Message):
    user_id = message.from_user.id
    city = db.get_user_city(user_id)
    
    if not city:
        await message.answer("❌ Сначала укажите город")
        return
    
    weather_data = weather_service.get_weather(city)
    
    if weather_data:
        recommendation = weather_service.get_wardrobe_recommendation(weather_data)
        await message.answer(f"👕 Рекомендации:\n{recommendation}")
    else:
        await message.answer("❌ Ошибка получения погоды")

@dp.message(F.text == "⚙️ Настройки")
async def notification_settings(message: types.Message):
    user_id = message.from_user.id
    current_status = db.get_notifications_status(user_id)
    status_text = "включены 🔔" if current_status else "выключены 🔕"
    
    await message.answer(f"Уведомления: {status_text}\n\nИспользуйте /toggle для переключения")

@dp.message(F.text == "👥 Группа")
async def group_invite(message: types.Message):
    await message.answer(f"👥 Наша группа: {GROUP_LINK}")

@dp.message(Command("toggle"))
async def toggle_notifications(message: types.Message):
    user_id = message.from_user.id
    new_status = db.toggle_notifications(user_id)
    status_text = "включены 🔔" if new_status else "выключены 🔕"
    await message.answer(f"Уведомления {status_text}")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("Админ панель\nИспользуйте /broadcast для рассылки")

@dp.message(Command("broadcast"))
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("Введите сообщение для рассылки:")
    await state.set_state(WeatherStates.waiting_for_broadcast)

@dp.message(WeatherStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = db.get_users_by_notification_time('07:00')
    
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 Рассылка:\n{message.text}")
            await asyncio.sleep(0.1)
        except Exception:
            continue
    
    await message.answer(f"✅ Рассылка завершена!")
    await state.clear()

async def send_daily_notifications():
    current_time = datetime.now().strftime("%H:%M")
    users = db.get_users_by_notification_time(current_time)
    
    for user_id, city in users:
        try:
            weather_data = weather_service.get_weather(city)
            if weather_data:
                await bot.send_message(user_id, f"🌅 Доброе утро! Погода: {weather_data['temperature']}°C")
        except Exception:
            continue

def setup_scheduler():
    scheduler.add_job(send_daily_notifications, 'interval', minutes=1)

async def main():
    logger.info("🚀 Starting Weather Bot...")
    setup_scheduler()
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
