import requests
import pandas as pd
import time
import schedule
import threading
import os
from flask import Flask

app = Flask(__name__)

# Web sunucusu ana sayfası
@app.route("/")
def home():
    return "CalmCapital piyasaları tarıyor! ⏳🚀"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# === TELEGRAM AYARLARI (Render Environment Variables'dan okur) ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "@CalmCappital")

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
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
    # Bot başlar başlamaz atılacak ilk mesaj
    send_telegram_message("CalmCapital piyasaları tarıyor! ⏳🚀")

# === BYBIT BAĞLANTISI (CloudFront 403 Bypass) ===
BYBIT_BASE_URL = "https://api.bybit.com"
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
})

def bybit_get(endpoint, params=None):
    url = f"{BYBIT_BASE_URL}{endpoint}"
    response = session.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    if data.get("retCode") != 0:
        raise Exception(f"Bybit API hatası: {data.get('retCode')} - {data.get('retMsg')}")
    return data

def get_symbols():
    print("Bybit USDT Futures pariteleri yükleniyor...", flush=True)
    symbols = []
    try:
        params = {"category": "linear", "limit": 500}
        data = bybit_get("/v5/market/instruments-info", params)
        instruments = data.get("result", {}).get("list", [])
        
        for item in instruments:
            symbol = item.get("symbol")
            status = item.get("status")
            settle_coin = item.get("settleCoin")
            
            if (
                symbol
                and symbol.endswith("USDT")
                and status == "Trading"
                and settle_coin == "USDT"
                and "UP" not in symbol
                and "DOWN" not in symbol
            ):
                symbols.append(symbol)
                
        symbols = sorted(list(set(symbols)))
        print(f"{len(symbols)} Bybit USDT paritesi bulundu.", flush=True)
        return symbols
    except Exception as e:
        print(f"Bybit pariteleri alınamadı: {repr(e)}", flush=True)
        return []

def fetch_ohlcv(symbol, interval, limit=100):
    try:
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        data = bybit_get("/v5/market/kline", params)
        rows = data.get("result", {}).get("list", [])
        if not rows:
            return []
        
        rows = list(reversed(rows))
        result = []
        for row in rows:
            if len(row) < 6:
                continue
            result.append([
                int(row[0]),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5])
            ])
        return result
    except Exception:
        return []

def get_mtf_levels(symbol):
    levels = {}
    timeframes = {
        "4 Saatlik": "240",
        "Günlük": "D",
        "Haftalık": "W",
        "Aylık": "M"
    }
    
    for tf_name, tf_code in timeframes.items():
        try:
            bars = fetch_ohlcv(symbol, tf_code, limit=3)
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
        bars = fetch_ohlcv(symbol, "15", limit=100)
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
                        f"🚨 *SHORT SİNYALİ* 🚨\n"
                        f"🪙 *Parite:* `{symbol}` ({tf} Direnci)\n\n"
                        f"📥 *Giriş Fiyatı:* `{giris}`\n"
                        f"🎯 *TP1:* `{hedef1:.4f}`\n"
                        f"🎯 *TP2:* `{hedef2:.4f}`\n"
                        f"🛑 *Stop:* `{stop:.4f}`\n"
                        f"📊 *Kaldıraç:* Max 5x-10x"
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
                        f"🟢 *LONG SİNYALİ* 🟢\n"
                        f"🪙 *Parite:* `{symbol}` ({tf} Desteği)\n\n"
                        f"📥 *Giriş Fiyatı:* `{giris}`\n"
                        f"🎯 *Hedef 1:* `{hedef1:.4f}`\n"
                        f"🎯 *Hedef 2:* `{hedef2:.4f}`\n"
                        f"🛑 *Zarar Durdurma:* `{stop:.4f}`\n"
                        f"📊 *Kaldıraç Önerisi:* Max 5x-10x"
                    )
                    send_telegram_message(mesaj)
                    return
                    
                if r1 < close < r1 * 1.006:
                    giris = close
                    stop = giris * 0.985
                    hedef1 = giris * 1.015
                    hedef2 = giris * 1.030
                    
                    mesaj = (
                        f"🟢 *LONG SİNYALİ (Kırılım)* 🟢\n"
                        f"🪙 *Parite:* `{symbol}` ({tf} Kırılımı)\n\n"
                        f"📥 *Giriş Fiyatı:* `{giris}`\n"
                        f"🎯 *Hedef 1:* `{hedef1:.4f}`\n"
                        f"🎯 *Hedef 2:* `{hedef2:.4f}`\n"
                        f"🛑 *Zarar Durdurma:* `{stop:.4f}`\n"
                        f"📊 *Kaldıraç Önerisi:* Max 5x-10x"
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
            # IP engeline takılmamak için 0.25 saniye bekleme süresi
            time.sleep(0.25)
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
