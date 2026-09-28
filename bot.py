import ccxt
import requests
import pandas as pd
import time
import schedule
import threading
import os
from flask import Flask

# === WEB SUNUCUSU (Render'ın kapanmaması için) ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Kripto Sinyal Botu Aktif ve Çalışıyor! 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# === TELEGRAM AYARLARI ===
TELEGRAM_TOKEN = '8923553015:AAFzkhX27Jejk2oTvqMEV2kDfp38aXs2DhU' # BotFather token'ın
TELEGRAM_CHAT_ID = '@CalmCappital'

# Telegram'a test mesajı gönder
def send_test_message():
    token = TELEGRAM_TOKEN  
    chat_id = TELEGRAM_CHAT_ID
    message = "CalmCapital piyasayı tarıyor! ⏳🚀"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Test mesajı hatası: {e}")

exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram gönderim hatası:", e)

def get_mtf_levels(symbol):
    levels = {}
    # 4 Saatlik (4h) zaman dilimi buraya eklendi!
    timeframes = {'4 Saatlik': '4h', 'Günlük': '1d', 'Haftalık': '1w', 'Aylık': '1M'}
    
    for tf_name, tf_code in timeframes.items():
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=tf_code, limit=2)
            if len(bars) >= 2:
                prev = bars[0]
                high, low, close = prev[2], prev[3], prev[4]
                
                pivot = (high + low + close) / 3
                r1 = (2 * pivot) - low
                r2 = pivot + (high - low)
                s1 = (2 * pivot) - high
                s2 = pivot - (high - low)
                
                levels[tf_name] = {'R2': r2, 'R1': r1, 'Pivot': pivot, 'S1': s1, 'S2': s2}
        except Exception:
            continue
    return levels

def analyze_symbol(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        if len(bars) < 50:
            return
            
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['vol_sma'] = df['volume'].rolling(window=20).mean()
        
        son_mum = df.iloc[-1]
        close = son_mum['close']
        ema9 = son_mum['EMA_9']
        ema21 = son_mum['EMA_21']
        hacim = son_mum['volume']
        hacim_ortalamasi = son_mum['vol_sma']
        
        mtf_levels = get_mtf_levels(symbol)
        if not mtf_levels:
            return
            
        hacim_onayi = hacim > (hacim_ortalamasi * 1.8)
        if not hacim_onayi:
            return

        # --- 🔴 SHORT STRATEJİSİ ---
        if ema9 < ema21:
            for tf, lvl in mtf_levels.items():
                r1 = lvl['R1']
                r2 = lvl['R2']
                if (close >= r1 * 0.997 and close <= r1 * 1.003) or (close >= r2 * 0.997 and close <= r2 * 1.003):
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

        # --- 🟢 LONG STRATEJİSİ ---
        elif ema9 > ema21:
            for tf, lvl in mtf_levels.items():
                s1 = lvl['S1']
                r1 = lvl['R1']
                
                if close >= s1 * 0.997 and close <= s1 * 1.003:
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
                    
                elif close > r1 and close < r1 * 1.006:
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

    except Exception as e:
        pass

def bot_run():
    print(f"\n[{time.strftime('%H:%M:%S')}] Piyasalar taranıyor...")
    try:
        markets = exchange.load_markets()
        symbols = [s for s in markets if s.endswith('/USDT') and markets[s]['active'] and not 'UP/' in s and not 'DOWN/' in s]
        for symbol in symbols:
            analyze_symbol(symbol)
            time.sleep(0.3)
    except Exception as e:
        print("Hata:", e)

def run_scheduler():
    schedule.every(15).minutes.do(bot_run)
    bot_run()
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    t = threading.Thread(target=run_scheduler)
    t.daemon = True
    t.start()
    
    run_flask()
