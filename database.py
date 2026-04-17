import sqlite3
import pandas as pd
import os
from datetime import datetime, timezone, timedelta
import streamlit as st

# --- 定数設定 ---
DB_PATH = "fishing_club_v6.db"
UPLOAD_DIR = "./uploads"
# 日本標準時 (JST) の設定
JST = timezone(timedelta(hours=9))

# ======================
# 1. データベース基本操作
# ======================
def db_op(query, params=(), fetch=False):
    """
    SQLを実行するための共通関数。
    fetch=True の場合は pandas の DataFrame を返し、
    False の場合は INSERT/UPDATE/DELETE を実行してコミットします。
    """
    with sqlite3.connect(DB_PATH) as conn:
        if fetch:
            return pd.read_sql(query, conn, params=params)
        conn.execute(query, params)
        conn.commit()

# ======================
# 2. テーブル初期化とマイグレーション
# ======================
def init_db():
    """
    アプリ起動時に呼び出し、必要なテーブルとカラムが揃っているか確認・作成します。
    """
    # アップロード用ディレクトリの作成
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        # --- posts テーブル (釣果投稿) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                datetime TEXT,
                name TEXT,
                fish TEXT,
                size INTEGER,
                place TEXT,
                image_path TEXT,
                likes INTEGER DEFAULT 0,
                pressure REAL,
                weather_desc TEXT,
                tide TEXT,
                moon_age REAL
            )
        """)

        # --- points テーブル (釣り場ポイント) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS points (
                id INTEGER PRIMARY KEY,
                name TEXT,
                memo TEXT,
                lat REAL,
                lon REAL
            )
        """)

        # --- users テーブル (ユーザー管理) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                name TEXT
            )
        """)

        # --- マイグレーション (既存DBへのカラム追加対応) ---
        # 現在のテーブル情報を取得してカラム名のリストを作る
        cursor = conn.execute("PRAGMA table_info(posts)")
        existing_cols = [row[1] for row in cursor.fetchall()]

        # 不足しているカラムがあれば追加する
        if "tide" not in existing_cols:
            conn.execute("ALTER TABLE posts ADD COLUMN tide TEXT")
        
        if "moon_age" not in existing_cols:
            conn.execute("ALTER TABLE posts ADD COLUMN moon_age REAL")
            
        if "image_path" not in existing_cols:
            conn.execute("ALTER TABLE posts ADD COLUMN image_path TEXT")
            
        if "weather_desc" not in existing_cols:
            conn.execute("ALTER TABLE posts ADD COLUMN weather_desc TEXT")
            
        conn.commit()

    # --- 初期ユーザーの登録 (管理者) ---
    # ユーザーテーブルが空の場合のみ、デフォルトの管理者を登録します
    check_user = db_op("SELECT * FROM users", fetch=True)
    if check_user.empty:
        db_op("INSERT INTO users (uid, name) VALUES (?, ?)", ("7023911", "管理者"))

# ======================
# 3. データ取得用ユーティリティ
# ======================
@st.cache_data(ttl=30)
def get_posts_from_db(limit=50):
    """
    最新の投稿を指定件数取得します。
    Streamlitのキャッシュを利用して、30秒間はDBへの再アクセスを抑制します。
    """
    query = f"SELECT * FROM posts ORDER BY id DESC LIMIT {limit}"
    return db_op(query, fetch=True)

def get_registered_points():
    """
    登録済みのポイント地点をすべて取得します。
    """
    return db_op("SELECT * FROM points", fetch=True)

def get_user_by_id(uid):
    """
    学籍番号（UID）からユーザー名を検索します。
    """
    return db_op("SELECT name FROM users WHERE uid=?", (uid,), fetch=True)