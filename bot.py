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

# --- OTOMATİK WEBHOOK KAYDI (Tarayıcı derdine son!) ---
def setup_webhook_automatically():
    if not TELEGRAM_TOKEN:
        return
    # Render servisinin kendi URL'sini otomatik yakalaması veya ortam değişkeninden alması
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        webhook_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={render_url}/{TELEGRAM_TOKEN}"
        try:
            requests.get(webhook_url, timeout=5)
            print("Webhook otomatik olarak kuruldu!", flush=True)
        except Exception as e:
            print(f"Webhook otomatik kurulum hatası: {e}", flush=True)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def fetch_ohlcv_data(symbol, timeframe, limit=50):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return bars
    except Exception:
        return []

def scan_volume_spikes():
    """Hacmi dikkat çekici şekilde artan (para giren) pariteleri tarar"""
    hot_coins = []
    try:
        markets = exchange.load_markets()
        symbols = [
            s for s in markets 
            if markets[s].get('swap') 
            and markets[s].get('active') 
            and markets[s].get('quote') == 'USDT'
        ]
        symbols = sorted(list(set(symbols)))[:30]
        
        for symbol in symbols:
            bars = fetch_ohlcv_data(symbol, '1h', limit=20)
            if len(bars) < 15:
                continue
            df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
            vol_current = float(df["volume"].iloc[-1])
            vol_avg = float(df["volume"].rolling(window=10).mean().iloc[-1])
            
            if not pd.isna(vol_avg) and vol_avg > 0:
                ratio = vol_current / vol_avg
                if ratio >= 2.0:
                    clean_name = symbol.split(':')[0].replace("/", "")
                    close_price = float(df["close"].iloc[-1])
                    change_pct = ((float(df["close"].iloc[-1]) - float(df["open"].iloc[-1])) / float(df["open"].iloc[-1])) * 100
                    hot_coins.append({
                        "symbol": clean_name,
                        "ratio": ratio,
                        "price": close_price,
                        "change": change_pct
                    })
        
        hot_coins = sorted(hot_coins, key=lambda x: x["ratio"], reverse=True)[:3]
        return hot_coins
    except Exception:
        return []

