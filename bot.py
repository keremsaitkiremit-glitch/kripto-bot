import ccxt
import pandas as pd
import numpy as np
import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# MEXC Futures (Swap) Bağlantısı
exchange = ccxt.mexc({
    'options': {'defaultType': 'swap'},
    'enableRateLimit': True
})

def send_telegram_message(chat_id, message):
    if not TELEGRAM_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        return response.ok
    except Exception:
        return False

def setup_webhook_automatically():
    if not TELEGRAM_TOKEN:
        return
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        webhook_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={render_url}/{TELEGRAM_TOKEN}"
        try:
            requests.get(webhook_url, timeout=5)
        except Exception:
            pass

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def fetch_ohlcv_data(symbol, timeframe, limit=100):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return bars
    except Exception:
        return []

def perform_pure_technical_analysis(ticker):
    formatted_symbol = f"{ticker.upper().replace('/USDT', '').replace('USDT', '')}/USDT:USDT"
    
    try:
        exchange.load_markets()
        if formatted_symbol not in exchange.markets:
            formatted_symbol = f"{ticker.upper().replace('/USDT', '').replace('USDT', '')}USDT"
            if formatted_symbol not in exchange.markets:
                return f"❌ `{ticker.upper()}` paritesi MEXC futures listesinde bulunamadı."
    except Exception:
        return f"⚠️ Parite yüklenirken hata oluştu."

    # Çoklu Zaman Dilimi Mum Verileri
    bars_15m = fetch_ohlcv_data(formatted_symbol, '15m', limit=50)
    bars_1h = fetch_ohlcv_data(formatted_symbol, '1h', limit=50)
    bars_4h = fetch_ohlcv_data(formatted_symbol, '4h', limit=50)
    bars_1d = fetch_ohlcv_data(formatted_symbol, '1d', limit=100)

    if not bars_15m or not bars_1h or not bars_4h or not bars_1d:
        return f"⚠️ `{ticker.upper()}` için yeterli teknik veri çekilemedi."

    df_15m = pd.DataFrame(bars_15m, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_1h = pd.DataFrame(bars_1h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_4h = pd.DataFrame(bars_4h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_1d = pd.DataFrame(bars_1d, columns=["timestamp", "open", "high", "low", "close", "volume"])

    # 1. 15 Dakika (Scalp / Tetik)
    close_15m = float(df_15m["close"].iloc[-1])
    rsi_15m = float(calculate_rsi(df_15m["close"], 14).iloc[-1])
    ema9_15m = df_15m["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_15m = df_15m["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    trend_15m = "LONG 🟢" if ema9_15m > ema21_15m else "SHORT 🔴"

    # 2. 1 Saat (İç Trend)
    rsi_1h = float(calculate_rsi(df_1h["close"], 14).iloc[-1])
    ema9_1h = df_1h["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_1h = df_1h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    trend_1h = "LONG 🟢" if ema9_1h > ema21_1h else "SHORT 🔴"

    # 3. 4 Saat (Orta Vade)
    rsi_4h = float(calculate_rsi(df_4h["close"], 14).iloc[-1])
    ema9_4h = df_4h["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_4h = df_4h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    trend_4h = "LONG 🟢" if ema9_4h > ema21_4h else "SHORT 🔴"

    # 4. 1 Gün (Ana Trend)
    rsi_1d = float(calculate_rsi(df_1d["close"], 14).iloc[-1])
    ema20_1d = df_1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50_1d = df_1d["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    close_1d = float(df_1d["close"].iloc[-1])
    trend_1d = "LONG 🟢" if close_1d > ema20_1d and ema20_1d > ema50_1d else "SHORT 🔴"

    # Net Karar Algoritması
    long_count = sum([1 for t in [trend_15m, trend_1h, trend_4h, trend_1d] if "LONG" in t])
    if long_count >= 3:
        overall_bias = "KESİN LONG 🟢"
    elif long_count <= 1:
        overall_bias = "KESİN SHORT 🔴"
    else:
        overall_bias = "NÖTR / YÖN ARANIYOR 🟡"

    # Risk Yönetimi & Seviyeler
    giris = close_15m
    if "LONG" in overall_bias or "NÖTR" in overall_bias:
        stop = giris * 0.975   # %2.5 Stop
        tp1 = giris * 1.025    # %2.5 Hedef
        tp2 = giris * 1.05     # %5.0 Hedef
        tp3 = giris * 1.08     # %8.0 Hedef
    else:
        stop = giris * 1.025   # %2.5 Stop (Short için üstte)
        tp1 = giris * 0.975    # %2.5 Hedef
        tp2 = giris * 0.95     # %5.0 Hedef
        tp3 = giris * 0.92     # %8.0 Hedef

    # Net Rapor Taslağı
    report = (
        f"📊 *TEKNİK ANALİZ RAPORU: {ticker.upper()}*\n\n"
        f"💵 *Anlık Fiyat:* `{giris:.4f}`\n\n"
        f"⏱ *Zaman Dilimi Analizi:*\n"
        f"• *15 Dakikalık:* {trend_15m} (RSI: `{rsi_15m:.1f}`)\n"
        f"• *1 Saatlik:* {trend_1h} (RSI: `{rsi_1h:.1f}`)\n"
        f"• *4 Saatlik:* {trend_4h} (RSI: `{rsi_4h:.1f}`)\n"
        f"• *Günlük:* {trend_1d} (RSI: `{rsi_1d:.1f}`)\n\n"
        f"🎯 *NET POZİSYON ÖNERİSİ:* *{overall_bias}*\n\n"
        f"📐 *İşlem Seviyeleri:*\n"
        f"• *Giriş (Entry):* `{giris:.4f}`\n"
        f"• *Zarar Durdur (Stop):* `{stop:.4f}`\n"
        f"• *Hedef 1 (TP1):* `{tp1:.4f}`\n"
        f"• *Hedef 2 (TP2):* `{tp2:.4f}`\n"
        f"• *Hedef 3 (TP3):* `{tp3:.4f}`"
    )
    return report

@app.route("/", methods=["GET"])
def home():
    return "Saf Teknik Analist Bot Aktif! ⏳🚀"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()
        
        if text:
            # Gelen metni temizle (Örn: /BTC veya BTC -> BTC)
            clean_text = text.replace("/", "").replace("@", "").strip().upper()
            
            # Eğer geçerli bir coin sembolüyse analizi bas
            if len(clean_text) <= 8 and len(clean_text) > 0 and " " not in clean_text:
                result = perform_pure_technical_analysis(clean_text)
                send_telegram_message(chat_id, message=result)
                
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    setup_webhook_automatically()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
