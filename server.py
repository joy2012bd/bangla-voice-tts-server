import os
import time
import tempfile
import requests
from flask import Flask, request, send_file, jsonify
from gtts import gTTS
from datetime import datetime, timedelta
import pytz
import bangla
import json

app = Flask(__name__)

# Config
OPENWEATHER_KEY = os.getenv("OPENWEATHER_API_KEY", "8c04437c21dcdcddace4e76e5c850dd7")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
_cache = {}

# Load Json
with open("ekadashis_2025.json", "r", encoding="utf-8") as f:
    ekadashis_2025 = json.load(f)

def cache_get(key):
    v = _cache.get(key)
    if not v: return None
    ts, data = v
    if time.time() - ts > CACHE_TTL:
        del _cache[key]
        return None
    return data

def cache_set(key, data):
    _cache[key] = (time.time(), data)

def tts_bangla(text, cache_key):
    """Generate Bengali TTS with cache"""
    cached = cache_get(cache_key)
    if cached:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.write(cached)
        tmp.flush()
        tmp.close()
        return send_file(tmp.name, mimetype="audio/mpeg", as_attachment=False)

    tts = gTTS(text=text, lang="bn")
    tmp_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp_name = tmp_fp.name
    tmp_fp.close()
    tts.save(tmp_name)
    with open(tmp_name, "rb") as f:
        data = f.read()
    cache_set(cache_key, data)
    return send_file(tmp_name, mimetype="audio/mpeg", as_attachment=False)


@app.route("/weather")
def weather_tts():
    """Weather + 3-day forecast Bengali TTS"""
    city = request.args.get("city", "Dhaka")
    units = request.args.get("units", "metric")
    cache_key = f"weather::{city}::{units}"

    cached_audio = cache_get(cache_key)
    if cached_audio:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.write(cached_audio)
        tmp.flush()
        tmp.close()
        return send_file(tmp.name, mimetype="audio/mpeg", as_attachment=False)

    if not OPENWEATHER_KEY:
        return jsonify({"error": "OPENWEATHER_API_KEY missing"}), 500

    # --- current weather ---
    url_now = "https://api.openweathermap.org/data/2.5/weather"
    params_now = {"q": city, "appid": OPENWEATHER_KEY, "units": units, "lang": "en"}
    resp_now = requests.get(url_now, params=params_now, timeout=10)
    if resp_now.status_code != 200:
        return jsonify({"error": "weather api failed", "detail": resp_now.text}), 502
    now = resp_now.json()
    temp = now["main"]["temp"]
    desc = now["weather"][0]["description"]

    # small translation map
    desc_map = {
        "clear sky": "পরিষ্কার আকাশ",
        "few clouds": "কিছু মেঘ",
        "scattered clouds": "বিক্ষিপ্ত মেঘ",
        "broken clouds": "আংশিক মেঘলা",
        "overcast clouds": "সম্পূর্ণ মেঘলা",
        "light rain": "হালকা বৃষ্টি",
        "moderate rain": "মাঝারি বৃষ্টি",
        "heavy rain": "তীব্র বৃষ্টি",
        "thunderstorm": "বজ্রসহ বৃষ্টি"
    }
    for en, bn in desc_map.items():
        if en in desc.lower():
            desc = bn
            break

    # --- forecast (next 3 days) ---
    url_forecast = "https://api.openweathermap.org/data/2.5/forecast"
    params_fore = {"q": city, "appid": OPENWEATHER_KEY, "units": units}
    resp_fore = requests.get(url_forecast, params=params_fore, timeout=10)
    if resp_fore.status_code == 200:
        fore = resp_fore.json()
        temps = []
        rains = 0
        for item in fore["list"][:24*3//3]:  # next 3 days (3h intervals)
            temps.append(item["main"]["temp"])
            if "rain" in item:
                rains += 1
        avg_temp = sum(temps)/len(temps)
        rain_msg = (
            "আগামী তিন দিনে বৃষ্টি হবার সম্ভাবনা আছে।" if rains > 0 else
            "আগামী তিন দিনে বৃষ্টি হবার সম্ভাবনা নেই।"
        )
        temp_trend = (
            "তাপমাত্রা কিছুটা বাড়তে পারে।" if avg_temp > temp + 2 else
            "তাপমাত্রা কিছুটা কমতে পারে।" if avg_temp < temp - 2 else
            "তাপমাত্রা প্রায় একই থাকবে।"
        )
        forecast_text = f"{rain_msg} {temp_trend}"
    else:
        forecast_text = "আগামী তিন দিনের পূর্বাভাস পাওয়া যায়নি।"

    # --- final text ---
    text = f"আজকের আবহাওয়া। এই মুহুর্তে {city} এ তাপমাত্রা {round(temp)} ডিগ্রি সেলসিয়াস। অবস্থা: {desc}। {forecast_text}"

    tts = gTTS(text=text, lang="bn")
    tmp_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp_name = tmp_fp.name
    tmp_fp.close()
    tts.save(tmp_name)
    with open(tmp_name, "rb") as f:
        data = f.read()
    cache_set(cache_key, data)

    return send_file(tmp_name, mimetype="audio/mpeg", as_attachment=False)

@app.route("/bangla-date-time")
def bangla_date_time():
    """আজকের বাংলা তারিখ, দিন ও সময় বলে (সংশোধিত সংস্করণ)"""
    tz = pytz.timezone("Asia/Dhaka")
    now = datetime.now(tz)

    # Benglai days name
    bn_day_name = {
        "Saturday": "শনিবার",
        "Sunday": "রবিবার",
        "Monday": "সোমবার",
        "Tuesday": "মঙ্গলবার",
        "Wednesday": "বুধবার",
        "Thursday": "বৃহস্পতিবার",
        "Friday": "শুক্রবার",
    }[now.strftime("%A")]

    # --- Calculation correct benglai time ---
    g_date = now.date()
    if g_date >= datetime(g_date.year, 4, 14).date():
        bangla_year = g_date.year - 593
        new_year_start = datetime(g_date.year, 4, 14).date()
    else:
        bangla_year = g_date.year - 594
        new_year_start = datetime(g_date.year - 1, 4, 14).date()

    bangla_months = [
        ("বৈশাখ", 31),
        ("জ্যৈষ্ঠ", 31),
        ("আষাঢ়", 31),
        ("শ্রাবণ", 31),
        ("ভাদ্র", 31),
        ("আশ্বিন", 30),
        ("কার্তিক", 30),
        ("অগ্রহায়ণ", 30),
        ("পৌষ", 30),
        ("মাঘ", 30),
        ("ফাল্গুন", 29),
        ("চৈত্র", 30)
    ]

    delta_days = (g_date - new_year_start).days
    month_index = 0
    for i, (_, days_in_month) in enumerate(bangla_months):
        if delta_days < days_in_month:
            month_index = i
            break
        delta_days -= days_in_month

    bangla_day = delta_days + 1
    bangla_month = bangla_months[month_index][0]

    # Convert int to bengali
    def to_bn_digits(s: str) -> str:
        return s.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))

    bn_day = to_bn_digits(str(bangla_day-1)) # To fix wtih indian time
    bn_year = to_bn_digits(str(bangla_year))

    # 🕒 Time in Bengali
    hour = now.hour
    minute = now.minute
    period = "রাত" if hour < 4 else "ভোর" if hour < 6 else "সকাল" if hour < 12 else "দুপুর" if hour < 16 else "বিকেল" if hour < 18 else "সন্ধ্যা" if hour < 20 else "রাত"
    hour_12 = hour % 12 or 12

    bn_hour = to_bn_digits(str(hour_12))
    bn_minute = to_bn_digits(f"{minute:02d}")

    # Final Text
    text = (
        f"আজ {bn_day}ই {bangla_month}, {bn_year} বঙ্গাব্দ, {bn_day_name}। "
        f"এখন সময় {period} {bn_hour}টা {bn_minute} মিনিট।"
    )

    return tts_bangla(text, f"date_time::{now.strftime('%Y-%m-%d-%H:%M')}")

