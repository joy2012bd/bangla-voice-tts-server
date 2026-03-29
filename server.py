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
try:
    with open("ekadashis_2025.json", "r", encoding="utf-8") as f:
        ekadashis_2025 = json.load(f)
except FileNotFoundError:
    ekadashis_2025 = [] # Fallback if file not found

def to_bn_digits(s: str) -> str:
    """Helper to convert English digits to Bengali digits for better TTS"""
    return str(s).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))

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
    """Detailed Weather + Today's Alert + 3-day forecast Bengali TTS"""
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
    temp_max = now["main"]["temp_max"]
    humidity = now["main"]["humidity"]
    raw_desc = now["weather"][0]["description"].lower()
    weather_main = now["weather"][0]["main"].lower()

    # বর্ধিত অনুবাদ ম্যাপ
    desc_map = {
        "clear sky": "পরিষ্কার",
        "few clouds": "কিছুটা মেঘলা",
        "scattered clouds": "বিক্ষিপ্ত মেঘলা",
        "broken clouds": "আংশিক মেঘলা",
        "overcast clouds": "সম্পূর্ণ মেঘলা",
        "light rain": "হালকা বৃষ্টি",
        "moderate rain": "মাঝারি বৃষ্টি",
        "heavy rain": "তীব্র বৃষ্টি",
        "thunderstorm": "বজ্রসহ বৃষ্টি",
        "drizzle": "গুঁড়ি গুঁড়ি বৃষ্টি",
        "haze": "ধোঁয়াশাচ্ছন্ন",
        "mist": "কুয়াশাচ্ছন্ন",
        "fog": "ঘন কুয়াশা",
        "smoke": "ধোঁয়াটে",
        "dust": "ধূলিময়",
        "sand": "বালু ঝড়"
    }
    
    desc = None
    for en, bn in desc_map.items():
        if en in raw_desc:
            desc = bn
            break
    
    # যদি ম্যাপে না থাকে তবে একটি সাধারণ বাংলা শব্দ ব্যবহার
    if not desc:
        if "cloud" in raw_desc:
            desc = "মেঘলা"
        elif "rain" in raw_desc:
            desc = "বৃষ্টিমুখর"
        else:
            desc = "অস্পষ্ট"

    # --- forecast & today's alerts ---
    url_forecast = "https://api.openweathermap.org/data/2.5/forecast"
    params_fore = {"q": city, "appid": OPENWEATHER_KEY, "units": units}
    resp_fore = requests.get(url_forecast, params=params_fore, timeout=10)
    
    current_month = datetime.now(pytz.timezone("Asia/Dhaka")).month
    today_alert = ""
    forecast_text = ""

    if resp_fore.status_code == 200:
        fore = resp_fore.json()
        forecast_list = fore["list"]
        
        upcoming_rain = False
        upcoming_storm = False
        for item in forecast_list[:4]:
            cond = item["weather"][0]["main"].lower()
            if cond in ["rain", "drizzle", "thunderstorm"]: upcoming_rain = True
            if cond == "thunderstorm": upcoming_storm = True
        
        if upcoming_storm:
            today_alert = "সতর্কতাঃ আজ কিছুক্ষণ পর বজ্রসহ ঝড়-বৃষ্টির সম্ভাবনা রয়েছে।"
        elif upcoming_rain and weather_main not in ["rain", "drizzle", "thunderstorm"]:
            today_alert = "তবে আজ কিছুক্ষণ পর বৃষ্টির সম্ভাবনা রয়েছে।"

        future_rains = 0
        future_storms = False
        for item in forecast_list[8:32]:
            cond = item["weather"][0]["main"].lower()
            if cond in ["rain", "drizzle", "thunderstorm"]: future_rains += 1
            if cond == "thunderstorm": future_storms = True

        if future_storms:
            rain_msg = "আগামী তিন দিনে বজ্রসহ ঝড়-বৃষ্টির সম্ভাবনা রয়েছে।"
        elif future_rains > 0:
            rain_msg = "আগামী তিন দিনে বৃষ্টির সম্ভাবনা রয়েছে।"
        else:
            rain_msg = "আগামী তিন দিনে বৃষ্টির তেমন কোনো সম্ভাবনা নেই।"
        
        forecast_text = f"পূর্বাভাস অনুযায়ী {rain_msg}"
    else:
        forecast_text = "আগামী তিন দিনের পূর্বাভাস এই মুহূর্তে পাওয়া যাচ্ছে না।"

    # --- Contextual Logic ---
    is_raining_now = weather_main in ["rain", "drizzle", "thunderstorm"]
    advice = ""
    current_feel = f"আকাশ {desc}।"

    if is_raining_now:
        if weather_main == "thunderstorm":
            current_feel = "বাইরে এখন বজ্রসহ বৃষ্টি হচ্ছে।"
            advice = "নিরাপদে থাকুন।"
        else:
            current_feel = f"বাইরে এখন {desc} হচ্ছে।"
            advice = "বাইরে বের হলে ছাতা সাথে রাখুন।"
    else:
        if current_month in [11, 12, 1, 2]: # Winter
            if temp < 18: current_feel += " বাইরে বেশ শীত অনুভূত হচ্ছে।"
        elif current_month in [3, 4, 5, 6]: # Summer
            if temp > 34: 
                current_feel += " বাইরে প্রচণ্ড গরম।"
                advice = "প্রচুর পানি পান করুন।"
        
        if humidity > 75 and temp > 30:
            current_feel += " বাতাসে আর্দ্রতা বেশি থাকায় ভ্যাপসা গরম লাগতে পারে।"

    # --- final text construction ---
    bn_temp = to_bn_digits(str(round(temp)))
    bn_max = to_bn_digits(str(round(temp_max)))
    bn_humidity = to_bn_digits(str(humidity))

    text = (
        f"আজকের আবহাওয়া। এই মুহূর্তে {city} এ তাপমাত্রা {bn_temp} ডিগ্রি সেলসিয়াস। "
        f"{current_feel} {today_alert} আজকের সর্বোচ্চ তাপমাত্রা হতে পারে {bn_max} ডিগ্রি। "
        f"বাতাসে আর্দ্রতা {bn_humidity} শতাংশ। {advice} {forecast_text}"
    )
    
    clean_text = " ".join(text.split())
    return tts_bangla(clean_text, cache_key)

