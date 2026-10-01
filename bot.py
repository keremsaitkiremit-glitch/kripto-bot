import ccxt
import pandas as pd
import numpy as np
import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === TELEGRAM VE BORSAYA BAĞLANTI AYARLARI ===
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

# --- İNDİKATÖR YARDIMCILARI ---
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

# --- HACİM PATLAMASI TARAYICISI (VOLUME SCANNER) ---
def scan_volume_spikes():
    """MEXC'deki en yüksek hacimli pariteleri tarar, hacmi ortalamasının üstüne çıkanları bulur"""
    print("Hacim taraması başlatılıyor...", flush=True)
    hot_coins = []
    try:
        markets = exchange.load_markets()
        symbols = [
            s for s in markets 
            if markets[s].get('swap') 
            and markets[s].get('active') 
            and markets[s].get('quote') == 'USDT'
        ]
        # İlk 150 likit pariteyi tarayalım (hız ve rate limit için)
        symbols = sorted(list(set(symbols)))[:150]
        
        for symbol in symbols:
            bars = fetch_ohlcv_data(symbol, '1h', limit=25)
            if len(bars) < 20:
                continue
            df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
            vol_current = float(df["volume"].iloc[-1])
            vol_avg = float(df["volume"].rolling(window=20).mean().iloc[-1])
            
            if not pd.isna(vol_avg) and vol_avg > 0:
                ratio = vol_current / vol_avg
                # Eğer son saatlik hacim ortalamanın en az 2.5 katı olduysa listeye ekle
                if ratio >= 2.5:
                    clean_name = symbol.split(':')[0].replace("/", "")
                    close_price = float(df["close"].iloc[-1])
                    change_pct = ((float(df["close"].iloc[-1]) - float(df["open"].iloc[-1])) / float(df["open"].iloc[-1])) * 100
                    hot_coins.append({
                        "symbol": clean_name,
                        "ratio": ratio,
                        "price": close_price,
                        "change": change_pct
                    })
        
        # En yüksek hacim artışına göre sırala
        hot_coins = sorted(hot_coins, key=lambda x: x["ratio"], reverse=True)[:5]
        return hot_coins
    except Exception as e:
        print(f"Tarama hatası: {e}", flush=True)
        return []

# --- AKILLI TEMEL ANALİZ & HYPE SENTEZLEYİCİ ---
def evaluate_fundamental_and_hype(ticker, rsi_1d, volume_status):
    ticker_upper = ticker.upper()
    
    if ticker_upper == "QNT":
        return (
            "🧠 *Temel Analiz & Hype İstihbaratı (QNT):*\n"
            "• *Proje Durumu:* Kurumsal birlikte çalışabilirlik alanında sağlam altyapı.\n"
            "• *Hype Durumu:* Dönemsel kurumsal haber akışlarıyla ani FOMO yaratır.\n"
            "• *Risk Faktörü:* Düşük hacimli dönemlerde manipülatiftir ancak hacim varsa long yönlü ivme kazanır."
        )
    else:
        hype_text = "Çok Yüksek 🔥 (Para Girişi Var)" if volume_status else "Normal / Durgun"
        sentiment = "Boğa / Güçlü Toplama" if rsi_1d > 50 else "Dibe Yakın / Akümülasyon"
        
        return (
            f"🧠 *Temel Analiz & Hype İstihbaratı ({ticker_upper}):*\n"
            f"• *Piyasa Algısı (Sentiment):* `{sentiment}`\n"
            f"• *Sosyal Hype / Hacim Yakıtı:* `{hype_text}`\n"
            f"• *Yorum:* Hacmin artmaya başlaması akıllı paranın (balinaların) pozisyon aldığını gösterir. Hacim varsa long yönlü fırsatlar önceliklidir."
        )

