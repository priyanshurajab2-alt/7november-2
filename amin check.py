import sqlite3

email_to_check = input("Enter email to check: ").strip().lower()

conn = sqlite3.connect('admin_users.db')
conn.row_factory = sqlite3.Row
user = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email_to_check,)).fetchone()
conn.close()

if user:
    print(f"User found: ID={user['id']}, Username={user['username']}, Email={user['email']}, UserType={user['user_type']}, Active={user['is_active']}")
else:
    print("No user found with email:", email_to_check)