@app.route("/bangla-time")
def bangla_time():
    """আজকের বর্তমান সময় বলে (সংশোধিত সংস্করণ)"""
    tz = pytz.timezone("Asia/Dhaka")
    now = datetime.now(tz)

    # 🕒 Time in Bengali
    hour = now.hour
    minute = now.minute
    period = "রাত" if hour < 4 else "ভোর" if hour < 6 else "সকাল" if hour < 12 else "দুপুর" if hour < 16 else "বিকেল" if hour < 18 else "সন্ধ্যা" if hour < 20 else "রাত"
    hour_12 = hour % 12 or 12
    
    # Convert int to bengali
    def to_bn_digits(s: str) -> str:
        return s.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))

    bn_hour = to_bn_digits(str(hour_12))
    bn_minute = to_bn_digits(f"{minute:02d}")

    # Final Text
    text = (
        f"এখন সময়, {period} {bn_hour}টা {bn_minute} মিনিট।"
    )

    return tts_bangla(text, f"date_time::{now.strftime('%Y-%m-%d-%H:%M')}")

# Ekadoshi 
@app.route("/ekadoshi")
def ekadoshi():
    today = datetime.today().date()

    next_ekadashi = None
    min_days = None

    for ekadashi in ekadashis_2025:
        ekadashi_date = datetime.strptime(ekadashi["english-date"], "%d-%m-%Y").date()
        delta_days = (ekadashi_date - today).days
        if delta_days >= 0:
            if min_days is None or delta_days < min_days:
                min_days = delta_days
                next_ekadashi = ekadashi

    if next_ekadashi:
        bangla_day = next_ekadashi["bangla-date"].split(",")[0]
        text = f"আজ থেকে {min_days} দিন পর {bangla_day}, {next_ekadashi['name']}"
    else:
        text = "এই বছরের আর কোনো একাদশী বাকি নেই।"

    cache_key = f"ekadoshi::{today.strftime('%Y-%m-%d')}"
    return tts_bangla(text, cache_key)

@app.route("/ping")
def ping():
    return "OK"
    
# Keep Server Alive
@app.route("/alive")
def alive():
    today = datetime.today().date()
    cache_key = f"alive::{today.strftime('%Y-%m-%d')}"
    return tts_bangla("য়ি", cache_key)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))