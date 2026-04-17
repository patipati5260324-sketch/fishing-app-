import requests
import math
import filetype
import io
import os
from PIL import Image
from datetime import datetime, timezone, timedelta
import streamlit as st

# 日本標準時 (JST)
JST = timezone(timedelta(hours=9))

# ======================
# 1. 天気・気象データ取得
# ======================
@st.cache_data(ttl=600)  # 10分間キャッシュ（API負荷軽減）
def get_jma_weather(lat, lon):
    """
    Open-Meteo APIを使用して、指定座標の気象データと日出/日没時間を取得します。
    """
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
        
        # JMA（気象庁）モデルが使えない場合のフォールバック
        if response.status_code == 400:
            params.pop("models")
            response = requests.get(url, params=params, timeout=10)
            
        if response.status_code != 200:
            return None
            
        res = response.json()
        curr = res.get("current", {})
        daily = res.get("daily", {})
        
        # WMO Weather interpretation codes (WW) を日本語に変換
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

# ======================
# 2. 釣行データ計算 (風向・月齢・潮汐)
# ======================
def deg_to_win(deg):
    """角度を16方位の漢字表記に変換します。"""
    if deg is None: return "-"
    labels = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
              "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    return labels[int((deg + 11.25) / 22.5) % 16]

def calc_moon_age(dt: datetime) -> float:
    """簡易的な月齢計算を行います（2000/1/6の新月基準）。"""
    base = datetime(2000, 1, 6)
    days = (dt - base).total_seconds() / 86400
    return round(days % 29.53, 1)

def calc_tide(moon_age: float) -> str:
    """月齢から簡易的な潮汐（大潮・中潮・小潮）を判定します。"""
    if moon_age < 2 or moon_age > 27:
        return "大潮"
    elif 5 < moon_age < 10 or 20 < moon_age < 25:
        return "中潮"
    else:
        return "小潮"

# ======================
# 3. 画像処理・バリデーション
# ======================
def is_valid_image(file_bytes: bytes) -> bool:
    """アップロードされたファイルのバイト列から、画像かどうかを判定します。"""
    kind = filetype.guess(file_bytes)
    return kind is not None and kind.mime.startswith("image/")

def process_and_save_image(img_file, upload_dir="./uploads"):
    """
    画像をリサイズ（最大500px）し、JPEG形式で保存して、そのパスを返します。
    """
    try:
        raw = img_file.read()
        if not is_valid_image(raw):
            return None
            
        pil_img = Image.open(io.BytesIO(raw))
        
        # 縦横比を維持したまま最大500pxにリサイズ
        pil_img.thumbnail((500, 500))
        
        # ファイル名を生成（日時＋元の名前）
        fname = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{img_file.name}"
        save_path = os.path.join(upload_dir, fname)
        
        # 保存実行
        pil_img.save(save_path, format="JPEG", quality=75)
        return save_path
    except Exception:
        return None