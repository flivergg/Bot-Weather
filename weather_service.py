import requests
from datetime import datetime

class WeatherService:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_weather(self, city: str):
        try:
            url = "http://api.weatherapi.com/v1/current.json"
            params = {'key': self.api_key, 'q': city, 'lang': 'ru'}
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
                'wind_speed': data['current']['wind_kph'] / 3.6
            }
        except Exception:
            return None

    def get_wardrobe_recommendation(self, weather_data):
        temp = weather_data['temperature']
        description = weather_data['description'].lower()
        
        if temp >= 25:
            recommendation = "👕 Легкая одежда: футболка, шорты, сандалии"
        elif temp >= 18:
            recommendation = "👔 Умеренная одежда: рубашка, джинсы, кроссовки"
        elif temp >= 10:
            recommendation = "🧥 Теплая одежда: свитер, брюки, закрытая обувь"
        elif temp >= 0:
            recommendation = "🧤 Зимняя одежда: пуховик, шапка, перчатки"
        else:
            recommendation = "❄️ Сильно утепляйтесь: термобелье, зимняя куртка"
        
        if 'дождь' in description:
            recommendation += "\n🌂 Возьмите зонт"
        elif 'снег' in description:
            recommendation += "\n👢 Непромокаемая обувь"
        
        return recommendation
