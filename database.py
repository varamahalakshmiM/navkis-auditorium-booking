import sqlite3
from werkzeug.security import generate_password_hash

DATABASE = "auditorium.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            event_name TEXT NOT NULL,
            purpose TEXT,
            participants INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Create/update the single built-in administrator account.
    # The credentials are intentionally not displayed on the login page.
    admin = cur.execute(
        "SELECT id FROM users WHERE username = ?",
        ("navkisadmin",)
    ).fetchone()

    legacy_admin = cur.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if admin is None and legacy_admin is not None:
        cur.execute("""
            UPDATE users
            SET name = ?, username = ?, password = ?, role = 'admin', active = 1
            WHERE id = ?
        """, (
            "Administrator",
            "navkisadmin",
            generate_password_hash("navkis@2005"),
            legacy_admin["id"]
        ))
    elif admin is None:
        cur.execute("""
            INSERT INTO users (name, username, password, role, active)
            VALUES (?, ?, ?, ?, 1)
        """, (
            "Administrator",
            "navkisadmin",
            generate_password_hash("navkis@2005"),
            "admin"
        ))
    else:
        cur.execute("""
            UPDATE users
            SET name = ?, password = ?, role = 'admin', active = 1
            WHERE id = ?
        """, (
            "Administrator",
            generate_password_hash("navkis@2005"),
            admin["id"]
        ))

    # Disable any legacy account that still uses the old administrator username.
    cur.execute(
        "UPDATE users SET active = 0 WHERE username = ? AND username != ?",
        ("admin", "navkisadmin")
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
