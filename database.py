import sqlite3
import datetime

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('referrals.db')
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_date TEXT
            )
        ''')
        
        # Таблица приглашений (навсегда)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                friend_id INTEGER UNIQUE,
                joined_date TEXT,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (friend_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица недельной статистики
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS weekly_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                week_start TEXT,
                invites_count INTEGER DEFAULT 0,
                tickets_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Уникальность: один пользователь - одна запись на неделю
        self.cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly 
            ON weekly_stats(user_id, week_start)
        ''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name):
        """Добавляет нового пользователя"""
        today = str(datetime.date.today())
        try:
            self.cursor.execute(
                "INSERT INTO users (user_id, username, first_name, joined_date) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, today)
            )
            self.conn.commit()
            return True
        except:
            return False  # Пользователь уже есть
    
    def add_referral(self, referrer_id, friend_id):
        """Добавляет реферала (друга)"""
        today = str(datetime.date.today())
        try:
            # Добавляем в вечную таблицу рефералов
            self.cursor.execute(
                "INSERT INTO referrals (referrer_id, friend_id, joined_date) VALUES (?, ?, ?)",
                (referrer_id, friend_id, today)
            )
            
            # Обновляем недельную статистику
            self.update_weekly_stats(referrer_id)
            
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Друг уже был приглашен кем-то
    
    def update_weekly_stats(self, user_id):
        """Обновляет статистику за неделю"""
        week_start = self.get_week_start()
        
        # Проверяем, есть ли запись за эту неделю
        self.cursor.execute(
            "SELECT id FROM weekly_stats WHERE user_id = ? AND week_start = ?",
            (user_id, week_start)
        )
        result = self.cursor.fetchone()
        
        if result:
            # Обновляем существующую запись
            self.cursor.execute(
                "UPDATE weekly_stats SET invites_count = invites_count + 1 WHERE user_id = ? AND week_start = ?",
                (user_id, week_start)
            )
        else:
            # Создаем новую запись
            self.cursor.execute(
                "INSERT INTO weekly_stats (user_id, week_start, invites_count) VALUES (?, ?, 1)",
                (user_id, week_start)
            )
        
        # Пересчитываем билеты по формуле
        self.calculate_tickets(user_id, week_start)
        self.conn.commit()
    
    def calculate_tickets(self, user_id, week_start):
        """Расчет билетов по формуле"""
        # Получаем количество приглашений
        self.cursor.execute(
            "SELECT invites_count FROM weekly_stats WHERE user_id = ? AND week_start = ?",
            (user_id, week_start)
        )
        result = self.cursor.fetchone()
        
        if not result:
            return
        
        invites = result[0]
        
        # ФОРМУЛА РАСЧЕТА БИЛЕТОВ (настраивай здесь!)
        if invites == 0:
            tickets = 0
        elif invites <= 4:
            tickets = invites  # 1 друг = 1 билет
        elif invites <= 9:
            tickets = invites + 1  # 5+ друзей = +1 бонус
        else:
            tickets = invites + 2  # 10+ друзей = +2 бонуса
        
        # Обновляем количество билетов
        self.cursor.execute(
            "UPDATE weekly_stats SET tickets_count = ? WHERE user_id = ? AND week_start = ?",
            (tickets, user_id, week_start)
        )
        self.conn.commit()
    
    def get_week_start(self):
        """Возвращает дату начала текущей недели (понедельник)"""
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        return str(monday)
    
    def get_user_stats(self, user_id):
        """Получает статистику пользователя за текущую неделю"""
        week_start = self.get_week_start()
        
        self.cursor.execute(
            "SELECT invites_count, tickets_count FROM weekly_stats WHERE user_id = ? AND week_start = ?",
            (user_id, week_start)
        )
        result = self.cursor.fetchone()
        
        if result:
            return {"invites": result[0], "tickets": result[1]}
        else:
            return {"invites": 0, "tickets": 0}
    
    def get_top_users(self, limit=10):
        """Топ пользователей по билетам за неделю"""
        week_start = self.get_week_start()
        
        self.cursor.execute('''
            SELECT users.user_id, users.username, users.first_name, 
                   weekly_stats.invites_count, weekly_stats.tickets_count
            FROM weekly_stats
            JOIN users ON weekly_stats.user_id = users.user_id
            WHERE weekly_stats.week_start = ?
            ORDER BY weekly_stats.tickets_count DESC
            LIMIT ?
        ''', (week_start, limit))
        
        return self.cursor.fetchall()
    
    def get_referrer_by_start_param(self, referrer_id):
        """Проверяет, существует ли пригласивший"""
        self.cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (referrer_id,)
        )
        return self.cursor.fetchone()
    
    def close(self):
        self.conn.close()