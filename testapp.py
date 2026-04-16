import streamlit as st
import pandas as pd
import sqlite3
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
import base64, requests, math, io, os
from PIL import Image
import plotly.express as px
from datetime import datetime
import filetype  # pip install filetype

# ======================
# 1. ページ・DB設定
# ======================
st.set_page_config(page_title="秋田釣り同好会 Portal", page_icon="🎣", layout="wide")

DB_PATH = "fishing_club_v6.db"
UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def db_op(query, params=(), fetch=False):
    with sqlite3.connect(DB_PATH) as conn:
        if fetch:
            return pd.read_sql(query, conn, params=params)
        conn.execute(query, params)
        conn.commit()

# ======================
# DBスキーマを一元管理（migrate_db の接続リーク・分散を修正）
# ======================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS points (
                id INTEGER PRIMARY KEY,
                name TEXT,
                memo TEXT,
                lat REAL,
                lon REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        # 旧スキーマ（image TEXT）から image_path TEXT への移行対応
        cols = [row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()]

        if "tide" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN tide TEXT")

        if "moon_age" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN moon_age REAL")
        
        if "image_path" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN image_path TEXT")
        if "weather_desc" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN weather_desc TEXT")
        conn.commit()

    # 初期ユーザー登録（テーブルが空のときだけ）
    if db_op("SELECT * FROM users", fetch=True).empty:
        db_op("INSERT INTO users (uid, name) VALUES (?, ?)", ("7023911", "管理者"))

init_db()

# ======================
# 2. 共通ロジック
# ======================
BASE_COORDS = {
    "秋田港": [39.74, 140.09], "男鹿港": [39.90, 139.85], "船川港": [39.89, 139.84],
    "能代港": [40.21, 140.02], "本荘マリーナ": [39.38, 140.05]
}

def get_locs():
    locs = BASE_COORDS.copy()
    df_p = db_op("SELECT name, lat, lon FROM points", fetch=True)
    for _, r in df_p.iterrows():
        locs[r['name']] = [r['lat'], r['lon']]
    return locs

# 【パフォーマンス修正】天気APIを10分キャッシュ（毎リロードで叩かない）
@st.cache_data(ttl=600)
def get_jma_weather(lat, lon):
    """Open-Meteo APIを使用して気象庁データ＋日没取得"""
    try:
        lat_f, lon_f = round(float(lat), 4), round(float(lon), 4)
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat_f,
            "longitude": lon_f,
            "current": "temperature_2m,surface_pressure,weather_code,wind_speed_10m,wind_direction_10m",
            "daily": "sunrise,sunset",
            "forecast_days": 1,
            "models": "jma",
            "timezone": "Asia/Tokyo"
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 400:
            params.pop("models")
            response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return None
        res = response.json()
        curr = res.get("current", {})
        daily = res.get("daily", {})
        w_dict = {
            0: "快晴", 1: "晴れ", 2: "一部曇", 3: "曇り",
            45: "霧", 48: "霧氷", 51: "霧雨", 61: "小雨",
            63: "雨", 65: "強い雨", 71: "小雪", 73: "雪",
            75: "強い雪", 80: "にわか雨", 95: "雷雨"
        }
        return {
            "temp": curr.get("temperature_2m"),
            "pressure": curr.get("surface_pressure"),
            "wind_speed": curr.get("wind_speed_10m"),
            "wind_deg": curr.get("wind_direction_10m"),
            "desc": w_dict.get(curr.get("weather_code"), f"不明({curr.get('weather_code')})"),
            "sunrise": daily.get("sunrise", [None])[0],
            "sunset": daily.get("sunset", [None])[0],
        }
    except Exception:
        return None

def deg_to_win(deg):
    labels = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
              "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    return labels[int((deg + 11.25) / 22.5) % 16]
def calc_moon_age(dt: datetime) -> float:
    base = datetime(2000, 1, 6)  # 新月基準
    days = (dt - base).total_seconds() / 86400
    return round(days % 29.53, 1)

def calc_tide(moon_age: float) -> str:
    if moon_age < 2 or moon_age > 27:
        return "大潮"
    elif 5 < moon_age < 10 or 20 < moon_age < 25:
        return "中潮"
    else:
        return "小潮"
    