@app.route("/rain")
def rain_alert_tts():
    """Short Rain/Storm alert only for next 12 hours"""
    city = request.args.get("city", "Dhaka")
    units = request.args.get("units", "metric")
    
    if not OPENWEATHER_KEY:
        return jsonify({"error": "OPENWEATHER_API_KEY missing"}), 500

    url_forecast = "https://api.openweathermap.org/data/2.5/forecast"
    params_fore = {"q": city, "appid": OPENWEATHER_KEY, "units": units}
    resp_fore = requests.get(url_forecast, params=params_fore, timeout=10)
    
    if resp_fore.status_code != 200:
        return jsonify({"error": "forecast api failed"}), 502
    
    fore = resp_fore.json()
    forecast_list = fore["list"]
    current_time = time.time()
    
    alert_text = ""
    # চেক আগামী ১২ ঘণ্টা (৪টি ৩-ঘণ্টার ব্লক)
    for item in forecast_list[:4]:
        weather_item = item["weather"][0]
        main_cond = weather_item["main"].lower()
        dt = item["dt"]
        
        # কত ঘণ্টা পর হিসেব
        hours_ahead = round((dt - current_time) / 3600)
        if hours_ahead < 1: hours_ahead = 1 # মিনিমাম ১ ঘণ্টা
        bn_hours = to_bn_digits(str(hours_ahead))
        
        if main_cond == "thunderstorm":
            alert_text = f"আগামী {bn_hours} ঘণ্টার মধ্যে ঝড় হওয়ার সম্ভাবনা রয়েছে।"
            break
        elif main_cond in ["rain", "drizzle"]:
            alert_text = f"আগামী {bn_hours} ঘণ্টার মধ্যে বৃষ্টি হওয়ার সম্ভাবনা রয়েছে।"
            break
            
    if not alert_text:
        # কোনো বৃষ্টি/ঝড় নেই, তাই কিছুই বলবে না
        return "", 204

    cache_key = f"rain_alert::{city}::{datetime.now().strftime('%Y-%m-%d-%H')}"
    return tts_bangla(alert_text, cache_key)

