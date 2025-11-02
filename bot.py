import asyncio
import logging
from datetime import datetime, time
from typing import Dict, Any, List
import sqlite3
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "8351803012:AAEWkO5AbndYnnWQ0gswwp4vFPSjQPI3qLU"
WEATHER_API_KEY = "e4b93ed98df342f2904201539252510"
ADMIN_IDS = [7638967663]  # Замени на свой Telegram ID
GROUP_LINK = "https://t.me/CodefProgress"  # Замени на ссылку своей группы

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

# Состояния FSM
class WeatherStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_broadcast = State()
    waiting_for_route_start = State()
    waiting_for_route_end = State()
    waiting_for_notification_time = State()

# База данных
class Database:
    def __init__(self, db_path="weather_bot.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    city TEXT,
                    latitude REAL,
                    longitude REAL,
                    notifications_enabled BOOLEAN DEFAULT TRUE,
                    notification_time TEXT DEFAULT '07:00',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def add_user(self, user_id: int, city: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, city, notifications_enabled, notification_time)
                VALUES (?, ?, TRUE, '07:00')
            ''', (user_id, city))
            conn.commit()

    def update_user_location(self, user_id: int, latitude: float, longitude: float, city: str = None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if city:
                cursor.execute('''
                    UPDATE users SET latitude = ?, longitude = ?, city = ? WHERE user_id = ?
                ''', (latitude, longitude, city, user_id))
            else:
                cursor.execute('''
                    UPDATE users SET latitude = ?, longitude = ? WHERE user_id = ?
                ''', (latitude, longitude, user_id))
            conn.commit()

    def get_user_city(self, user_id: int) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT city FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else None

    def get_user_location(self, user_id: int) -> tuple:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT latitude, longitude, city FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result if result else (None, None, None)

    def get_notifications_status(self, user_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notifications_enabled FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else True

    def toggle_notifications(self, user_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notifications_enabled FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            new_status = not result[0] if result else False
            
            cursor.execute('UPDATE users SET notifications_enabled = ? WHERE user_id = ?', (new_status, user_id))
            conn.commit()
            return new_status

    def update_notification_time(self, user_id: int, time_str: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET notification_time = ? WHERE user_id = ?', (time_str, user_id))
            conn.commit()

    def get_notification_time(self, user_id: int) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notification_time FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else '07:00'

    def get_users_by_notification_time(self, target_time: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, city FROM users 
                WHERE notifications_enabled = TRUE AND notification_time = ?
            ''', (target_time,))
            return cursor.fetchall()

    def get_all_users(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, city, notifications_enabled, notification_time FROM users')
            return cursor.fetchall()

# Сервис погоды
class WeatherService:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_weather(self, city: str) -> Dict[str, Any]:
        try:
            url = "http://api.weatherapi.com/v1/current.json"
            params = {
                'key': self.api_key,
                'q': city,
                'lang': 'ru'
            }
            response = requests.get(url, params=params)
            data = response.json()

            if response.status_code != 200:
                return None

            return {
                'city': data['location']['name'],
                'temperature': round(data['current']['temp_c']),
                'feels_like': round(data['current']['feelslike_c']),
                'description': data['current']['condition']['text'],
                'humidity': data['current']['humidity'],
                'pressure': data['current']['pressure_mb'],
                'wind_speed': data['current']['wind_kph'] / 3.6,
                'wind_dir': data['current']['wind_dir'],
                'condition_code': data['current']['condition']['code']
            }
        except Exception as e:
            logger.error(f"Weather API error: {e}")
            return None

    def get_weather_by_coords(self, lat: float, lon: float) -> Dict[str, Any]:
        try:
            url = "http://api.weatherapi.com/v1/current.json"
            params = {
                'key': self.api_key,
                'q': f"{lat},{lon}",
                'lang': 'ru'
            }
            response = requests.get(url, params=params)
            data = response.json()

            if response.status_code != 200:
                return None

            return {
                'city': data['location']['name'],
                'temperature': round(data['current']['temp_c']),
                'feels_like': round(data['current']['feelslike_c']),
                'description': data['current']['condition']['text'],
                'humidity': data['current']['humidity'],
                'pressure': data['current']['pressure_mb'],
                'wind_speed': data['current']['wind_kph'] / 3.6,
                'wind_dir': data['current']['wind_dir'],
                'condition_code': data['current']['condition']['code']
            }
        except Exception as e:
            logger.error(f"Weather API error: {e}")
            return None

    def get_forecast_3days(self, city: str) -> List[Dict[str, Any]]:
        try:
            url = "http://api.weatherapi.com/v1/forecast.json"
            params = {
                'key': self.api_key,
                'q': city,
                'days': 3,
                'lang': 'ru'
            }
            response = requests.get(url, params=params)
            data = response.json()

            if response.status_code != 200:
                return None

            forecast_days = []
            for day in data['forecast']['forecastday']:
                forecast_days.append({
                    'date': day['date'],
                    'max_temp': round(day['day']['maxtemp_c']),
                    'min_temp': round(day['day']['mintemp_c']),
                    'avg_temp': round(day['day']['avgtemp_c']),
                    'description': day['day']['condition']['text'],
                    'max_wind': day['day']['maxwind_kph'] / 3.6,
                    'avg_humidity': day['day']['avghumidity'],
                    'chance_of_rain': day['day']['daily_chance_of_rain'],
                    'chance_of_snow': day['day']['daily_chance_of_snow'],
                    'sunrise': day['astro']['sunrise'],
                    'sunset': day['astro']['sunset']
                })
            
            return forecast_days
        except Exception as e:
            logger.error(f"Weather API forecast error: {e}")
            return None

    def get_wardrobe_recommendation(self, weather_data: Dict[str, Any]) -> str:
        """Рекомендации по гардеробу на основе погоды"""
        temp = weather_data['temperature']
        description = weather_data['description'].lower()
        
        if temp >= 25:
            recommendation = "👕 Легкая одежда: футболка, шорты, сандалии\n🕶️ Не забудьте солнцезащитные очки!"
        elif temp >= 18:
            recommendation = "👔 Умеренная одежда: рубашка, джинсы, кроссовки\n🧥 Можно взять легкую куртку"
        elif temp >= 10:
            recommendation = "🧥 Теплая одежда: свитер, брюки, закрытая обувь\n🧣 Легкий шарф не помешает"
        elif temp >= 0:
            recommendation = "🧤 Зимняя одежда: пуховик, шапка, перчатки\n🥾 Теплая обувь обязательна"
        else:
            recommendation = "❄️ Сильно утепляйтесь: термобелье, зимняя куртка\n🎩 Обязательно шапка и шарф"
        
        # Дополнительные рекомендации по осадкам
        if 'дождь' in description or 'ливень' in description:
            recommendation += "\n🌂 Возьмите зонт или дождевик"
        elif 'снег' in description:
            recommendation += "\n👢 Непромокаемая обувь будет кстати"
        elif 'солн' in description or 'ясно' in description:
            recommendation += "\n🧴 Используйте солнцезащитный крем"
        
        return recommendation

    def format_weather_message(self, weather_data: Dict[str, Any]) -> str:
        if not weather_data:
            return "❌ Не удалось получить данные о погоде."

        wind_directions = {
            'N': 'северный', 'S': 'южный', 'E': 'восточный', 'W': 'западный',
            'NE': 'северо-восточный', 'NW': 'северо-западный',
            'SE': 'юго-восточный', 'SW': 'юго-западный'
        }

        wind_dir = wind_directions.get(weather_data['wind_dir'], weather_data['wind_dir'])

        message = (
            f"🌤️ <b>Погода в {weather_data['city']}</b>\n\n"
            f"🌡️ Температура: <b>{weather_data['temperature']}°C</b>\n"
            f"🤔 Ощущается как: <b>{weather_data['feels_like']}°C</b>\n"
            f"📝 Состояние: <b>{weather_data['description']}</b>\n"
            f"💧 Влажность: <b>{weather_data['humidity']}%</b>\n"
            f"📊 Давление: <b>{weather_data['pressure']} гПа</b>\n"
            f"💨 Ветер: <b>{weather_data['wind_speed']:.1f} м/с, {wind_dir}</b>"
        )
        return message

    def format_forecast_message(self, forecast_data: List[Dict[str, Any]], city: str) -> str:
        if not forecast_data:
            return "❌ Не удалось получить прогноз погоды."

        message = f"📅 <b>Прогноз погоды в {city} на 3 дня</b>\n\n"
        
        for i, day in enumerate(forecast_data):
            date_obj = datetime.strptime(day['date'], '%Y-%m-%d')
            day_name = self.get_day_name(date_obj)
            
            # Эмодзи для погоды
            weather_emoji = self.get_weather_emoji(day['description'])
            
            message += (
                f"{weather_emoji} <b>{day_name} ({day['date']})</b>\n"
                f"🌡️ Температура: <b>{day['min_temp']}°C - {day['max_temp']}°C</b>\n"
                f"📝 Погода: <b>{day['description']}</b>\n"
                f"💧 Влажность: <b>{day['avg_humidity']}%</b>\n"
                f"💨 Ветер: <b>{day['max_wind']:.1f} м/с</b>\n"
            )
            
            if day['chance_of_rain'] > 0:
                message += f"🌧️ Вероятность дождя: <b>{day['chance_of_rain']}%</b>\n"
            if day['chance_of_snow'] > 0:
                message += f"❄️ Вероятность снега: <b>{day['chance_of_snow']}%</b>\n"
                
            message += f"🌅 Восход: {day['sunrise']} | 🌇 Закат: {day['sunset']}\n\n"
        
        return message

    def get_day_name(self, date_obj: datetime) -> str:
        days = {
            0: "Понедельник",
            1: "Вторник", 
            2: "Среда",
            3: "Четверг",
            4: "Пятница",
            5: "Суббота",
            6: "Воскресенье"
        }
        return days.get(date_obj.weekday(), "")

    def get_weather_emoji(self, description: str) -> str:
        desc_lower = description.lower()
        if 'солн' in desc_lower or 'ясн' in desc_lower:
            return "☀️"
        elif 'облач' in desc_lower or 'пасмурн' in desc_lower:
            return "☁️"
        elif 'дожд' in desc_lower or 'ливень' in desc_lower:
            return "🌧️"
        elif 'снег' in desc_lower:
            return "❄️"
        elif 'туман' in desc_lower:
            return "🌫️"
        elif 'гроза' in desc_lower:
            return "⛈️"
        else:
            return "🌤️"

# Инициализация сервисов
db = Database()
weather_service = WeatherService(WEATHER_API_KEY)

# Клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤️ Погода на сегодня"), KeyboardButton(text="👕 Что надеть?")],
            [KeyboardButton(text="📅 Погода на 3 дня"), KeyboardButton(text="📍 Погода по геолокации")],
            [KeyboardButton(text="🚗 Погода по маршруту"), KeyboardButton(text="⚙️ Настройки уведомлений")],
            [KeyboardButton(text="👥 Наша группа"), KeyboardButton(text="🎲 Случайный факт")]
        ],
        resize_keyboard=True
    )

