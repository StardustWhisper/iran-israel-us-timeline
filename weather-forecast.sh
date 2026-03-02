#!/usr/bin/env bash
set -euo pipefail

# 每日信息简报
# 可通过环境变量覆盖
# BRIEFING_CITY="大连市" BRIEFING_LAT=38.914 BRIEFING_LON=121.614 ./weather-forecast.sh

CITY="${BRIEFING_CITY:-大连市}"
LAT="${BRIEFING_LAT:-38.9140}"
LON="${BRIEFING_LON:-121.6147}"
TZ="${BRIEFING_TZ:-Asia/Shanghai}"

now="$(date '+%F %T')"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

WEATHER_JSON="$TMP_DIR/weather.json"
FX_JSON="$TMP_DIR/fx.json"
NEWS_XML="$TMP_DIR/news.xml"
SGE_LIST_HTML="$TMP_DIR/sge_list.html"
SGE_DETAIL_HTML="$TMP_DIR/sge_detail.html"

# 1) 天气
curl -fsSL "https://api.open-meteo.com/v1/forecast?latitude=${LAT}&longitude=${LON}&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=${TZ}&forecast_days=2" -o "$WEATHER_JSON"

# 2) 上海黄金交易所（主来源）
curl -fsSL "https://www.sge.com.cn/sjzx/mrhqsj" -o "$SGE_LIST_HTML" || true
SGE_PATH="$(grep -Eo '/sjzx/mrhqsj/[0-9]+' "$SGE_LIST_HTML" 2>/dev/null | head -n1 || true)"
if [[ -n "$SGE_PATH" ]]; then
  curl -fsSL "https://www.sge.com.cn${SGE_PATH}" -o "$SGE_DETAIL_HTML" || true
fi

# 3) 美元/人民币（轻量无 key）
curl -fsSL "https://open.er-api.com/v6/latest/USD" -o "$FX_JSON" || true

# 4) 国际要闻
curl -fsSL "https://news.google.com/rss/search?q=%E5%9B%BD%E9%99%85+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans" -o "$NEWS_XML" || true

python3 - "$CITY" "$now" "$WEATHER_JSON" "$FX_JSON" "$NEWS_XML" "$SGE_DETAIL_HTML" <<'PY'
import json
import re
import sys
from xml.etree import ElementTree as ET

city, now, weather_path, fx_path, news_path, sge_detail_path = sys.argv[1:]

code_map = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "冻雾",
    51: "毛毛雨", 53: "小雨", 55: "中雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "阵雪",
    80: "阵雨", 81: "阵雨", 82: "暴雨", 85: "阵雪", 86: "暴雪",
    95: "雷阵雨", 96: "雷阵雨夹冰雹", 99: "雷暴夹冰雹",
}

def r1(x):
    return f"{x:.1f}"

def fmt2(x):
    return f"{x:.2f}" if isinstance(x, (int, float)) else "--"

def parse_num(s):
    if s is None:
        return None
    s = s.replace(',', '').strip()
    try:
        return float(s)
    except Exception:
        return None

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
    else:
        avg = (hi + lo) / 2
        temp_line = f"🌡️ {r1(lo)}°C - {r1(hi)}°C (平均 {r1(avg)}°C)"

    weather_desc = code_map.get(code, "未知") if code is not None else "未知"
    rain_line = f"🌧️ 降雨概率: {int(rain)}%" if isinstance(rain, (int, float)) else "🌧️ 降雨概率: --"
    return date, temp_line, weather_desc, rain_line

today_date, today_temp, today_desc, today_rain = day_line(0)
tmr_date, tmr_temp, tmr_desc, _ = day_line(1)

# ----- finance from SGE -----
sge_gold = None          # Au99.99 收盘，元/克
sge_silver = None        # Ag99.99 或 Ag(T+D) 收盘（通常元/千克）
sge_silver_name = None

try:
    html = open(sge_detail_path, 'r', encoding='utf-8', errors='ignore').read()
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, flags=re.S | re.I)

    def clean(cell):
        cell = re.sub(r'<[^>]+>', '', cell)
        cell = cell.replace('&nbsp;', ' ').strip()
        return re.sub(r'\s+', ' ', cell)

    row_map = {}
    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, flags=re.S | re.I)
        if len(tds) < 5:
            continue
        vals = [clean(x) for x in tds]
        name = vals[0]
        row_map[name] = vals

    # 收盘价列：第5列（索引4）
    if 'Au99.99' in row_map:
        sge_gold = parse_num(row_map['Au99.99'][4])

    if 'Ag99.99' in row_map:
        sge_silver_name = 'Ag99.99'
        sge_silver = parse_num(row_map['Ag99.99'][4])
    elif 'Ag(T+D)' in row_map:
        sge_silver_name = 'Ag(T+D)'
        sge_silver = parse_num(row_map['Ag(T+D)'][4])
except Exception:
    pass

# 金银比（把白银按元/千克换算为元/克后再比）
ratio = None
if isinstance(sge_gold, (int, float)) and isinstance(sge_silver, (int, float)) and sge_silver:
    silver_per_g = sge_silver / 1000.0 if sge_silver > 100 else sge_silver
    if silver_per_g:
        ratio = sge_gold / silver_per_g

# USD/CNY
usdcny = None
try:
    with open(fx_path, 'r', encoding='utf-8') as f:
        fx = json.load(f)
    usdcny = fx.get('rates', {}).get('CNY')
except Exception:
    pass

# ----- news -----
news = []
try:
    tree = ET.parse(news_path)
    root = tree.getroot()
    items = root.findall('.//item')
    for it in items:
        title = (it.findtext('title') or '').strip()
        if not title:
            continue
        if ' - ' in title:
            title = title.rsplit(' - ', 1)[0].strip()
        if title and title not in news and title != '国际':
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
print(f"🏆 上海金交所 Au99.99: {fmt2(sge_gold)} 元/克")
if sge_silver_name:
    print(f"🥈 上海金交所 {sge_silver_name}: {fmt2(sge_silver)} 元/千克")
else:
    print(f"🥈 上海金交所白银: --")
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
