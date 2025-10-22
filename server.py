# server.py
import os
import time
import tempfile
from flask import Flask, request, send_file, jsonify
from gtts import gTTS
import requests

app = Flask(__name__)

# config from env
OPENWEATHER_KEY = "8c04437c21dcdcddace4e76e5c850dd7"  # set in Render dashboard
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # seconds, default 5 minutes

# simple in-memory cache to reduce API calls: {key: (timestamp, mp3_bytes or text)}
_cache = {}

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

@app.route("/tts")
def tts_endpoint():
    """
    Generic TTS endpoint:
    GET /tts?text=...&lang=bn
    Returns: mp3 file
    """
    text = request.args.get("text", "").strip()
    lang = request.args.get("lang", "bn")

    if not text:
        return jsonify({"error": "text param required"}), 400
    if len(text) > 1000:
        return jsonify({"error": "text too long"}), 400

    cache_key = f"tts::{lang}::{text}"
    cached = cache_get(cache_key)
    if cached:
        # cached is bytes
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.write(cached)
        tmp.flush()
        tmp.close()
        return send_file(tmp.name, mimetype="audio/mpeg", as_attachment=False)

    # generate with gTTS
    try:
        tts = gTTS(text=text, lang=lang)
        tmp_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp_name = tmp_fp.name
        tmp_fp.close()
        tts.save(tmp_name)
        with open(tmp_name, "rb") as f:
            data = f.read()
        cache_set(cache_key, data)
        return send_file(tmp_name, mimetype="audio/mpeg", as_attachment=False)
    finally:
        # cleanup: let send_file finish; we won't delete immediately to avoid race
        pass

@app.route("/weather")
def weather_tts():
    """
    Weather endpoint that returns TTS mp3 of current weather in Bengali.
    GET /weather?city=Dhaka&units=metric
    """
    city = request.args.get("city", "Dhaka")
    units = request.args.get("units", "metric")
    lang = "bn"

    # build cache key by city+units
    cache_key_text = f"weather_text::{city}::{units}"
    cached_audio = cache_get(f"tts::{lang}::{cache_key_text}")
    if cached_audio:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.write(cached_audio)
        tmp.flush()
        tmp.close()
        return send_file(tmp.name, mimetype="audio/mpeg", as_attachment=False)

    if not OPENWEATHER_KEY:
        return jsonify({"error": "OPENWEATHER_API_KEY not configured"}), 500

    # call OpenWeatherMap current weather API
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_KEY, "units": units, "lang": "en"}  # en for condition -> we'll translate
    resp = requests.get(url, params=params, timeout=8)
    if resp.status_code != 200:
        return jsonify({"error": "weather api failed", "detail": resp.text}), 502

    j = resp.json()
    # extract useful bits robustly
    try:
        temp = j["main"]["temp"]
        feels = j["main"].get("feels_like")
        desc = j["weather"][0]["description"]  # in language=en per param
        # make a Bengali sentence. Simplest: translate known terms, or just compose in Bengali.
        text = f"{city} এ বর্তমানে তাপমাত্রা {round(temp)} ডিগ্রি সেলসিয়াস। অবস্থা: {desc}।"
    except Exception as e:
        return jsonify({"error": "parse error", "detail": str(e), "resp": j}), 500

    # Optionally refine translation for common words (small map)
    small_map = {
        "clear sky":"পরিষ্কার আকাশ",
        "broken clouds":"আবহাওয়া মেঘলা",
        "few clouds":"কিছু মেঘ",
        "scattered clouds":"বিস্তৃত মেঘ",
        "overcast clouds":"সম্পূর্ণ মেঘলা",
        "light rain":"অল্প বৃষ্টি",
        "moderate rain":"মাঝারি বৃষ্টি",
        "heavy intensity rain":"তীব্র বৃষ্টি",
        "shower rain":"বৃষ্টি"
    }
    for en, bn in small_map.items():
        if en in desc.lower():
            text = f"{city} এ বর্তমানে তাপমাত্রা {round(temp)} ডিগ্রি সেলসিয়াস। অবস্থা: {bn}।"
            break

    # generate TTS (reuse /tts logic but inline to avoid extra HTTP)
    cache_key = f"tts::{lang}::{cache_key_text}"
    cached = cache_get(cache_key)
    if cached:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.write(cached)
        tmp.flush()
        tmp.close()
        return send_file(tmp.name, mimetype="audio/mpeg", as_attachment=False)

    tts = gTTS(text=text, lang=lang)
    tmp_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp_name = tmp_fp.name
    tmp_fp.close()
    tts.save(tmp_name)
    with open(tmp_name, "rb") as f:
        data = f.read()
    cache_set(cache_key, data)
    # also cache the underlying text key so repeated /weather calls within TTL don't re-API
    cache_set(f"weather_text::{city}::{units}", text)
    return send_file(tmp_name, mimetype="audio/mpeg", as_attachment=False)


@app.route("/ping")
def ping():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