def get_location_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Поделиться геолокацией", request_location=True)],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True
    )

def get_settings_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔔 Вкл/Выкл уведомления"), KeyboardButton(text="⏰ Изменить время")],
            [KeyboardButton(text="✏️ Изменить город"), KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="👥 Все пользователи"), KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True
    )

def get_time_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ 06:00"), KeyboardButton(text="⏰ 07:00"), KeyboardButton(text="⏰ 08:00")],
            [KeyboardButton(text="⏰ 09:00"), KeyboardButton(text="⏰ 18:00"), KeyboardButton(text="⏰ 20:00")],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True
    )

# Команды бота
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    welcome_text = (
        "👋 <b>Добро пожаловать в умный погодный бот!</b>\n\n"
        "🌤️ <b>Погода на сегодня</b> - актуальная погода в вашем городе\n"
        "👕 <b>Что надеть?</b> - рекомендации по гардеробу\n"
        "📅 <b>Погода на 3 дня</b> - расширенный прогноз погоды\n"
        "📍 <b>Погода по геолокации</b> - погода по вашему местоположению\n"
        "🚗 <b>Погода по маршруту</b> - погода от точки А до Б\n"
        "⚙️ <b>Настройки уведомлений</b> - управление уведомлениями\n"
        "👥 <b>Наш канал</b> - присоединяйтесь к нашему каналу\n"
        "🎲 <b>Случайный факт</b> - интересные факты о погоде\n\n"
        "🏙️ Для начала введите название вашего города:"
    )
    await message.answer(welcome_text, parse_mode='HTML')
    await state.set_state(WeatherStates.waiting_for_city)

