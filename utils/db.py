"""SQLite veritabanı katmanı. Python ile birlikte gelir, ek kurulum gerekmez."""
import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    value    TEXT,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS levels (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    xp       INTEGER NOT NULL DEFAULT 0,
    level    INTEGER NOT NULL DEFAULT 0,
    voice_xp    INTEGER NOT NULL DEFAULT 0,
    voice_level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level    INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    credits    INTEGER NOT NULL DEFAULT 0,
    rep        INTEGER NOT NULL DEFAULT 0,
    last_daily REAL    NOT NULL DEFAULT 0,
    last_rep   REAL    NOT NULL DEFAULT 0,
    bio        TEXT
);
CREATE TABLE IF NOT EXISTS autoresponses (
    guild_id INTEGER NOT NULL,
    trigger  TEXT    NOT NULL,
    response TEXT    NOT NULL,
    mode     TEXT    NOT NULL DEFAULT 'tam',
    PRIMARY KEY (guild_id, trigger)
);
CREATE TABLE IF NOT EXISTS reaction_roles (
    guild_id   INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji      TEXT    NOT NULL,
    role_id    INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);
CREATE TABLE IF NOT EXISTS warnings (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    mod_id   INTEGER NOT NULL,
    reason   TEXT,
    ts       REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS starboard (
    message_id  INTEGER PRIMARY KEY,
    board_msg_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jail (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    roles    TEXT    NOT NULL,   -- alınan rollerin ID listesi (JSON)
    until    REAL,               -- bitiş zamanı (NULL = süresiz)
    reason   TEXT,
    mod_id   INTEGER NOT NULL,
    ts       REAL    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS invite_roles (
    guild_id INTEGER NOT NULL,
    code     TEXT    NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, code, role_id)
);
CREATE TABLE IF NOT EXISTS temp_channels (
    channel_id INTEGER PRIMARY KEY,
    owner_id   INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str = "data/bot.db"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            # Eski veritabanlarına ses seviyesi sütunlarını ekle (mevcut XP yazı XP'si olarak kalır)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(levels)")}
            if "voice_xp" not in cols:
                self.conn.execute("ALTER TABLE levels ADD COLUMN voice_xp INTEGER NOT NULL DEFAULT 0")
            if "voice_level" not in cols:
                self.conn.execute("ALTER TABLE levels ADD COLUMN voice_level INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()

    # --- genel ---
    def execute(self, sql: str, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def one(self, sql: str, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    # --- sunucu ayarları (anahtar/değer, JSON olarak saklanır) ---
    def get(self, guild_id: int, key: str, default=None):
        row = self.one("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
        if row is None or row["value"] is None:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set(self, guild_id: int, key: str, value):
        if value is None:
            self.execute("DELETE FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
        else:
            self.execute(
                "INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
                (guild_id, key, json.dumps(value, ensure_ascii=False)),
            )

    # --- kullanıcı (kredi, itibar, profil) ---
    def user(self, user_id: int):
        row = self.one("SELECT * FROM users WHERE user_id=?", (user_id,))
        if row is None:
            self.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            row = self.one("SELECT * FROM users WHERE user_id=?", (user_id,))
        return row

    # --- seviye ---
    def level_row(self, guild_id: int, user_id: int):
        row = self.one("SELECT * FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        if row is None:
            self.execute("INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
            row = self.one("SELECT * FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        return row
