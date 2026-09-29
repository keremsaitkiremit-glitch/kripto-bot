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
    return "CalmCapital Short Odaklı Modda Tarıyor! ⏳🚀"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# === TELEGRAM AYARLARI ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "@CalmCappital")

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
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
    except Exception:
        return False

def send_test_message():
    send_telegram_message("CalmCapital piyasaları tarıyor! ⏳🚀 ")

# === BORSAYA BAĞLANTI (MEXC Futures - İlk 500 Yüksek Hacimli Parite) ===
exchange = ccxt.mexc({
    'options': {'defaultType': 'swap'},
    'enableRateLimit': True
})

def get_symbols():
    print("MEXC USDT Futures pariteleri yükleniyor...", flush=True)
    try:
        markets = exchange.load_markets()
        symbols = [
            s for s in markets 
            if markets[s].get('swap') 
            and markets[s].get('active') 
            and markets[s].get('quote') == 'USDT'
        ]
        symbols = sorted(list(set(symbols)))[:500]
        print(f"{len(symbols)} USDT paritesi (ilk 500) yüklendi.", flush=True)
        return symbols
    except Exception as e:
        print(f"Pariteler alınamadı: {repr(e)}", flush=True)
        return []

def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return bars
    except Exception:
        return []

def check_higher_timeframe_trend(symbol):
    """4 Saatlik grafikte ana trendin düşüşte (BEARISH) olup olmadığını kontrol eder"""
    try:
        bars = fetch_ohlcv(symbol, '4h', limit=30)
        if len(bars) < 25:
            return None
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()
        
        last = df.iloc[-1]
        if last["EMA_9"] < last["EMA_21"]:
            return "BEARISH" # 4H Düşüş trendinde
    except Exception:
        pass
    return None

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
        # 1. 4 Saatlik ana trend düşüşte mi? Değilse direkt ele.
        htf_trend = check_higher_timeframe_trend(symbol)
        if htf_trend != "BEARISH":
            return

        # 2. 15 Dakikalık veriler
        bars = fetch_ohlcv(symbol, '15m', limit=100)
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
        
        # Sert Hacim Filtresi: Ortalamanın en az 2.5 katı hacim
        if pd.isna(hacim_ortalamasi) or hacim <= hacim_ortalamasi * 2.5:
            return
            
        mtf_levels = get_mtf_levels(symbol)
        if not mtf_levels:
            return
            
        clean_symbol = symbol.split(':')[0].replace("/", "")
            
        # 3. 15m'de de EMA 9 < EMA 21 (Short teyidi)
        if ema9 < ema21:
            for tf, lvl in mtf_levels.items():
                r1, r2 = lvl["R1"], lvl["R2"]
                # Direnç bölgesi teması
                if (r1 * 0.998 <= close <= r1 * 1.002) or (r2 * 0.998 <= close <= r2 * 1.002):
                    giris = close
                    stop = giris * 1.04       # %4 Stop
                    hedef1 = giris * 0.90     # %10 TP1
                    hedef2 = giris * 0.80     # %20 TP2
                    
                    mesaj = (
                        f"🚨 *SHORT SİNYALİ* 🚨\n"
                        f"🪙 *Parite:* `{clean_symbol}` ({tf} Direnci)\n\n"
                        f"📥 *Giriş Fiyatı:* `{giris}`\n"
                        f"🎯 *TP1 (%10):* `{hedef1:.4f}`\n"
                        f"🎯 *TP2 (%20):* `{hedef2:.4f}`\n"
                        f"🛑 *Stop (%4):* `{stop:.4f}`\n"
                        f"📊 *Kaldıraç:* Max 5x"
                    )
                    send_telegram_message(mesaj)
                    return
    except Exception:
        pass

def bot_run():
    print(f"\n[{time.strftime('%H:%M:%S')}] Short odaklı piyasa taraması...", flush=True)
    symbols = get_symbols()
    if symbols:
        for symbol in symbols:
            analyze_symbol(symbol)
            time.sleep(0.25)
    print("Tarama tamamlandı.", flush=True)

def run_scheduler():
    print("CalmCapital short bot başlatılıyor...", flush=True)
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