@dp.message(WeatherStates.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    
    await message.answer("🔍 Ищу город...")
    weather_data = weather_service.get_weather(city)
    
    if not weather_data:
        await message.answer("❌ Город не найден. Введите корректное название:")
        return
    
    db.add_user(message.from_user.id, city)
    await message.answer(
        f"✅ Город <b>{weather_data['city']}</b> успешно установлен!\n"
        f"Ежедневные уведомления будут приходить в 7:00 утра.",
        parse_mode='HTML'
    )
    
    weather_message = weather_service.format_weather_message(weather_data)
    await message.answer(weather_message, parse_mode='HTML', reply_markup=get_main_keyboard())
    await state.clear()

# Основные функции
@dp.message(F.text == "🌤️ Погода на сегодня")
async def weather_today(message: types.Message):
    user_id = message.from_user.id
    city = db.get_user_city(user_id)
    
    if not city:
        await message.answer("❌ Сначала укажите ваш город. Нажмите '✏️ Изменить город'")
        return
    
    await message.answer("🔍 Получаю актуальные данные о погоде...")
    weather_data = weather_service.get_weather(city)
    
    if weather_data:
        weather_message = weather_service.format_weather_message(weather_data)
        await message.answer(weather_message, parse_mode='HTML')
    else:
        await message.answer("❌ Не удалось получить данные о погоде. Попробуйте позже.")

@dp.message(F.text == "👕 Что надеть?")
async def wardrobe_advice(message: types.Message):
    user_id = message.from_user.id
    city = db.get_user_city(user_id)
    
    if not city:
        await message.answer("❌ Сначала укажите ваш город.")
        return
    
    await message.answer("👗 Анализирую погоду для подбора гардероба...")
    weather_data = weather_service.get_weather(city)
    
    if weather_data:
        weather_message = weather_service.format_weather_message(weather_data)
        recommendation = weather_service.get_wardrobe_recommendation(weather_data)
        
        full_message = f"{weather_message}\n\n<b>👕 Рекомендации по гардеробу:</b>\n{recommendation}"
        await message.answer(full_message, parse_mode='HTML')
    else:
        await message.answer("❌ Не удалось получить данные о погоде.")

@dp.message(F.text == "📅 Погода на 3 дня")
async def weather_forecast(message: types.Message):
    user_id = message.from_user.id
    city = db.get_user_city(user_id)
    
    if not city:
        await message.answer("❌ Сначала укажите ваш город. Нажмите '✏️ Изменить город'")
        return
    
    await message.answer("📅 Получаю прогноз погоды на 3 дня...")
    forecast_data = weather_service.get_forecast_3days(city)
    
    if forecast_data:
        forecast_message = weather_service.format_forecast_message(forecast_data, city)
        await message.answer(forecast_message, parse_mode='HTML')
    else:
        await message.answer("❌ Не удалось получить прогноз погоды. Попробуйте позже.")

@dp.message(F.text == "📍 Погода по геолокации")
async def request_location(message: types.Message):
    await message.answer(
        "📍 <b>Поделитесь вашей геолокацией</b>\n\n"
        "Нажмите кнопку ниже, чтобы отправить ваше местоположение и получить актуальную погоду:",
        parse_mode='HTML',
        reply_markup=get_location_keyboard()
    )

@dp.message(F.location)
async def handle_location(message: types.Message):
    latitude = message.location.latitude
    longitude = message.location.longitude
    
    await message.answer("📍 Получаю погоду по вашему местоположению...", reply_markup=get_main_keyboard())
    
    weather_data = weather_service.get_weather_by_coords(latitude, longitude)
    
    if weather_data:
        # Сохраняем местоположение пользователя
        db.update_user_location(message.from_user.id, latitude, longitude, weather_data['city'])
        
        weather_message = weather_service.format_weather_message(weather_data)
        await message.answer(weather_message, parse_mode='HTML')
        
        # Предлагаем сохранить город
        save_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💾 Сохранить этот город", callback_data=f"save_city_{weather_data['city']}")]
            ]
        )
        await message.answer(
            f"💡 Хотите сохранить <b>{weather_data['city']}</b> как ваш основной город для уведомлений?",
            parse_mode='HTML',
            reply_markup=save_markup
        )
    else:
        await message.answer("❌ Не удалось получить погоду по вашему местоположению.")

