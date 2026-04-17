import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
import os, io, base64
from datetime import datetime
from PIL import Image

# 自作モジュールからのインポート
from database import db_op, get_posts_from_db
from utils import (
    get_jma_weather, calc_moon_age, calc_tide, 
    process_and_save_image, JST, is_valid_image
)

# 固定の釣り場データ
BASE_COORDS = {
    "秋田港": [39.74, 140.09], "男鹿港": [39.90, 139.85], "船川港": [39.89, 139.84],
    "能代港": [40.21, 140.02], "本荘マリーナ": [39.38, 140.05]
}

def get_locs():
    """固定の釣り場と、ユーザーが登録したポイントを合流させて返します。"""
    locs = BASE_COORDS.copy()
    df_p = db_op("SELECT name, lat, lon FROM points", fetch=True)
    for _, r in df_p.iterrows():
        locs[r['name']] = [r['lat'], r['lon']]
    return locs

def post_page():
    st.title("🎣 釣果投稿・マップ")
    locs = get_locs()
    
    # 画面を左（投稿フォーム）と右（マップ）に分割
    col_in, col_map = st.columns([1, 1])

    # ======================
    # 1. 新規投稿フォーム (左側)
    # ======================
    with col_in:
        with st.expander("✨ 新規投稿", expanded=True):
            fish = st.text_input("魚種", placeholder="例: シーバス")
            
            st.subheader("🕒 釣行時刻")
            use_now = st.checkbox("現在時刻を使う", value=True)
            if use_now:
                fish_time = datetime.now(JST)
            else:
                d = st.date_input("日付", value=datetime.now(JST).date())
                t = st.time_input("時刻", value=datetime.now(JST).time())
                fish_time = datetime.combine(d, t)

            size = st.number_input("サイズ(cm)", min_value=0, step=1)
            place = st.selectbox("釣り場", list(locs.keys()))
            img = st.file_uploader("写真", type=["jpg", "png", "jpeg"])

            # 選択された場所の現在の天気をプレビュー表示
            w_now = get_jma_weather(*locs[place])
            if w_now:
                st.caption(f"現在の現地の天気: {w_now['desc']} ({w_now['pressure']}hPa)")
            else:
                st.caption("⚠️ 天気情報を取得できませんでした（投稿は可能です）")

            if st.button("投稿を完了", use_container_width=True):
                if not fish:
                    st.error("魚種を入力してください")
                else:
                    # 画像の処理
                    image_path = process_and_save_image(img) if img else ""
                    
                    # 気象・潮汐データの準備
                    pres = w_now['pressure'] if w_now else None
                    w_desc = w_now['desc'] if w_now else "取得失敗"
                    moon_age = calc_moon_age(fish_time)
                    tide = calc_tide(moon_age)

                    # DBへ保存
                    db_op(
                        """
                        INSERT INTO posts (
                            datetime, name, fish, size, place, 
                            image_path, pressure, weather_desc, tide, moon_age
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            fish_time.strftime("%Y/%m/%d %H:%M"),
                            st.session_state.login_user,
                            fish, size, place, image_path,
                            pres, w_desc, tide, moon_age
                        )
                    )
                    # キャッシュをクリアして再読み込み
                    st.cache_data.clear()
                    st.success("投稿しました！")
                    st.rerun()

    # ======================
    # 2. 釣り場マップ (右側)
    # ======================
    # 最新50件のデータを取得
    df = get_posts_from_db(limit=50)

    with col_map:
        # 秋田県中心付近のマップを作成
        m = folium.Map(location=[39.75, 140.0], zoom_start=8, tiles="cartodbpositron")
        marker_cluster = MarkerCluster(name="釣果詳細").add_to(m)
        
        for _, r in df.iterrows():
            if r["place"] in locs:
                popup_html = (
                    f"<b>📍 {r['place']}</b><br>"
                    f"🐟 {r['fish']} ({r['size']}cm)<br>"
                    f"🌤 {r.get('weather_desc','-')}<br>"
                    f"👤 {r['name']}"
                )
                folium.Marker(
                    location=locs[r["place"]],
                    popup=folium.Popup(popup_html, max_width=200),
                    icon=folium.Icon(color="blue", icon="fish", prefix="fa")
                ).add_to(marker_cluster)
        
        st_folium(m, width="100%", height=500, key="main_map")

    # ======================
    # 3. タイムライン表示 (下部)
    # ======================
    st.divider()
    st.subheader("最新の釣果タイムライン")
    
    if df.empty:
        st.write("まだ投稿がありません。最初の釣果を投稿しましょう！")
    else:
        for _, r in df.iterrows():
            with st.container(border=True):
                # 自分の投稿かどうかの判定
                is_owner = (r["name"] == st.session_state.login_user)
                
                # 投稿のレイアウト (左に画像、右に詳細テキスト)
                c_img, c_txt = st.columns([1, 2])
                
                with c_img:
                    img_path = r.get("image_path")
                    if img_path and os.path.exists(str(img_path)):
                        st.image(img_path, use_container_width=True)
                    else:
                        st.caption("No Image")

                with c_txt:
                    st.markdown(f"### {r['fish']} {r['size']}cm")
                    st.write(f"📍 **{r['place']}** | 🌤 **{r.get('weather_desc','不明')}**")
                    st.write(f"👤 {r['name']} | 📅 {r['datetime']}")
                    st.write(f"🌊 {r.get('tide','-')} (月齢: {r.get('moon_age','-')}) | 🌡 {r.get('pressure','-')}hPa")
                    
                    # いいねボタン
                    if st.button(f"👍 {r['likes']}", key=f"lk_{r['id']}"):
                        db_op("UPDATE posts SET likes=likes+1 WHERE id=?", (r['id'],))
                        st.cache_data.clear()
                        st.rerun()

                # 自分の投稿なら編集ボタンを表示（機能は後ほど追加）
                if is_owner:
                    st.caption("🟢 あなたの投稿です")

                # --- 編集・削除ロジック ---
                if is_owner:
                    # 現在の投稿が「編集モード」かどうかを判定
                    if st.session_state.edit_post_id == r["id"]:
                        st.markdown("---")
                        st.subheader("✏️ 投稿を編集")
                        
                        edit_fish = st.text_input("魚種", value=r["fish"], key=f"ef_{r['id']}")
                        edit_size = st.number_input("サイズ(cm)", value=int(r["size"]), min_value=0, key=f"es_{r['id']}")
                        edit_place = st.selectbox("釣り場", list(locs.keys()), 
                                                index=list(locs.keys()).index(r["place"]) if r["place"] in locs else 0,
                                                key=f"ep_{r['id']}")
                        
                        st.markdown("##### 🕒 釣行時刻の修正")
                        # 既存の日時をパースしてデフォルト値にする
                        try:
                            current_dt = datetime.strptime(r["datetime"], "%Y/%m/%d %H:%M")
                        except:
                            current_dt = datetime.now()
                            
                        ed = st.date_input("日付", value=current_dt.date(), key=f"ed_{r['id']}")
                        et = st.time_input("時刻", value=current_dt.time(), key=f"et_{r['id']}")
                        edit_time = datetime.combine(ed, et)

                        edit_weather = st.text_input("天気メモ", value=r["weather_desc"], key=f"ew_{r['id']}")
                        
                        st.markdown("##### 🖼 写真の変更")
                        new_img = st.file_uploader("新しい写真（変更しない場合は空欄）", type=["jpg", "jpeg", "png"], key=f"ei_{r['id']}")

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.button("💾 変更を保存", key=f"save_{r['id']}", use_container_width=True):
                                # 新しい画像がある場合は保存、なければ旧パスを維持
                                updated_image_path = r["image_path"]
                                if new_img:
                                    # 古いファイルを削除（任意ですがストレージ節約のため）
                                    if r["image_path"] and os.path.exists(str(r["image_path"])):
                                        try: os.remove(r["image_path"])
                                        except: pass
                                    updated_image_path = process_and_save_image(new_img)
                                
                                # DB更新
                                db_op(
                                    """
                                    UPDATE posts SET fish=?, size=?, place=?, datetime=?, weather_desc=?, image_path=?
                                    WHERE id=?
                                    """,
                                    (edit_fish, edit_size, edit_place, edit_time.strftime("%Y/%m/%d %H:%M"), 
                                     edit_weather, updated_image_path, r["id"])
                                )
                                st.session_state.edit_post_id = None
                                st.cache_data.clear()
                                st.success("更新しました")
                                st.rerun()

                        with col_cancel:
                            if st.button("❌ キャンセル", key=f"can_{r['id']}", use_container_width=True):
                                st.session_state.edit_post_id = None
                                st.rerun()

                        # --- 削除セクション ---
                        st.divider()
                        if st.button("🗑 この投稿を削除する", key=f"del_btn_{r['id']}", type="secondary"):
                            st.session_state.delete_confirm_id = r["id"]
                        
                        if st.session_state.delete_confirm_id == r["id"]:
                            st.error("⚠️ 本当に削除しますか？この操作は取り消せません。")
                            c_yes, c_no = st.columns(2)
                            with c_yes:
                                if st.button("🔥 完全に削除", key=f"conf_del_{r['id']}", use_container_width=True):
                                    # 画像ファイルの削除
                                    if r["image_path"] and os.path.exists(str(r["image_path"])):
                                        try: os.remove(r["image_path"])
                                        except: pass
                                    # DBレコードの削除
                                    db_op("DELETE FROM posts WHERE id=?", (r["id"],))
                                    st.session_state.edit_post_id = None
                                    st.session_state.delete_confirm_id = None
                                    st.cache_data.clear()
                                    st.rerun()
                            with c_no:
                                if st.button("🔙 戻る", key=f"back_del_{r['id']}", use_container_width=True):
                                    st.session_state.delete_confirm_id = None
                                    st.rerun()

                    else:
                        # 通常時（編集モードでない時）
                        if st.button("✏️ 編集・削除", key=f"edit_btn_{r['id']}"):
                            st.session_state.edit_post_id = r["id"]
                            st.rerun()


from utils import deg_to_win # 16方位変換関数をインポートに追加してください

def weather_page():
    st.title("🌊 港・地点別コンディション")
    st.write("各地点の最新の気象情報と日出・日没時間を確認できます。")
    
    locs = get_locs() # database.pyで取得した地点リスト
    
    # 画面をグリッド状に配置（3列）
    cols = st.columns(3)
    
    for i, (name, coords) in enumerate(locs.items()):
        # 列のインデックス（0, 1, 2）を計算して配置
        with cols[i % 3]:
            with st.container(border=True):
                st.subheader(f"📍 {name}")
                
                # 天気APIからデータを取得
                w = get_jma_weather(coords[0], coords[1])
                
                if w:
                    # 1. 天気と気温
                    st.write(f"### {w['desc']}")
                    st.metric("気温", f"{w['temp']}°C")
                    
                    # 2. 風の情報（風速と16方位）
                    wind_label = deg_to_win(w['wind_deg'])
                    st.write(f"💨 **風:** {wind_label} {w['wind_speed']}m/s")
                    
                    # 3. 気圧
                    st.write(f"🌡 **気圧:** {w['pressure']}hPa")
                    
                    st.divider()
                    
                    # 4. 日出・日没（時間の文字列から時刻部分だけ抽出）
                    try:
                        sr = datetime.fromisoformat(w['sunrise']).strftime("%H:%M")
                        ss = datetime.fromisoformat(w['sunset']).strftime("%H:%M")
                        st.write(f"🌅 **日出:** {sr} | 🌇 **日没:** {ss}")
                    except:
                        st.write("🌅 **日出/日没:** データ取得不可")
                else:
                    st.error("天気データが取得できませんでした。")
                    
                # 地図へのリンク（任意）
                google_map_url = f"https://www.google.com/maps?q={coords[0]},{coords[1]}"
                st.link_button(f"🔗 {name}を地図で見る", google_map_url)

# --- ここで views.py の中身が一旦完成です ---


def point_page():
    st.title("📍 新規ポイント登録")
    st.write("地図をクリックするとピンが移動し、右側のフォームに座標が反映されます。")

    # --- セッション状態の管理 ---
    if "center_lat" not in st.session_state:
        st.session_state.center_lat = 39.75
    if "center_lon" not in st.session_state:
        st.session_state.center_lon = 140.0
    if "zoom_level" not in st.session_state:
        st.session_state.zoom_level = 9

    col_map, col_form = st.columns([2, 1])

    with col_map:
        m = folium.Map(
            location=[st.session_state.center_lat, st.session_state.center_lon], 
            zoom_start=st.session_state.zoom_level,
            control_scale=True
        )
        
        # 選択中のピンを表示
        folium.Marker(
            [st.session_state.center_lat, st.session_state.center_lon],
            icon=folium.Icon(color="red", icon="crosshair", prefix="fa")
        ).add_to(m)

        # クリックイベントのみを確実に取得
        map_data = st_folium(
            m, 
            width="100%", 
            height=500, 
            key="fishing_point_map",
            returned_objects=["last_clicked", "zoom"] # 必要なものに絞って高速化
        )

        # --- ここが重要：ワンタップで反映させるロジック ---
        if map_data and map_data.get("last_clicked"):
            new_lat = map_data["last_clicked"]["lat"]
            new_lon = map_data["last_clicked"]["lng"]
            
            # 座標が今のセッションと違う場合のみ、書き換えて再描画
            if new_lat != st.session_state.center_lat or new_lon != st.session_state.center_lon:
                st.session_state.center_lat = new_lat
                st.session_state.center_lon = new_lon
                # ズーム倍率も今の状態をキープ
                if map_data.get("zoom"):
                    st.session_state.zoom_level = map_data["zoom"]
                # 強制的に再描画することで、右側のフォームと地図のピンを更新
                st.rerun()

    with col_form:
        st.subheader("地点情報の入力")
        new_name = st.text_input("地点名", placeholder="例: 秋田港セリオン裏")
        
        # 地図の座標を直接反映
        lat = st.number_input("緯度", value=st.session_state.center_lat, format="%.6f")
        lon = st.number_input("経度", value=st.session_state.center_lon, format="%.6f")
        memo = st.text_area("メモ", placeholder="駐車場情報など")
        
        if st.button("この場所を保存する", use_container_width=True, type="primary"):
            if not new_name:
                st.error("地点名を入力してください")
            else:
                from database import db_op
                db_op("INSERT INTO points (name, lat, lon, memo) VALUES (?,?,?,?)", (new_name, lat, lon, memo))
                st.success(f"「{new_name}」を登録しました！")
                st.cache_data.clear()
                st.rerun()

    # --- 登録済みリスト & 削除機能 ---
    st.divider()
    from database import get_registered_points
    points_df = get_registered_points()
    if not points_df.empty:
        with st.expander("📋 登録済みポイント一覧"):
            st.dataframe(points_df[["name", "lat", "lon", "memo"]], use_container_width=True, hide_index=True)
            
            # 削除機能もここに入れておくと便利です
            del_target = st.selectbox("削除するポイント", points_df["name"].tolist())
            if st.button("選択したポイントを削除"):
                from database import db_op
                db_op("DELETE FROM points WHERE name=?", (del_target,))
                st.rerun()

# views.py の末尾に追記

def analysis_page():
    st.title("📊 釣果統計分析")
    
    # データを取得
    df = get_posts_from_db(limit=1000)
    
    if df.empty:
        st.warning("データが不足しているため分析できません。")
        return

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🐟 魚種別投稿数")
        fish_counts = df["fish"].value_counts()
        st.bar_chart(fish_counts)

    with col2:
        st.subheader("🏆 サイズランキング (TOP10)")
        ranking = df.sort_values(by="size", ascending=False).head(10)
        st.table(ranking[["fish", "size", "name", "place"]])

    st.divider()
    st.subheader("📈 潮汐・気圧とサイズの相関")
    st.scatter_chart(data=df, x="pressure", y="size", color="tide")

def admin_page():
    st.title("👥 メンバー・システム管理")
    
    # --- パスワードチェック ---
    # セッションで認証状態を保持
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    if not st.session_state.admin_authenticated:
        st.warning("この操作には管理者権限が必要です。")
        admin_password = st.text_input("管理者パスワードを入力してください", type="password")
        if st.button("認証"):
            # ここでパスワードを設定（自由に変更してください）
            if admin_password == "7023911":
                st.session_state.admin_authenticated = True
                st.success("認証に成功しました！")
                st.rerun()
            else:
                st.error("パスワードが正しくありません。")
        return # 認証されるまでこれ以降のコードは実行されない

    # --- 認証成功後の表示 ---
    st.sidebar.info("🔓 管理者認証済み")
    if st.sidebar.button("管理者ログアウト"):
        st.session_state.admin_authenticated = False
        st.rerun()

    tab1, tab2 = st.tabs(["メンバー登録", "データ管理"])
    
    with tab1:
        st.subheader("➕ 新規メンバー追加")
        with st.form("add_user_form", clear_on_submit=True):
            u_id = st.text_input("学籍番号 (UID)")
            u_name = st.text_input("氏名")
            if st.form_submit_button("登録"):
                if u_id and u_name:
                    db_op("INSERT OR REPLACE INTO users (uid, name) VALUES (?, ?)", (u_id, u_name))
                    st.success(f"「{u_name}」さんを登録しました。")
                else:
                    st.error("入力が不足しています。")
        
        st.subheader("📋 メンバー一覧")
        users = db_op("SELECT * FROM users", fetch=True)
        st.dataframe(users, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("⚙️ メンテナンス")
        if st.button("全データを再読み込み（キャッシュクリア）"):
            st.cache_data.clear()
            st.success("キャッシュをクリアしました。")