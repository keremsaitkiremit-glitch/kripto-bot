import ccxt
import pandas as pd
import numpy as np
import time
import schedule
import threading
import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "CalmCapital Kurumsal Short Botu Aktif! ⏳🚀"

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
    send_telegram_message("CalmCapital piyasaları tarıyor! ⏳🚀 (Mod: Kurumsal Multi-TF Short)")

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

# --- İNDİKATÖR YARDIMCI FONKSİYONLARI ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
    
    tr1 = high - low
    tr2 = np.abs(high - close.shift())
    tr3 = np.abs(low - close.shift())
    tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
    tr_smooth = tr.rolling(window=period).sum()
    
    plus_di = 100 * (pd.Series(plus_dm).rolling(window=period).sum() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm).rolling(window=period).sum() / tr_smooth)
    
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    return adx

# --- KONTROL FONKSİYONLARI (Zaman Dilimleri) ---
def check_monthly_weekly_bias(symbol):
    """Aylık ve Haftalık Bias Kontrolü: Bearish / Nötr-Bearish ve Haftalık EMA altında"""
    try:
        # Haftalık Kontrol
        w_bars = fetch_ohlcv(symbol, '1w', limit=30)
        if len(w_bars) < 25:
            return False
        w_df = pd.DataFrame(w_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        w_ema21 = w_df["close"].ewm(span=21, adjust=False).mean().iloc[-1]
        w_close = w_df["close"].iloc[-1]
        
        if w_close > w_ema21:
            return False # Haftalık EMA üzerindeyse short iptal
            
        # Aylık Kontrol
        m_bars = fetch_ohlcv(symbol, '1M', limit=15)
        if len(m_bars) >= 10:
            m_df = pd.DataFrame(m_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
            m_open = m_df["open"].iloc[-1]
            m_close = m_df["close"].iloc[-1]
            # Aylık kırmızı veya yatay/baskılı ise kabul (Bearish / Nötr-Bearish)
            if m_close > m_open * 1.05: # Çok sert aylık yeşilse geç
                return False
                
        return True
    except Exception:
        return False

def check_daily_filter(symbol):
    """Günlük: EMA 20/50 altında + RSI < 50"""
    try:
        bars = fetch_ohlcv(symbol, '1d', limit=60)
        if len(bars) < 55:
            return False
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["EMA_20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["EMA_50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["RSI"] = calculate_rsi(df["close"], 14)
        
        last = df.iloc[-1]
        close = last["close"]
        if close < last["EMA_20"] and close < last["EMA_50"] and last["RSI"] < 50:
            return True
    except Exception:
        pass
    return False

def check_12h_filter(symbol):
    """12 Saatlik: MACD Bearish + ADX > 25"""
    try:
        bars = fetch_ohlcv(symbol, '12h', limit=50)
        if len(bars) < 40:
            return False
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # MACD Hesaplama (12, 26, 9)
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        
        adx = calculate_adx(df["high"], df["low"], df["close"], 14)
        
        last_macd = macd.iloc[-1]
        last_signal = signal.iloc[-1]
        last_adx = adx.iloc[-1]
        
        if last_macd < last_signal and last_adx > 25:
            return True
    except Exception:
        pass
    return False

def get_pivot_resistance(symbol):
    """4 Saatlik Pivot R1 ve R2 Seviyeleri"""
    try:
        bars = fetch_ohlcv(symbol, '4h', limit=3)
        if len(bars) < 2:
            return None
        prev = bars[-2]
        high, low, close = float(prev[2]), float(prev[3]), float(prev[4])
        pivot = (high + low + close) / 3
        r1 = (2 * pivot) - low
        r2 = pivot + (high - low)
        return {"R1": r1, "R2": r2}
    except Exception:
        return None

def analyze_symbol(symbol):
    try:
        # 1. Aşama: Aylık ve Haftalık Bias Kontrolü
        if not check_monthly_weekly_bias(symbol):
            return
            
        # 2. Aşama: Günlük Filtre (EMA 20/50 altı + RSI < 50)
        if not check_daily_filter(symbol):
            return
            
        # 3. Aşama: 12 Saatlik Filtre (MACD Bearish + ADX > 25)
        if not check_12h_filter(symbol):
            return
            
        # 4. Aşama: 4 Saatlik Tetiklenme (Direnç Retest + RSI Aşağı Dönüş + Hacim Artışı)
        bars = fetch_ohlcv(symbol, '4h', limit=30)
        if len(bars) < 25:
            return
            
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()
        df["RSI"] = calculate_rsi(df["close"], 14)
        df["vol_sma"] = df["volume"].rolling(window=10).mean()
        
        last = df.iloc.values[-1]
        prev = df.iloc.values[-2]
        
        close = float(df["close"].iloc[-1])
        vol = float(df["volume"].iloc[-1])
        vol_avg = float(df["vol_sma"].iloc[-1])
        
        # Hacim Artışı (Ortalamanın üstünde hacim)
        if pd.isna(vol_avg) or vol <= vol_avg * 1.3:
            return
            
        # 4H RSI tekrar aşağı dönüyor olmalı (Örn: Önceki mumda yukarı yönlüydü veya tepedeydi, şimdi düşüyor)
        rsi_last = float(df["RSI"].iloc[-1])
        rsi_prev = float(df["RSI"].iloc[-2])
        if rsi_last >= rsi_prev: # RSI düşüşte değilse es geç
            return
            
        # Direnç Retest Kontrolü (Pivot R1 veya R2 yakınlaşması)
        pivots = get_pivot_resistance(symbol)
        if not pivots:
            return
            
        r1, r2 = pivots["R1"], pivots["R2"]
        at_resistance = (r1 * 0.997 <= close <= r1 * 1.003) or (r2 * 0.997 <= close <= r2 * 1.003) or (close >= r1)
        
        if not at_resistance:
            return
            
        # Tüm kurallar kusursuz sağlandı -> Sinyal Gönder!
        clean_symbol = symbol.split(':')[0].replace("/", "")
        giris = close
        stop = giris * 1.04       # %4 Stop
        hedef1 = giris * 0.90     # %10 TP1
        hedef2 = giris * 0.80     # %20 TP2
        
        mesaj = (
            f"🚨 *KURUMSAL SHORT SİNYALİ* 🚨\n"
            f"🪙 *Parite:* `{clean_symbol}` (4S Direnç Retest)\n\n"
            f"📥 *Giriş Fiyatı:* `{giris}`\n"
            f"🎯 *TP1 (%10):* `{hedef1:.4f}`\n"
            f"🎯 *TP2 (%20):* `{hedef2:.4f}`\n"
            f"🛑 *Stop (%4):* `{stop:.4f}`\n"
            f"📊 *Kaldıraç:* Max 5x"
        )
        send_telegram_message(mesaj)
        
    except Exception:
        pass

def bot_run():
    print(f"\n[{time.strftime('%H:%M:%S')}] Kurumsal Multi-TF Short taraması başlıyor...", flush=True)
    symbols = get_symbols()
    if symbols:
        for symbol in symbols:
            analyze_symbol(symbol)
            time.sleep(0.3)
    print("Tarama tamamlandı.", flush=True)

def run_scheduler():
    print("CalmCapital kurumsal bot başlatılıyor...", flush=True)
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