@dp.callback_query(F.data.startswith("save_city_"))
async def save_city_from_location(callback: types.CallbackQuery):
    city = callback.data.replace("save_city_", "")
    user_id = callback.from_user.id
    
    db.add_user(user_id, city)
    await callback.message.edit_text(f"✅ Город <b>{city}</b> успешно сохранен!", parse_mode='HTML')
    await callback.answer()

@dp.message(F.text == "🚗 Погода по маршруту")
async def start_route_weather(message: types.Message, state: FSMContext):
    await message.answer("🗺️ <b>Погода по маршруту</b>\n\nВведите начальную точку маршрута (город или адрес):", parse_mode='HTML')
    await state.set_state(WeatherStates.waiting_for_route_start)

@dp.message(WeatherStates.waiting_for_route_start)
async def process_route_start(message: types.Message, state: FSMContext):
    await state.update_data(route_start=message.text)
    await message.answer("📍 Теперь введите конечную точку маршрута:")
    await state.set_state(WeatherStates.waiting_for_route_end)

@dp.message(WeatherStates.waiting_for_route_end)
async def process_route_end(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    start_city = user_data['route_start']
    end_city = message.text
    
    await message.answer(f"🔍 Сравниваю погоду по маршруту:\n{start_city} → {end_city}")
    
    start_weather = weather_service.get_weather(start_city)
    end_weather = weather_service.get_weather(end_city)
    
    if start_weather and end_weather:
        message_text = (
            f"🚗 <b>Погода по маршруту</b>\n\n"
            f"📍 <b>Отправление из {start_weather['city']}:</b>\n"
            f"🌡️ {start_weather['temperature']}°C, {start_weather['description']}\n\n"
            f"🎯 <b>Прибытие в {end_weather['city']}:</b>\n"
            f"🌡️ {end_weather['temperature']}°C, {end_weather['description']}\n\n"
        )
        
        temp_diff = end_weather['temperature'] - start_weather['temperature']
        if abs(temp_diff) >= 5:
            if temp_diff > 0:
                message_text += "📈 <b>Совет:</b> Будет теплее, можно одеться легче"
            else:
                message_text += "📉 <b>Совет:</b> Будет холоднее, возьмите дополнительную одежду"
        
        await message.answer(message_text, parse_mode='HTML')
    else:
        await message.answer("❌ Не удалось получить данные для одного из городов")
    
    await state.clear()

@dp.message(F.text == "🎲 Случайный факт")
async def weather_fact(message: types.Message):
    facts = [
        "🌪️ Самая высокая скорость ветра была зарегистрирована в 1996 году в Австралии - 408 км/ч!",
        "❄️ Самый большой снегопад был в 1921 году в США - за сусутки выпало 193 см снега!",
        "🌡️ Самая высокая температура была зафиксирована в Долине Смерти (Калифорния) - 56.7°C!",
        "🌀 Глаз урагана - это область полного спокойствия в центре бури диаметром до 50 км!",
        "🌈 Двойная радуга появляется когда свет отражается в каплях воды дважды!",
        "⚡ Молния может нагревать воздух до 30,000°C - в 5 раз горячее поверхности Солнца!",
        "💨 В Антарктиде дуют самые сильные ветра на Земле - до 320 км/ч!",
        "🌧️ Самая крупная градина весила 1 кг и упала в Бангладеш в 1986 году!"
    ]
    
    import random
    fact = random.choice(facts)
    await message.answer(f"🎲 <b>Случайный факт о погоде:</b>\n\n{fact}", parse_mode='HTML')

@dp.message(F.text == "👥 Наша группа")
async def group_invite(message: types.Message):
    invite_text = (
        "👥 <b>Присоединяйтесь к нашему каналу!</b>\n\n"
        "В нашем канале вы найдете:\n"
        "• Списки моих проектов\n"
        "• Истории созданий\n"
        "• Моя жизнь\n"
        f"👉 <a href='{GROUP_LINK}'>Присоединиться к каналу</a>"
    )
    await message.answer(invite_text, parse_mode='HTML')

# Настройки уведомлений
@dp.message(F.text == "⚙️ Настройки уведомлений")
async def notification_settings(message: types.Message):
    user_id = message.from_user.id
    current_status = db.get_notifications_status(user_id)
    current_time = db.get_notification_time(user_id)
    
    status_text = "включены 🔔" if current_status else "выключены 🔕"
    
    settings_text = (
        f"⚙️ <b>Настройки уведомлений</b>\n\n"
        f"Текущий статус: <b>{status_text}</b>\n"
        f"Время уведомлений: <b>{current_time}</b>\n\n"
        "Выберите действие:"
    )
    
    await message.answer(settings_text, parse_mode='HTML', reply_markup=get_settings_keyboard())

@dp.message(F.text == "🔔 Вкл/Выкл уведомления")
async def toggle_notifications(message: types.Message):
    user_id = message.from_user.id
    new_status = db.toggle_notifications(user_id)
    
    status_text = "включены 🔔" if new_status else "выключены 🔕"
    await message.answer(f"✅ Уведомления теперь <b>{status_text}</b>", parse_mode='HTML')

@dp.message(F.text == "⏰ Изменить время")
async def change_notification_time(message: types.Message, state: FSMContext):
    await message.answer(
        "⏰ <b>Выберите время для уведомлений:</b>\n\n"
        "Уведомления будут приходить ежедневно в выбранное время",
        parse_mode='HTML',
        reply_markup=get_time_keyboard()
    )
    await state.set_state(WeatherStates.waiting_for_notification_time)

@dp.message(WeatherStates.waiting_for_notification_time)
async def process_notification_time(message: types.Message, state: FSMContext):
    if message.text in ["⏰ 06:00", "⏰ 07:00", "⏰ 08:00", "⏰ 09:00", "⏰ 18:00", "⏰ 20:00"]:
        time_str = message.text.replace("⏰ ", "")
        db.update_notification_time(message.from_user.id, time_str)
        await message.answer(f"✅ Время уведомлений установлено на <b>{time_str}</b>", 
                           parse_mode='HTML', reply_markup=get_main_keyboard())
        await state.clear()
    else:
        await message.answer("❌ Пожалуйста, выберите время из предложенных вариантов")

@dp.message(F.text == "✏️ Изменить город")
async def change_city(message: types.Message, state: FSMContext):
    await message.answer("🏙️ Введите новый город:")
    await state.set_state(WeatherStates.waiting_for_city)

@dp.message(F.text == "🏠 Главное меню")
async def main_menu(message: types.Message):
    await message.answer("🏠 Главное меню", reply_markup=get_main_keyboard())

# Админ команды
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ панели")
        return
    
    users = db.get_all_users()
    enabled_users = len([u for u in users if u[2]])
    
    stats_text = (
        "👨‍💻 <b>Админ панель</b>\n\n"
        f"👥 Всего пользователей: <b>{len(users)}</b>\n"
        f"🔔 Уведомления включены: <b>{enabled_users}</b>"
    )
    
    await message.answer(stats_text, parse_mode='HTML', reply_markup=get_admin_keyboard())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    users = db.get_all_users()
    enabled_users = len([u for u in users if u[2]])
    
    # Статистика по времени уведомлений
    time_stats = {}
    for user in users:
        if user[2]:  # если уведомления включены
            time_str = user[3]
            time_stats[time_str] = time_stats.get(time_str, 0) + 1
    
    stats_text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{len(users)}</b>\n"
        f"🔔 Уведомления включены: <b>{enabled_users}</b>\n"
        f"🔕 Уведомления выключены: <b>{len(users) - enabled_users}</b>\n\n"
        "<b>Распределение по времени:</b>\n"
    )
    
    for time_str, count in sorted(time_stats.items()):
        stats_text += f"⏰ {time_str}: {count} пользователей\n"
    
    await message.answer(stats_text, parse_mode='HTML')

