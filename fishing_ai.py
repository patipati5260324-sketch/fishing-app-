from datetime import datetime


def calc_moon_age(dt: datetime) -> float:
    base = datetime(2000, 1, 6)
    days = (dt - base).total_seconds() / 86400
    return round(days % 29.53, 1)

def calc_tide(moon_age: float) -> str:
    if moon_age < 2 or moon_age > 27:
        return "大潮"
    elif 5 < moon_age < 10 or 20 < moon_age < 25:
        return "中潮"
    else:
        return "小潮"

def fish_score(weather, tide):
    """
    釣れやすさ指数（暫定ルール）
    0〜100
    """
    score = 50

    # 天気
    if weather in ["快晴", "晴れ"]:
        score += 10
    elif weather in ["雨", "強い雨"]:
        score -= 10

    # 潮
    if tide == "大潮":
        score += 20
    elif tide == "小潮":
        score -= 10

    return max(0, min(100, score))