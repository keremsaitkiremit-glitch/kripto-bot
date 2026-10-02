import ccxt
import pandas as pd
import numpy as np
import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

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

def perform_real_technical_analysis(ticker):
    formatted_symbol = f"{ticker.upper().replace('/USDT', '').replace('USDT', '')}/USDT:USDT"
    
    try:
        exchange.load_markets()
        if formatted_symbol not in exchange.markets:
            formatted_symbol = f"{ticker.upper().replace('/USDT', '').replace('USDT', '')}USDT"
            if formatted_symbol not in exchange.markets:
                return f"❌ `{ticker.upper()}` paritesi MEXC futures listesinde bulunamadı."
    except Exception:
        return f"⚠️ Piyasa verileri yüklenirken hata oluştu."

    # Çoklu Zaman Dilimi Mum Verileri
    bars_15m = fetch_ohlcv_data(formatted_symbol, '15m', limit=60)
    bars_1h = fetch_ohlcv_data(formatted_symbol, '1h', limit=60)
    bars_4h = fetch_ohlcv_data(formatted_symbol, '4h', limit=60)
    bars_1d = fetch_ohlcv_data(formatted_symbol, '1d', limit=100)

    if not bars_15m or not bars_1h or not bars_4h or not bars_1d:
        return f"⚠️ `{ticker.upper()}` için yeterli teknik veri çekilemedi."

    df_15m = pd.DataFrame(bars_15m, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_1h = pd.DataFrame(bars_1h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_4h = pd.DataFrame(bars_4h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_1d = pd.DataFrame(bars_1d, columns=["timestamp", "open", "high", "low", "close", "volume"])

    # Zaman Dilimi Trend Hesaplamaları
    close_15m = float(df_15m["close"].iloc[-1])
    rsi_15m = float(calculate_rsi(df_15m["close"], 14).iloc[-1])
    ema9_15m = df_15m["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_15m = df_15m["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    trend_15m = "LONG 🟢" if ema9_15m > ema21_15m else "SHORT 🔴"

    rsi_1h = float(calculate_rsi(df_1h["close"], 14).iloc[-1])
    ema9_1h = df_1h["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_1h = df_1h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    trend_1h = "LONG 🟢" if ema9_1h > ema21_1h else "SHORT 🔴"

    rsi_4h = float(calculate_rsi(df_4h["close"], 14).iloc[-1])
    ema9_4h = df_4h["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_4h = df_4h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    trend_4h = "LONG 🟢" if ema9_4h > ema21_4h else "SHORT 🔴"

    rsi_1d = float(calculate_rsi(df_1d["close"], 14).iloc[-1])
    ema20_1d = df_1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50_1d = df_1d["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    close_1d = float(df_1d["close"].iloc[-1])
    trend_1d = "LONG 🟢" if close_1d > ema20_1d and ema20_1d > ema50_1d else "SHORT 🔴"

    long_count = sum([1 for t in [trend_15m, trend_1h, trend_4h, trend_1d] if "LONG" in t])
    if long_count >= 3:
        overall_bias = "KESİN LONG 🟢"
    elif long_count <= 1:
        overall_bias = "KESİN SHORT 🔴"
    else:
        overall_bias = "NÖTR / KARARSIZ 🟡"

    # --- GERÇEK DESTEK VE DİRENÇ (SWING HIGH / LOW) TESPİTİ ---
    # 1 saatlik ve 4 saatlik mumların en düşük dip ve en yüksek tepe noktalarını baz alıyoruz
    recent_low_1h = float(df_1h["low"].tail(20).min())   # Son 20 mumun en dip noktası (Doğal Destek)
    recent_high_1h = float(df_1h["high"].tail(20).max()) # Son 20 mumun en tepe noktası (Doğal Direnç)
    
    recent_low_4h = float(df_4h["low"].tail(10).min())   # 4 Saatlik ana destek
    recent_high_4h = float(df_4h["high"].tail(10).max()) # 4 Saatlik ana direnç

    giris = close_15m

    if "LONG" in overall_bias or "NÖTR" in overall_bias:
        # Stop loss: 1 saatlik en yakın dip desteğinin biraz altı (Piyasa yapısına dayalı)
        stop = min(recent_low_1h, recent_low_4h) * 0.992 
        if stop >= giris: # Güvenlik kontrolü
            stop = giris * 0.975
            
        # Hedefler (TP): Önümüzdeki gerçek dirençler ve mesafe projeksiyonu
        risk_araligi = giris - stop
        tp1 = giris + (risk_araligi * 1.5)
        tp2 = max(recent_high_1h, giris + (risk_araligi * 2.5))
        tp3 = max(recent_high_4h, giris + (risk_araligi * 4.0))
    else:
        # Short için stop: Son tepe direncinin biraz üstü
        stop = max(recent_high_1h, recent_high_4h) * 1.008
        if stop <= giris:
            stop = giris * 1.025
            
        risk_araligi = stop - giris
        tp1 = giris - (risk_araligi * 1.5)
        tp2 = min(recent_low_1h, giris - (risk_araligi * 2.5))
        tp3 = min(recent_low_4h, giris - (risk_araligi * 4.0))

    # Profesyonel Rapor Taslağı
    report = (
        f"📊 *PİYASA YAPISI ANALİZİ: {ticker.upper()}/USDT*\n\n"
        f"💵 *Anlık Fiyat:* `{giris:.4f}`\n\n"
        f"⏱ *Zaman Dilimi Durumu:*\n"
        f"• *15 Dakikalık:* {trend_15m} (RSI: `{rsi_15m:.1f}`)\n"
        f"• *1 Saatlik:* {trend_1h} (RSI: `{rsi_1h:.1f}`)\n"
        f"• *4 Saatlik:* {trend_4h} (RSI: `{rsi_4h:.1f}`)\n"
        f"• *Günlük Trend:* {trend_1d} (RSI: `{rsi_1d:.1f}`)\n\n"
        f"🎯 *NET YÖN KARARI:* *{overall_bias}*\n\n"
        f"📐 *Gerçek Destek/Direnç Bazlı Seviyeler:*\n"
        f"• *Giriş (Entry):* `{giris:.4f}`\n"
        f"• *Zarar Durdur (Stop - Destek Altı):* `{stop:.4f}`\n"
        f"• *Hedef 1 (TP1):* `{tp1:.4f}`\n"
        f"• *Hedef 2 (TP2 - Direnç):* `{tp2:.4f}`\n"
        f"• *Hedef 3 (TP3 - Ana Direnç):* `{tp3:.4f}`"
    )
    return report

@app.route("/", methods=["GET"])
def home():
    return "Gerçek Teknik Destek/Direnç Botu Aktif! ⏳🚀"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()
        
        if text:
            clean_text = text.replace("/", "").replace("@", "").strip().upper()
            if len(clean_text) <= 8 and len(clean_text) > 0 and " " not in clean_text:
                result = perform_real_technical_analysis(clean_text)
                send_telegram_message(chat_id, message=result)
                
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    setup_webhook_automatically()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