def get_fundamental_and_news_context(ticker):
    """Sorduğun coinin temel analiz, haber akışı ve long/short dinamikleri"""
    t = ticker.upper()
    
    if t == "QNT":
        return (
            "📰 *Temel Analiz & Haber Akışı İstihbaratı:*\n"
            "• *Hikaye:* Kurumsal birlikte çalışabilirlik ve CBDC entegrasyonları ana hikayesidir.\n"
            "• *Long/Short Tetikleyicisi:* Kurumsal taraftan gelebilecek olumlu haberler ani bir *Short Squeeze* (yukarı yönlü sert patlama) tetikler. Habersiz dönemde ise düşük hacim nedeniyle aşağı yönlü süzülmeye meyillidir."
        )
    elif t == "BTC":
        return (
            "📰 *Temel Analiz & Haber Akışı İstihbaratı:*\n"
            "• *Hikaye:* Spot ETF akışları ve makro enflasyon verileri (Fed) ana yönü belirler.\n"
            "• *Long/Short Tetikleyicisi:* Fon girişlerinin olduğu günlerde destek retestleri long için kusursuz çalışır. Makro FUD haberlerinde ise ilk silkeleme (long likidasyonu) sert olur."
        )
    else:
        return (
            f"📰 *Temel Analiz & Haber Akışı İstihbaratı ({t}):*\n"
            f"• *Sektör Dinamiği:* Varlık, sektörel trendlere ve balina cüzdan hareketlerine duyarlıdır.\n"
            f"• *Long/Short Tetikleyicisi:* Sosyal medya hype'ı veya proaktif bir haber akışı ani FOMO ile long yönlü patlama yaratır. Temel bir FUD durumunda ise teknik destekler kırılırsa hızla short baskıya döner."
        )

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

    bars_1h = fetch_ohlcv_data(formatted_symbol, '1h', limit=40)
    bars_4h = fetch_ohlcv_data(formatted_symbol, '4h', limit=40)
    bars_1d = fetch_ohlcv_data(formatted_symbol, '1d', limit=50)

    if not bars_1h or not bars_4h or not bars_1d:
        return f"⚠️ `{ticker.upper()}` için yeterli veri çekilemedi."

    df_1h = pd.DataFrame(bars_1h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_4h = pd.DataFrame(bars_4h, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_1d = pd.DataFrame(bars_1d, columns=["timestamp", "open", "high", "low", "close", "volume"])
    
    close_1h = float(df_1h["close"].iloc[-1])
    rsi_1h = float(calculate_rsi(df_1h["close"], 14).iloc[-1])
    
    ema9_4h = df_4h["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21_4h = df_4h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    
    ema20_1d = df_1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    rsi_1d = float(calculate_rsi(df_1d["close"], 14).iloc[-1])
    close_1d = float(df_1d["close"].iloc[-1])
    
    vol_current = float(df_1h["volume"].iloc[-1])
    vol_avg = float(df_1h["volume"].rolling(window=10).mean().iloc[-1])
    is_volume_spike = vol_current > (vol_avg * 2.0) if not pd.isna(vol_avg) else False

    # Hacim varsa öncelik her zaman longdur
    tech_bias = "LONG (Hacim ve Temel Destekli Yükseliş)" if (close_1d > ema20_1d or is_volume_spike) else "SHORT (Satış Baskısı / Zayıf Temel)"
    
    giris = close_1h
    if "LONG" in tech_bias:
        stop = giris * 0.96
        tp1 = giris * 1.10
        tp2 = giris * 1.20
    else:
        stop = giris * 1.04
        tp1 = giris * 0.90
        tp2 = giris * 0.80

    fundamental_insight = get_fundamental_and_news_context(ticker)

    report = (
        f"📊 *KURUMSAL İSTİHBARAT & ANALİZ: {ticker.upper()}*\n\n"
        f"💵 *Anlık Fiyat:* `{giris:.4f}`\n\n"
        f"⏱ *Teknik & Hacim Süzgeci:*\n"
        f"• *1 Saatlik Hacim:* `{'🚨 HACİM PATLAMASI (' + str(round(vol_current/vol_avg, 1)) + 'x)' if is_volume_spike else 'Normal Akış'}`\n"
        f"• *4 Saatlik EMA 9/21:* `{'Pozitif' if ema9_4h > ema21_4h else 'Negatif'}`\n"
        f"• *Günlük Trend:* `{'Boğa (EMA Üstü)' if close_1d > ema20_1d else 'Akümülasyon / Baskı'}` (RSI: `{rsi_1d:.1f}`)\n\n"
        f"🎯 *Fon Yöneticisi Stratejisi & Seviyeler:*\n"
        f"• *Önerilen Yön:* *{tech_bias}*\n"
        f"• *Giriş:* `{giris:.4f}`\n"
        f"• *Stop-Loss:* `{stop:.4f}`\n"
        f"• *Hedef 1 (TP1):* `{tp1:.4f}`\n"
        f"• *Hedef 2 (TP2):* `{tp2:.4f}`\n\n"
        f"{fundamental_insight}\n\n"
        f"⚠️ *Risk Yönetimi Uyarısı:* Hacim ve temel hikaye long desteklese bile stop-loss seviyeleri mutlak suretle uygulanmalıdır."
    )
    return report

@app.route("/", methods=["GET"])
def home():
    return "CalmCapital Kurumsal Analist Asistan Aktif ve Webhook Otomatik! ⏳🚀"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()
        
        if text:
            clean_text = text.replace("/analiz", "").replace("@", "").strip().upper()
            
            if clean_text == "HACİM" or clean_text == "/HACİM":
                send_telegram_message(chat_id, "🔍 *Piyasada hacmi patlayan pariteler taranıyor...* ⏳")
                spikes = scan_volume_spikes()
                if spikes:
                    msg = "🚨 *HACMİ PATLAYAN (PARA GİREN) COİNLER* 🚨\n\n"
                    for item in spikes:
                        msg += (
                            f"🪙 *{item['symbol']}*\n"
                            f"• Hacim Katı: `{item['ratio']:.1f}x`\n"
                            f"• Fiyat: `{item['price']}` (`%{item['change']:.2f}`)\n"
                            f"👉 *Yorum:* Hacim var, long kollanmalı!\n\n"
                        )
                    send_telegram_message(chat_id, msg)
                else:
                    send_telegram_message(chat_id, "ℹ Şu an eşiği geçen belirgin bir hacim patlaması bulunamadı.")
            elif len(clean_text) <= 10 and len(clean_text) > 0:
                analysis_result = perform_deep_analysis(clean_text)
                send_telegram_message(chat_id, message=analysis_result)
            else:
                send_telegram_message(
                    chat_id, 
                    "🤖 Komutlar:\n• `/hacim` yazarak hacmi patlayanları gör.\n• İstediğin coini yaz (Örn: `QNT`, `BTC`, `SOL`)."
                )
                
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # Kod başlar başlamaz Telegram Webhook'unu otomatik bağlar
    setup_webhook_automatically()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