@app.route("/bangla-date-time")
def bangla_date_time():
    tz = pytz.timezone("Asia/Dhaka")
    now = datetime.now(tz)

    bn_day_name = {
        "Saturday": "শনিবার", "Sunday": "রবিবার", "Monday": "সোমবার",
        "Tuesday": "মঙ্গলবার", "Wednesday": "বুধবার", "Thursday": "বৃহস্পতিবার", "Friday": "শুক্রবার",
    }[now.strftime("%A")]

    g_date = now.date()
    if g_date >= datetime(g_date.year, 4, 14).date():
        bangla_year = g_date.year - 593
        new_year_start = datetime(g_date.year, 4, 14).date()
    else:
        bangla_year = g_date.year - 594
        new_year_start = datetime(g_date.year - 1, 4, 14).date()

    bangla_months = [
        ("বৈশাখ", 31), ("জ্যৈষ্ঠ", 31), ("আষাঢ়", 31), ("শ্রাবণ", 31), ("ভাদ্র", 31), ("আশ্বিন", 30),
        ("কার্তিক", 30), ("অগ্রহায়ণ", 30), ("পৌষ", 30), ("মাঘ", 30), ("ফাল্গুন", 29), ("চৈত্র", 30)
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

    bn_day = to_bn_digits(str(bangla_day))
    bn_year = to_bn_digits(str(bangla_year))

    en_month_map = {
        1: "জানুয়ারী", 2: "ফেব্রুয়ারী", 3: "মার্চ", 4: "এপ্রিল", 5: "মে", 6: "জুন",
        7: "জুলাই", 8: "আগস্ট", 9: "সেপ্টেম্বর", 10: "অক্টোবর", 11: "নভেম্বর", 12: "ডিসেম্বর"
    }
    en_month_name = en_month_map[now.month]
    en_day_num = to_bn_digits(str(now.day))
    en_year_num = to_bn_digits(str(now.year))

    text = (
        f"আজ {bn_day_name}, বাংলাঃ {bn_day}ই {bangla_month}, {bn_year} বঙ্গাব্দ। "
        f"ইংরেজিঃ {en_day_num}ই {en_month_name} {en_year_num}।"
    )

    return tts_bangla(text, f"date_time::{now.strftime('%Y-%m-%d-%H')}")

@app.route("/bangla-time")
def bangla_time():
    tz = pytz.timezone("Asia/Dhaka")
    now = datetime.now(tz)

    hour = now.hour
    minute = now.minute
    period = "রাত" if hour < 4 else "ভোর" if hour < 6 else "সকাল" if hour < 12 else "দুপুর" if hour < 16 else "বিকেল" if hour < 18 else "সন্ধ্যা" if hour < 20 else "রাত"
    hour_12 = hour % 12 or 12
    
    bn_hour = to_bn_digits(str(hour_12))
    
    if minute == 0:
        text = f"এখন সময়, {period} {bn_hour}টা।"
    else:
        bn_minute = to_bn_digits(str(minute))
        text = f"এখন সময়, {period} {bn_hour}টা {bn_minute} মিনিট।"

    return tts_bangla(text, f"date_time::{now.strftime('%Y-%m-%d-%H:%M')}")

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
        bn_min_days = to_bn_digits(str(min_days))
        text = f"আজ থেকে {bn_min_days} দিন পর {bangla_day}, {next_ekadashi['name']}"
    else:
        text = "এই বছরের আর কোনো একাদশী বাকি নেই।"

    return tts_bangla(text, f"ekadoshi::{today.strftime('%Y-%m-%d')}")

@app.route("/ping")
def ping():
    return "OK"

@app.route("/alive")
def alive():
    return tts_bangla("সিস্টেম সচল আছে", "alive_check")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))