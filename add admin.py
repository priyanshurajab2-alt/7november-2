import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'admin_users.db')

# Change these to your desired admin credentials
ADMIN_USERNAME = "AdminUser"
ADMIN_EMAIL = "anshukumarraaj2005@gmail.com"
ADMIN_PASSWORD = "Br09s3765@"  # Choose a strong password


def add_or_update_admin_user():
    password_hash = generate_password_hash(ADMIN_PASSWORD)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                user_type TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        ''')

        conn.execute('''
            INSERT INTO users (username, email, password, user_type, is_active)
            VALUES (?, ?, ?, 'admin', 1)
            ON CONFLICT(email) DO UPDATE SET
                username=excluded.username,
                password=excluded.password,
                user_type='admin',
                is_active=1
        ''', (ADMIN_USERNAME, ADMIN_EMAIL.lower(), password_hash))

        conn.commit()
        print(f"Admin user '{ADMIN_EMAIL}' added or updated successfully.")
    except Exception as e:
        print("Error adding/updating admin user:", e)
    finally:
        conn.close()


if __name__ == '__main__':
    add_or_update_admin_user()