# --- TEKİL PARİTE DERİN ANALİZİ ---
def perform_deep_analysis(ticker):
    formatted_symbol = f"{ticker.upper().replace('/USDT', '').replace('USDT', '')}/USDT:USDT"
    
    try:
        exchange.load_markets()
        if formatted_symbol not in exchange.markets:
            formatted_symbol = f"{ticker.upper().replace('/USDT', '').replace('USDT', '')}USDT"
            if formatted_symbol not in exchange.markets:
                return f"❌ `{ticker.upper()}` paritesi MEXC futures listesinde bulunamadı."
    except Exception:
        return f"⚠️ Parite yüklenirken hata oluştu."

    bars_1h = fetch_ohlcv_data(formatted_symbol, '1h', limit=50)
    bars_4h = fetch_ohlcv_data(formatted_symbol, '4h', limit=50)
    bars_1d = fetch_ohlcv_data(formatted_symbol, '1d', limit=100)
    bars_1w = fetch_ohlcv_data(formatted_symbol, '1w', limit=30)

    if not bars_1h or not bars_4h or not bars_1d:
        return f"⚠️ `{ticker.upper()}` için yeterli veri çekilemedi."

    df_1h = pd.DataFrame(bars_1h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_4h = pd.DataFrame(bars_4h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_1d = pd.DataFrame(bars_1d, columns=["timestamp", "open", "high", "low", "close", "volume"])
    
    close_1h = float(df_1h["close"].iloc[-1])
    rsi_1h = float(calculate_rsi(df_1h["close"], 14).iloc[-1])
    
    ema9_4h = df_4h["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_4h = df_4h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    rsi_4h = float(calculate_rsi(df_4h["close"], 14).iloc[-1])
    
    ema20_1d = df_1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50_1d = df_1d["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    rsi_1d = float(calculate_rsi(df_1d["close"], 14).iloc[-1])
    close_1d = float(df_1d["close"].iloc[-1])
    
    vol_current = float(df_1h["volume"].iloc[-1])
    vol_avg = float(df_1h["volume"].rolling(window=20).mean().iloc[-1])
    is_volume_spike = vol_current > (vol_avg * 2.0) if not pd.isna(vol_avg) else False

    w_trend = "Nötr"
    if len(bars_1w) >= 20:
        df_1w = pd.DataFrame(bars_1w, columns=["timestamp", "open", "high", "low", "close", "volume"])
        w_ema21 = df_1w["close"].ewm(span=21, adjust=False).mean().iloc[-1]
        w_close = df_1w["close"].iloc[-1]
        w_trend = "Yükseliş (Bullish)" if w_close > w_ema21 else "Düşüş (Bearish)"

    # Hacim patlaması varsa teknik yönü long lehine güçlendiririz
    is_bullish = (close_1d > ema20_1d and rsi_1d > 45) or is_volume_spike
    tech_bias = "LONG (Güçlü Hacim / Yükseliş Baskısı)" if is_bullish else "SHORT (Satış Baskısı)"
    
    giris = close_1h
    if "LONG" in tech_bias:
        stop = giris * 0.96
        tp1 = giris * 1.10
        tp2 = giris * 1.20
    else:
        stop = giris * 1.04
        tp1 = giris * 0.90
        tp2 = giris * 0.80

    fundamental_report = evaluate_fundamental_and_hype(ticker, rsi_1d, is_volume_spike)

    report = (
        f"📊 *KURUMSAL ANALİST RAPORU: {ticker.upper()}*\n\n"
        f"💵 *Anlık Fiyat:* `{giris:.4f}`\n\n"
        f"⏱ *Zaman Dilimi ve Hacim Durumu:*\n"
        f"• *1 Saatlik Hacim:* `{'🚨 DİKKAT ÇEKİCİ HACİM PATLAMASI (' + str(round(vol_current/vol_avg, 1)) + 'x)' if is_volume_spike else 'Normal Seviyede'}`\n"
        f"• *4 Saatlik EMA 9/21:* `{'Pozitif' if ema9_4h > ema21_4h else 'Negatif'}` (RSI: `{rsi_4h:.1f}`)\n"
        f"• *Günlük Trend:* `{'Boğa (EMA Üstü)' if close_1d > ema20_1d else 'Akümülasyon'}` (RSI: `{rsi_1d:.1f}`)\n"
        f"• *Haftalık Makro Trend:* `{w_trend}`\n\n"
        f"🎯 *Teknik Strateji & Seviyeler:*\n"
        f"• *Önerilen Yön:* *{tech_bias}*\n"
        f"• *Giriş:* `{giris:.4f}`\n"
        f"• *Stop-Loss:* `{stop:.4f}`\n"
        f"• *Hedef 1 (TP1):* `{tp1:.4f}`\n"
        f"• *Hedef 2 (TP2):* `{tp2:.4f}`\n\n"
        f"{fundamental_report}\n\n"
        f"⚠️ *Fon Yöneticisi Notu:* *Hacim, fiyat hareketinin yakıtıdır. Hacim patlaması yaşayan varlıklarda long yönlü fırsatlar her zaman önceliklidir ancak stop disiplini unutulmamalıdır.*"
    )
    return report

# === FLASK WEBHOOK (TELEGRAM İLETİŞİM) ===
@app.route("/", methods=["GET"])
def home():
    return "CalmCapital Kurumsal Analist & Hacim Tarayıcı Aktif! ⏳🚀"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()
        
        if text:
            clean_text = text.replace("/analiz", "").replace("@", "").strip().upper()
            
            # Eğer kullanıcı /hacim komutu yazdıysa piyasayı tarasın
            if clean_text == "HACİM" or clean_text == "/HACİM":
                send_telegram_message(chat_id, "🔍 *Piyasada hacmi patlayan pariteler taranıyor, lütfen bekleyin...* ⏳")
                spikes = scan_volume_spikes()
                if spikes:
                    msg = "🚨 *HACMİ DİKKAT ÇEKEN (PATLAMA YAPAN) COİNLER* 🚨\n\n"
                    for item in spikes:
                        msg += (
                            f"🪙 *{item['symbol']}*\n"
                            f"• Hacim Katı: `{item['ratio']:.1f}x` ortalama\n"
                            f"• Fiyat: `{item['price']}` (`%{item['change']:.2f}`)\n"
                            f"👉 *Yorum:* Hacim girişi var, long fırsatları aranmalı!\n\n"
                        )
                    send_telegram_message(chat_id, msg)
                else:
                    send_telegram_message(chat_id, "ℹ️ Şu an hacmi ortalamanın çok üstüne çıkan belirgin bir parite bulunamadı.")
            elif len(clean_text) <= 10 and len(clean_text) > 0:
                analysis_result = perform_deep_analysis(clean_text)
                send_telegram_message(chat_id, analysis_result)
            else:
                send_telegram_message(
                    chat_id, 
                    "🤖 Bot Komutları:\n"
                    "• Hacmi patlayanları görmek için: `/hacim`\n"
                    "• Tekil coin analizi için: Doğrudan coin adı yaz (Örn: `BTC`, `QNT`, `ETH`)."
                )
                
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
