import ccxt
import pandas as pd
import time
import schedule
import threading
import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "CalmCapital Bybit Botu Aktif ve Çalışıyor! ⏳🚀"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# === TELEGRAM AYARLARI (Render Environment Variables'dan okur) ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "@CalmCappital")

def send_telegram_message(message):
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN bulunamadı!", flush=True)
        return False
    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID bulunamadı!", flush=True)
        return False

    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        return response.ok
    except Exception as e:
        print(f"Telegram bağlantı hatası: {repr(e)}", flush=True)
        return False

def send_test_message():
    send_telegram_message(
        "🚀 *CalmCapital Başlatıldı!*\n\n"
        "Bot başarıyla çalışıyor.\n"
        "📊 Bybit Futures (CCXT) piyasaları taranıyor..."
    )

# CCXT üzerinden Bybit Futures bağlantısı (403 hatasını engeller)
exchange = ccxt.bybit({
    'options': {'defaultType': 'swap'},
    'enableRateLimit': True
})

def get_symbols():
    print("Bybit USDT Futures pariteleri yükleniyor...", flush=True)
    try:
        markets = exchange.load_markets()
        symbols = [
            s for s in markets 
            if s.endswith('/USDT') 
            and markets[s]['active'] 
            and 'linear' in markets[s].get('info', {}).get('contractType', 'linear')
            and not 'UP/' in s 
            and not 'DOWN/' in s
        ]
        print(f"{len(symbols)} Bybit USDT paritesi bulundu.", flush=True)
        return symbols
    except Exception as e:
        print(f"Bybit pariteleri alınamadı: {repr(e)}", flush=True)
        return []

def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return bars
    except Exception:
        return []

def get_mtf_levels(symbol):
    levels = {}
    timeframes = {
        "4 Saatlik": "4h",
        "Günlük": "1d",
        "Haftalık": "1w",
        "Aylık": "1M"
    }
    
    for tf_name, tf_code in timeframes.items():
        try:
            bars = fetch_ohlcv(symbol, timeframe=tf_code, limit=3)
            if len(bars) < 2:
                continue
                
            prev = bars[-2]
            high, low, close = float(prev[2]), float(prev[3]), float(prev[4])
            
            pivot = (high + low + close) / 3
            r1 = (2 * pivot) - low
            r2 = pivot + (high - low)
            s1 = (2 * pivot) - high
            s2 = pivot - (high - low)
            
            levels[tf_name] = {
                "R2": r2, "R1": r1, "Pivot": pivot, "S1": s1, "S2": s2
            }
        except Exception:
            continue
    return levels

def analyze_symbol(symbol):
    try:
        bars = fetch_ohlcv(symbol, timeframe='15m', limit=100)
        if len(bars) < 50:
            return
            
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()
        df["vol_sma"] = df["volume"].rolling(window=20).mean()
        
        son_mum = df.iloc[-1]
        close = float(son_mum["close"])
        ema9 = float(son_mum["EMA_9"])
        ema21 = float(son_mum["EMA_21"])
        hacim = float(son_mum["volume"])
        hacim_ortalamasi = float(son_mum["vol_sma"])
        
        if pd.isna(hacim_ortalamasi) or hacim <= hacim_ortalamasi * 1.8:
            return
            
        mtf_levels = get_mtf_levels(symbol)
        if not mtf_levels:
            return
            
        if ema9 < ema21:
            for tf, lvl in mtf_levels.items():
                r1, r2 = lvl["R1"], lvl["R2"]
                if (r1 * 0.997 <= close <= r1 * 1.003) or (r2 * 0.997 <= close <= r2 * 1.003):
                    giris = close
                    stop = giris * 1.015
                    hedef1 = giris * 0.985
                    hedef2 = giris * 0.970
                    
                    mesaj = (
                        "🚨 *SHORT SİNYALİ* 🚨\n\n"
                        f"🪙 Parite: `{symbol}`\n"
                        f"📍 Seviye: {tf} Direnci\n\n"
                        f"📥 Giriş: `{giris:.6f}`\n"
                        f"🎯 TP1: `{hedef1:.6f}`\n"
                        f"🎯 TP2: `{hedef2:.6f}`\n"
                        f"🛑 Stop: `{stop:.6f}`\n\n"
                        "📊 Kaldıraç: Max 5x-10x"
                    )
                    send_telegram_message(mesaj)
                    return
                    
        elif ema9 > ema21:
            for tf, lvl in mtf_levels.items():
                s1, r1 = lvl["S1"], lvl["R1"]
                
                if s1 * 0.997 <= close <= s1 * 1.003:
                    giris = close
                    stop = giris * 0.985
                    hedef1 = giris * 1.015
                    hedef2 = giris * 1.030
                    
                    mesaj = (
                        "🟢 *LONG SİNYALİ* 🟢\n\n"
                        f"🪙 Parite: `{symbol}`\n"
                        f"📍 Seviye: {tf} Desteği\n\n"
                        f"📥 Giriş: `{giris:.6f}`\n"
                        f"🎯 Hedef 1: `{hedef1:.6f}`\n"
                        f"🎯 Hedef 2: `{hedef2:.6f}`\n"
                        f"🛑 Stop: `{stop:.6f}`\n\n"
                        "📊 Kaldıraç: Max 5x-10x"
                    )
                    send_telegram_message(mesaj)
                    return
                    
                if r1 < close < r1 * 1.006:
                    giris = close
                    stop = giris * 0.985
                    hedef1 = giris * 1.015
                    hedef2 = giris * 1.030
                    
                    mesaj = (
                        "🟢 *LONG KIRILIM SİNYALİ* 🟢\n\n"
                        f"🪙 Parite: `{symbol}`\n"
                        f"📍 Seviye: {tf} Kırılımı\n\n"
                        f"📥 Giriş: `{giris:.6f}`\n"
                        f"🎯 Hedef 1: `{hedef1:.6f}`\n"
                        f"🎯 Hedef 2: `{hedef2:.6f}`\n"
                        f"🛑 Stop: `{stop:.6f}`\n\n"
                        "📊 Kaldıraç: Max 5x-10x"
                    )
                    send_telegram_message(mesaj)
                    return
    except Exception:
        pass

def bot_run():
    print(f"\n[{time.strftime('%H:%M:%S')}] Bybit piyasaları taranıyor...", flush=True)
    symbols = get_symbols()
    if symbols:
        for symbol in symbols:
            analyze_symbol(symbol)
            time.sleep(0.3)
    print("Tarama tamamlandı.", flush=True)

def run_scheduler():
    print("CalmCapital bot başlatılıyor...", flush=True)
    send_test_message()
    schedule.every(15).minutes.do(bot_run)
    bot_run()
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    run_flask()