# 【セキュリティ修正】実際のファイル種別を検証（拡張子偽装を防ぐ）
def is_valid_image(file_bytes: bytes) -> bool:
    kind = filetype.guess(file_bytes)
    return kind is not None and kind.mime.startswith("image/")

# 【パフォーマンス修正】投稿一覧を30秒キャッシュ（毎描画で全件取得しない）
@st.cache_data(ttl=30)
def get_posts(limit: int = 50):
    return db_op(f"SELECT * FROM posts ORDER BY id DESC LIMIT {limit}", fetch=True)

# ======================
# 3. 各機能ページ
# ======================

def post_page():
    st.title("🎣 釣果投稿・マップ")
    locs = get_locs()
    col_in, col_map = st.columns([1, 1.5])

    with col_in:
        with st.expander("✨ 新規投稿", expanded=True):
            fish = st.text_input("魚種")
            st.subheader("🕒 釣行時刻")

            use_now = st.checkbox("現在時刻を使う", value=True)

            if use_now:
                fish_time = datetime.now()
            else:
                d = st.date_input("日付")
                t = st.time_input("時刻")
                fish_time = datetime.combine(d, t)
            size = st.number_input("サイズ(cm)", 0)
            place = st.selectbox("釣り場", list(locs.keys()))
            img = st.file_uploader("写真", type=["jpg", "png", "jpeg"])

            w_now = get_jma_weather(*locs[place])
            if w_now:
                st.caption(f"現在の現地の天気: {w_now['desc']} ({w_now['pressure']}hPa)")
            else:
                # 【バグ修正】天気取得失敗を明示表示
                st.caption("⚠️ 天気情報を取得できませんでした（投稿は可能です）")

            if st.button("投稿を完了", use_container_width=True, type="primary"):
                image_path = ""
                if img:
                    # 【バグ修正】画像処理を try/except でラップ（クラッシュ防止）
                    # 【セキュリティ修正】実際のバイト列で種別検証
                    try:
                        raw = img.read()
                        if not is_valid_image(raw):
                            st.warning("⚠️ 有効な画像ファイルではありません。写真なしで投稿します。")
                        else:
                            pil_img = Image.open(io.BytesIO(raw))
                            pil_img.thumbnail((500, 500))
                            # 【パフォーマンス修正】DBではなくファイルシステムに保存
                            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{img.name}"
                            save_path = os.path.join(UPLOAD_DIR, fname)
                            pil_img.save(save_path, format="JPEG", quality=75)
                            image_path = save_path
                    except Exception as e:
                        st.warning(f"⚠️ 画像の処理に失敗しました: {e}。写真なしで投稿します。")

                pres = w_now['pressure'] if w_now else None
                w_desc = w_now['desc'] if w_now else "取得失敗"

                fish_time = datetime.now()
                moon_age = calc_moon_age(fish_time)
                tide = calc_tide(moon_age)

                db_op(
                    """
                    INSERT INTO posts (
                        datetime, name, fish, size, place,
                        image_path, pressure, weather_desc,
                        tide, moon_age
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fish_time.strftime("%Y/%m/%d %H:%M"),
                        st.session_state.login_user,
                        fish,
                        size,
                        place,
                        image_path,
                        pres,
                        w_desc,
                        tide,
                        moon_age
                    )
                )
                
                # キャッシュを無効化して最新投稿を反映
                get_posts.clear()
                st.rerun()

    # 【パフォーマンス修正】直近50件のみ取得
    df = get_posts(limit=50)

    with col_map:
        m = folium.Map(location=[39.75, 140.0], zoom_start=8, tiles="cartodbpositron")
        marker_cluster = MarkerCluster(name="詳細").add_to(m)
        for _, r in df.iterrows():
            if r["place"] in locs:
                popup_html = (f"<b>📍 {r['place']}</b><br>🐟 {r['fish']}({r['size']}cm)"
                              f"<br>🌤 {r.get('weather_desc','-')}<br>👤 {r['name']}")
                folium.Marker(
                    location=locs[r["place"]],
                    popup=folium.Popup(popup_html, max_width=200),
                    icon=folium.Icon(color="blue", icon="fish", prefix="fa")
                ).add_to(marker_cluster)
        st_folium(m, width="100%", height=500, key="main_map")

    st.divider()
    for _, r in df.iterrows():
        with st.container(border=True):
            is_owner = (r["name"] == st.session_state.login_user)

            if is_owner:
                st.caption("🟢 あなたの投稿")
            else:
                st.caption("🔒 他のメンバーの投稿")

            # ===== 編集ボタン（自分の投稿だけ）=====
            if st.session_state.edit_post_id == r["id"]:

                st.subheader("✏️ 投稿を編集")

                fish = st.text_input(
                    "魚種",
                    value=r["fish"],
                    key=f"edit_fish_{r['id']}"
                )

                place = st.selectbox(
                    "釣り場",
                    options=list(locs.keys()),
                    index=list(locs.keys()).index(r["place"]) if r["place"] in locs else 0,
                    key=f"edit_place_{r['id']}"
                )

                # ---- サイズ ----
                size = st.number_input(
                    "サイズ (cm)",
                    value=int(r["size"]),
                    min_value=0,
                    key=f"edit_size_{r['id']}"
                )

                # ---- 現在の画像 ----
                st.markdown("### 🖼 現在の写真")

                current_image_path = r.get("image_path")

                if current_image_path and os.path.exists(str(current_image_path)):
                    st.image(current_image_path, width=250)
                else:
                    st.caption("（画像なし）")

                # ---- 新しい画像（任意）----
                st.markdown("### 🔁 写真を差し替える（任意）")
                new_img = st.file_uploader(
                    "新しい写真を選択",
                    type=["jpg", "jpeg", "png"],
                    key=f"edit_img_{r['id']}"
                )

                # ---- 釣行時刻 ----
                st.markdown("### 🕒 釣行時刻")
                use_now = st.checkbox(
                    "現在時刻を使う",
                    value=False,
                    key=f"edit_now_{r['id']}"
                )

                if use_now:
                    fish_time = datetime.now()
                else:
                    d = st.date_input(
                        "日付",
                        value=datetime.strptime(r["datetime"], "%Y/%m/%d %H:%M").date(),
                        key=f"edit_date_{r['id']}"
                    )
                    t = st.time_input(
                        "時刻",
                        value=datetime.strptime(r["datetime"], "%Y/%m/%d %H:%M").time(),
                        key=f"edit_time_{r['id']}"
                    )
                    fish_time = datetime.combine(d, t)

                # ---- 天気（手動）----
                st.markdown("### 🌤 天気")
                weather_desc = st.text_input(
                    "天気メモ",
                    value=r["weather_desc"],
                    key=f"edit_weather_{r['id']}"
                )

                # ---- ボタン ----
                col_save, col_cancel = st.columns(2)

                with col_save:
                    if st.button("💾 保存", key=f"save_{r['id']}"):

                        new_image_path = current_image_path  # デフォルトは維持

                        # ===== 新しい画像が選ばれた場合のみ処理 =====
                        if new_img is not None:
                            try:
                                raw = new_img.read()
                                if is_valid_image(raw):
                                    pil_img = Image.open(io.BytesIO(raw))
                                    pil_img.thumbnail((500, 500))

                                    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{new_img.name}"
                                    save_path = os.path.join(UPLOAD_DIR, fname)
                                    pil_img.save(save_path, format="JPEG", quality=75)

                                    new_image_path = save_path
                                else:
                                    st.warning("⚠️ 画像形式が不正です。元の画像を維持します。")
                            except Exception as e:
                                st.warning(f"⚠️ 画像更新失敗: {e}")

                        # ===== DB更新 =====
                        db_op(
                            """
                            UPDATE posts
                            SET fish = ?,
                                place = ?,
                                size = ?,
                                datetime = ?,
                                weather_desc = ?,
                                image_path = ?
                            WHERE id = ?
                            """,
                            (
                                fish,   # ← ②で追加した魚種入力
                                place,  # ← ③で追加した釣り場selectbox
                                size,
                                fish_time.strftime("%Y/%m/%d %H:%M"),
                                weather_desc,
                                new_image_path,
                                r["id"]
                            )
                        )

                        st.session_state.edit_post_id = None
                        get_posts.clear()
                        st.success("✅ 更新しました")
                        st.rerun()
                
                with col_cancel:
                    if st.button("❌ キャンセル", key=f"cancel_{r['id']}"):
                        st.session_state.edit_post_id = None
                        st.rerun()

                st.divider()
                st.markdown("### 🗑 投稿を削除")

                if st.button("🗑 この投稿を削除", key=f"del_{r['id']}"):
                    st.session_state.delete_confirm_id = r["id"]
                    st.rerun()

                if st.session_state.delete_confirm_id == r["id"]:
                    st.warning("⚠️ この投稿を完全に削除します。元に戻せません。")

                    col_yes, col_no = st.columns(2)

                    # ===== 本当に削除 =====                
                    with col_yes:
                        if st.button("❌ 削除する", key=f"confirm_del_{r['id']}"):

                            # ---- 画像ファイル削除 ----
                            img_path = r.get("image_path")
                            if img_path and os.path.exists(str(img_path)):
                                try:
                                    os.remove(img_path)
                                except Exception as e:
                                    st.warning(f"画像削除に失敗: {e}")

                            # ---- DB削除 ----
                            db_op("DELETE FROM posts WHERE id = ?", (r["id"],))

                            st.session_state.edit_post_id = None
                            st.session_state.delete_confirm_id = None
                            get_posts.clear()

                            st.success("🗑 投稿を削除しました")
                            st.rerun()

                    # ===== キャンセル =====
                    with col_no:
                        if st.button("↩ キャンセル", key=f"cancel_del_{r['id']}"):
                            st.session_state.delete_confirm_id = None
                            st.rerun()

            else:
                # ===== 自分の投稿だけ編集可能 =====
                if r["name"] == st.session_state.login_user:
                    if is_owner:
                        if st.button("✏️ 編集", key=f"edit_{r['id']}"):
                            st.session_state.edit_post_id = r["id"]
                            st.rerun()
                else:
                    st.caption("🔒 他のメンバーの投稿")

            c1, c2 = st.columns([1, 2])
            # 【パフォーマンス修正】ファイルパスから画像読み込み
            img_path = r.get("image_path") or r.get("image")  # 旧カラム名にも対応
            if img_path and os.path.exists(str(img_path)):
                c1.image(img_path)
            elif img_path and not img_path.startswith("/") and len(img_path) > 100:
                # 旧データ（Base64文字列）の後方互換表示
                try:
                    c1.image(base64.b64decode(img_path))
                except Exception:
                    pass
            with c2:
                st.subheader(f"{r['fish']} {r['size']}cm")
                st.write(f"📍 **{r['place']}** | 🌤 **{r.get('weather_desc','不明')}**")
                pres_str = f"{r['pressure']}hPa" if r['pressure'] else "取得失敗"
                st.write(f"👤 {r['name']} | 📅 {r['datetime']} | 🌡 {pres_str}")
                st.write(f"🌊 {r.get('tide','-')}")
                if st.button(f"👍 {r['likes']}", key=f"lk_{r['id']}"):
                    db_op("UPDATE posts SET likes=likes+1 WHERE id=?", (r['id'],))
                    get_posts.clear()
                    st.rerun()


def weather_page():
    st.title("🌤 港・地点情報 (気象庁JMA)")
    locs = get_locs()
    target = st.selectbox("地点を選択", list(locs.keys()))
    w = get_jma_weather(*locs[target])

    if w:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("天気", w["desc"])
        m2.metric("気温", f"{w['temp']}℃")
        m3.metric("風速", f"{w['wind_speed']}m/s")
        m4.metric("風向き", deg_to_win(w["wind_deg"]))
        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("🌅 日の出", w["sunrise"][11:16] if w["sunrise"] else "-")
        c2.metric("🌇 日没", w["sunset"][11:16] if w["sunset"] else "-")
    else:
        st.warning("⚠️ 天気情報を取得できませんでした。しばらくしてから再試行してください。")

    st.subheader("🌊 タイドグラフ (近似)")
    st.caption("※ 実際の潮汐とは異なります。正確な情報は気象庁潮位表をご確認ください。")
    st.line_chart([math.sin(h * (math.pi / 6.2)) for h in range(24)])


def point_page():
    st.title("📍 自由ポイント登録")
    if "lat" not in st.session_state:
        st.session_state.lat, st.session_state.lon = 39.74, 140.09
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=11, tiles="cartodbpositron")
    folium.Marker([st.session_state.lat, st.session_state.lon],
                  icon=folium.Icon(color="orange")).add_to(m)
    df_p = db_op("SELECT * FROM points", fetch=True)
    for _, p in df_p.iterrows():
        folium.Marker([p['lat'], p['lon']], tooltip=p['name']).add_to(m)
    res = st_folium(m, width="100%", height=450, returned_objects=["last_clicked"])
    if res and res.get("last_clicked"):
        st.session_state.lat = res["last_clicked"]["lat"]
        st.session_state.lon = res["last_clicked"]["lng"]
        st.rerun()
    with st.form("p_f"):
        name = st.text_input("ポイント名")
        memo = st.text_area("メモ")
        if st.form_submit_button("保存") and name:
            db_op("INSERT INTO points (name, memo, lat, lon) VALUES (?,?,?,?)",
                  (name, memo, st.session_state.lat, st.session_state.lon))
            st.rerun()


def analysis_page():
    st.title("📊 統計分析")
    df = db_op("SELECT * FROM posts", fetch=True)
    if not df.empty:
        st.plotly_chart(px.histogram(df, x="size", color="fish", title="サイズ分布"))


def admin_page():
    st.title("👥 メンバー管理")
    pw = st.text_input("管理者パスワード", type="password")

    # 【セキュリティ修正】パスワードをst.secretsまたは環境変数から取得
    # .streamlit/secrets.toml に admin_password = "your_password" を記載してください
    # secrets.toml が未設定の場合は環境変数 ADMIN_PASSWORD を使用します
    try:
        correct_pw = st.secrets["admin_password"]
    except (KeyError, FileNotFoundError):
        correct_pw = os.environ.get("ADMIN_PASSWORD", "")
        if not correct_pw:
            st.warning("⚠️ 管理者パスワードが設定されていません。"
                       "`.streamlit/secrets.toml` に `admin_password` を設定してください。")

    if pw and pw == correct_pw:
        with st.form("add_u"):
            u_id = st.text_input("学籍番号")
            u_name = st.text_input("名前")
            if st.form_submit_button("追加"):
                db_op("INSERT OR REPLACE INTO users (uid, name) VALUES (?,?)", (u_id, u_name))
                st.success("登録完了")
                st.rerun()
        df_u = db_op("SELECT * FROM users", fetch=True)
        for _, u in df_u.iterrows():
            c1, c2 = st.columns([3, 1])
            c1.write(f"{u['name']} ({u['uid']})")
            if c2.button("削除", key=u['uid']):
                db_op("DELETE FROM users WHERE uid=?", (u['uid'],))
                st.rerun()
    elif pw:
        st.error("パスワードが正しくありません。")

if "delete_confirm_id" not in st.session_state:
    st.session_state.delete_confirm_id = None

# ======================
# 4. メイン（ログイン制御）
# ======================
if "login_user" not in st.session_state:
    st.session_state.login_user = None

if st.session_state.login_user is None:
    st.title("🎣 釣り同好会ログイン")
    uid_input = st.text_input("学籍番号を入力してください")
    if st.button("ログイン"):
        user = db_op("SELECT name FROM users WHERE uid=?", (uid_input,), fetch=True)
        if not user.empty:
            st.session_state.login_user = user.iloc[0]["name"]
            st.rerun()
        else:
            st.error("未登録です。管理者に連絡してください。")
else:
    st.sidebar.title("🎣 メニュー")
    st.sidebar.write(f"Login: **{st.session_state.login_user}**")
    menu = st.sidebar.radio("機能", ["投稿管理", "港・地点情報", "自由ポイント", "統計分析", "メンバー管理"])
    if st.sidebar.button("ログアウト"):
        st.session_state.login_user = None
        st.rerun()
    # ===== 編集モード管理 =====
    if "edit_post_id" not in st.session_state:
        st.session_state.edit_post_id = None

    if menu == "投稿管理":
        post_page()
    elif menu == "港・地点情報":
        weather_page()
    elif menu == "自由ポイント":
        point_page()
    elif menu == "統計分析":
        analysis_page()
    elif menu == "メンバー管理":
        admin_page()