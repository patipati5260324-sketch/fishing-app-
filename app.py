import streamlit as st
from database import init_db, db_op, get_user_by_id
# views.py から作成した各画面の関数をインポート
from views import post_page, weather_page, point_page

# app.py の上の方を以下に書き換えてください

# ======================
# 1. ページ全体の初期設定
# ======================
st.set_page_config(
    page_title="秋田釣り同好会 Portal", 
    page_icon="🎣", 
    layout="wide",
    initial_sidebar_state="expanded"  # ←ここを "expanded" に変更
)

# 一旦、サイドバーまで消してしまう恐れのあるCSSをコメントアウト、または削除します
st.markdown("""
<style>
/* #MainMenu {visibility: hidden;}
header {visibility: hidden;}  <-- これがボタンを消している犯人の可能性が高いです
footer {visibility: hidden;}
*/
.block-container {padding-top: 2rem; padding-bottom: 1rem;}
</style>
""", unsafe_allow_html=True)
# データベースの初期化を実行
init_db()

# ======================
# 2. セッション状態の初期化
# ======================
if "login_user" not in st.session_state:
    st.session_state.login_user = None

if "edit_post_id" not in st.session_state:
    st.session_state.edit_post_id = None

if "delete_confirm_id" not in st.session_state:
    st.session_state.delete_confirm_id = None

# ======================
# 3. ログインチェックと画面分岐
# ======================
if st.session_state.login_user is None:
    # --- ログイン画面 ---
    st.title("🎣 秋田釣り同好会 Portal")
    st.subheader("ログイン")
    
    with st.container(border=True):
        uid_input = st.text_input("学籍番号を入力してください", placeholder="例: 7023911")
        if st.button("ログインする", use_container_width=True):
            if uid_input:
                user_df = get_user_by_id(uid_input)
                if not user_df.empty:
                    st.session_state.login_user = user_df.iloc[0]["name"]
                    st.rerun()
                else:
                    st.error("未登録の学籍番号です。管理者に連絡してください。")
            else:
                st.warning("学籍番号を入力してください。")
else:
    # --- ログイン後のメインアプリ画面 ---
    
    # 1. サイドバーメニュー
    st.sidebar.title("🎣 Menu")
    st.sidebar.write(f"USER: **{st.session_state.login_user}**")
    st.sidebar.divider()
    
    menu = st.sidebar.radio(
        "機能を選択", 
        ["投稿管理", "港・地点情報", "ポイント登録", "分析", "メンバー管理"],
        index=0
    )
    
    st.sidebar.divider()
    if st.sidebar.button("ログアウト", use_container_width=True):
        st.session_state.login_user = None
        st.rerun()

    # app.py の下部（メニュー切り替え部分）を以下に差し替え

    # --- 2. メインエリア ---
    from views import analysis_page, admin_page # インポートを忘れずに
    
    if menu == "投稿管理":
        post_page()
        
    elif menu == "港・地点情報":
        weather_page()
        
    elif menu == "ポイント登録":
        point_page()
        
    elif menu == "分析":
        analysis_page()
        
    elif menu == "メンバー管理":
        admin_page()

        st.header("📊 釣果統計分析")
        st.info("現在準備中です。月別の釣果数や魚種別サイズランキングを表示予定です。")
        # ここに今後 analysis_page() を追加
        
    elif menu == "メンバー管理":
        st.header("👥 メンバー管理")
        st.write("新規メンバー（学籍番号）の登録や、名前の変更を行います。")
        
        # 簡易的なメンバー追加フォーム
        with st.expander("➕ 新規メンバー登録"):
            new_uid = st.text_input("学籍番号")
            new_name = st.text_input("氏名")
            if st.button("登録"):
                if new_uid and new_name:
                    db_op("INSERT INTO users (uid, name) VALUES (?, ?)", (new_uid, new_name))
                    st.success(f"{new_name}さんを登録しました")
                else:
                    st.error("入力が不足しています")