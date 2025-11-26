import sqlite3

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
                    notification_time TEXT DEFAULT '07:00'
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

    def get_user_city(self, user_id: int) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT city FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else None

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

    def get_users_by_notification_time(self, target_time: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, city FROM users WHERE notifications_enabled = TRUE AND notification_time = ?', (target_time,))
            return cursor.fetchall()