@dp.message(F.text == "👥 Все пользователи")
async def all_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    users = db.get_all_users()
    
    if not users:
        await message.answer("📭 Пользователей пока нет")
        return
    
    users_text = "👥 <b>Все пользователи:</b>\n\n"
    for i, user in enumerate(users[:10], 1):
        status = "🔔" if user[2] else "🔕"
        users_text += f"{i}. ID: {user[0]} | {user[1]} | {status} | {user[3]}\n"
    
    if len(users) > 10:
        users_text += f"\n... и еще {len(users) - 10} пользователей"
    
    await message.answer(users_text, parse_mode='HTML')

@dp.message(F.text == "📢 Рассылка")
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("📝 Введите сообщение для рассылки:")
    await state.set_state(WeatherStates.waiting_for_broadcast)

@dp.message(WeatherStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = db.get_all_users()
    success_count = 0
    
    await message.answer(f"🔄 Начинаю рассылку для {len(users)} пользователей...")
    
    for user in users:
        try:
            await bot.send_message(
                user[0], 
                f"📢 <b>Рассылка от администратора:</b>\n\n{message.text}", 
                parse_mode='HTML'
            )
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to send to user {user[0]}: {e}")
    
    await message.answer(f"✅ Рассылка завершена!\nУспешно отправлено: {success_count}/{len(users)}")
    await state.clear()

# Ежедневные уведомления
async def send_daily_weather_notifications():
    logger.info("🔄 Starting daily weather notifications...")
    
    # Получаем текущее время в формате HH:MM
    current_time = datetime.now().strftime("%H:%M")
    
    # Получаем пользователей с уведомлениями в текущее время
    users = db.get_users_by_notification_time(current_time)
    
    success_count = 0
    error_count = 0
    
    for user_id, city in users:
        try:
            weather_data = weather_service.get_weather(city)
            if weather_data:
                weather_message = weather_service.format_weather_message(weather_data)
                wardrobe_advice = weather_service.get_wardrobe_recommendation(weather_data)
                
                full_message = (
                    f"{weather_message}\n\n"
                    f"<b>👕 Рекомендации на сегодня:</b>\n{wardrobe_advice}\n\n"
                    f"🌅 Хорошего дня! ☕"
                )
                
                await bot.send_message(user_id, full_message, parse_mode='HTML')
                success_count += 1
                logger.info(f"✅ Weather sent to user {user_id} for city {city} at {current_time}")
            else:
                error_count += 1
                logger.error(f"❌ Failed to get weather for user {user_id}, city: {city}")
            
            await asyncio.sleep(0.3)
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Failed to send weather to user {user_id}: {e}")
    
    logger.info(f"📊 Weather notifications completed for {current_time}. Success: {success_count}, Errors: {error_count}")

# Планировщик - проверяет каждую минуту
def setup_scheduler():
    scheduler.add_job(
        send_daily_weather_notifications,
        'interval',
        minutes=1
    )
    logger.info("✅ Scheduler started - checking every minute for notifications")

# Запуск бота
async def main():
    logger.info("🚀 Starting Advanced Weather Bot...")
    
    # Проверка API
    test_weather = weather_service.get_weather("Moscow")
    if not test_weather:
        logger.error("❌ Weather API connection failed!")
        return
    
    logger.info("✅ Weather API connection successful!")
    
    # Запуск планировщика
    setup_scheduler()
    scheduler.start()
    logger.info("✅ Scheduler started - checking for notifications every minute")
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())