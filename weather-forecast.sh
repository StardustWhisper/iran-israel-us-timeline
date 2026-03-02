#!/usr/bin/env bash
set -euo pipefail

# 每日信息简报（免 key 版）
# 可通过环境变量覆盖
# BRIEFING_CITY="大连市" BRIEFING_LAT=38.914 BRIEFING_LON=121.614 ./weather-forecast.sh

CITY="${BRIEFING_CITY:-大连市}"
LAT="${BRIEFING_LAT:-38.9140}"
LON="${BRIEFING_LON:-121.6147}"
TZ="${BRIEFING_TZ:-Asia/Shanghai}"

now="$(date '+%F %T')"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

weather_json="$tmp_dir/weather.json"
finance_json="$tmp_dir/finance.json"
news_xml="$tmp_dir/news.xml"

curl -fsSL "https://api.open-meteo.com/v1/forecast?latitude=${LAT}&longitude=${LON}&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=${TZ}&forecast_days=2" -o "$weather_json"

curl -fsSL "https://query1.finance.yahoo.com/v7/finance/quote?symbols=GC%3DF,SI%3DF,CNY%3DX" -o "$finance_json" || true
curl -fsSL "https://news.google.com/rss/search?q=%E5%9B%BD%E9%99%85+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans" -o "$news_xml" || true

python3 - "$CITY" "$now" "$weather_json" "$finance_json" "$news_xml" <<'PY'
import json
import math
import sys
from xml.etree import ElementTree as ET

city, now, weather_path, finance_path, news_path = sys.argv[1:]

code_map = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "冻雾",
    51: "毛毛雨",
    53: "小雨",
    55: "中雨",
    56: "冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "阵雪",
    80: "阵雨",
    81: "阵雨",
    82: "暴雨",
    85: "阵雪",
    86: "暴雪",
    95: "雷阵雨",
    96: "雷阵雨夹冰雹",
    99: "雷暴夹冰雹",
}

def r1(x):
    return f"{x:.1f}"

# ----- weather -----
with open(weather_path, "r", encoding="utf-8") as f:
    w = json.load(f)

d = w.get("daily", {})
dates = d.get("time", ["--", "--"])
tmax = d.get("temperature_2m_max", [None, None])
tmin = d.get("temperature_2m_min", [None, None])
wc = d.get("weather_code", [None, None])
pp = d.get("precipitation_probability_max", [None, None])

def day_line(i):
    date = dates[i] if i < len(dates) else "--"
    hi = tmax[i] if i < len(tmax) else None
    lo = tmin[i] if i < len(tmin) else None
    code = wc[i] if i < len(wc) else None
    rain = pp[i] if i < len(pp) else None

    if hi is None or lo is None:
        temp_line = "🌡️ --"
        avg_line = ""
    else:
        avg = (hi + lo) / 2
        temp_line = f"🌡️ {r1(lo)}°C - {r1(hi)}°C (平均 {r1(avg)}°C)"
        avg_line = ""

    weather_desc = code_map.get(code, "未知") if code is not None else "未知"
    rain_line = f"🌧️ 降雨概率: {int(rain)}%" if isinstance(rain, (int, float)) else "🌧️ 降雨概率: --"

    return date, temp_line, weather_desc, rain_line

today_date, today_temp, today_desc, today_rain = day_line(0)
tmr_date, tmr_temp, tmr_desc, _ = day_line(1)

# ----- finance -----
gold = silver = usdcny = None
try:
    with open(finance_path, "r", encoding="utf-8") as f:
        fj = json.load(f)
    results = fj.get("quoteResponse", {}).get("result", [])
    by_symbol = {x.get("symbol"): x for x in results}
    gold = by_symbol.get("GC=F", {}).get("regularMarketPrice")
    silver = by_symbol.get("SI=F", {}).get("regularMarketPrice")
    usdcny = by_symbol.get("CNY=X", {}).get("regularMarketPrice")
except Exception:
    pass

ratio = None
if isinstance(gold, (int, float)) and isinstance(silver, (int, float)) and silver:
    ratio = gold / silver

fmt2 = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else "--"

# ----- news -----
news = []
try:
    tree = ET.parse(news_path)
    root = tree.getroot()
    items = root.findall(".//item")
    for it in items:
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        # 去掉来源后缀："xxx - 来源"
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        if title and title not in news:
            news.append(title)
        if len(news) >= 5:
            break
except Exception:
    pass

if not news:
    news = ["暂无可用国际要闻（网络源暂不可达）"]

# ----- output -----
print("📰 每日信息简报")
print(f"📍 地点: {city}")
print(f"🕐 更新时间: {now}")
print()
print("🌤️ 天气预报")
print(f"📅 今天 ({today_date})")
print(today_temp)
print(f"☁️ {today_desc}")
print(today_rain)
print()
print("💰 财经信息")
print(f"🏆 国际黄金: {fmt2(gold)} USD/盎司")
print(f"🥈 国际白银: {fmt2(silver)} USD/盎司")
print(f"⚖️ 金银比: {fmt2(ratio)}")
print(f"💵 美元/人民币: {fmt2(usdcny)}")
print()
print("🌍 国际要闻 (24小时)")
for i, t in enumerate(news, 1):
    print(f"• {i}. {t}")
print()
print(f"📅 明天 ({tmr_date})")
print(tmr_temp if tmr_temp else "🌡️ --")
print(f"☁️ {tmr_desc}")
print()
print("💡 建议")
print("• 根据天气情况合理安排出行")
print("• 关注国际动态，把握市场机会")
PY
