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
    return "CalmCapital Çift Yönlü Kurumsal Bot Aktif! ⏳🚀"

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
def check_macro_bias(symbol):
    """Aylık ve Haftalık Yön Teyidi"""
    try:
        # Haftalık Kontrol
        w_bars = fetch_ohlcv(symbol, '1w', limit=30)
        if len(w_bars) < 25:
            return None
        w_df = pd.DataFrame(w_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        w_ema21 = w_df["close"].ewm(span=21, adjust=False).mean().iloc[-1]
        w_close = w_df["close"].iloc[-1]
        
        # Aylık Kontrol
        m_bars = fetch_ohlcv(symbol, '1M', limit=15)
        m_df = pd.DataFrame(m_bars, columns=["timestamp", "open", "high", "low", "close", "volume"]) if len(m_bars) >= 10 else None
        
        if w_close > w_ema21:
            return "BULLISH"
        elif w_close < w_ema21:
            return "BEARISH"
    except Exception:
        pass
    return None

def check_daily_filter(symbol, trend_direction):
    """Günlük: EMA 20/50 ve RSI Kontrolü"""
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
        rsi = last["RSI"]
        
        if trend_direction == "BEARISH":
            if close < last["EMA_20"] and close < last["EMA_50"] and rsi < 50:
                return True
        elif trend_direction == "BULLISH":
            if close > last["EMA_20"] and close > last["EMA_50"] and rsi > 50:
                return True
    except Exception:
        pass
    return False

def check_12h_filter(symbol, trend_direction):
    """12 Saatlik: MACD ve ADX > 25 Kontrolü"""
    try:
        bars = fetch_ohlcv(symbol, '12h', limit=50)
        if len(bars) < 40:
            return False
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        
        adx = calculate_adx(df["high"], df["low"], df["close"], 14)
        
        last_macd = macd.iloc[-1]
        last_signal = signal.iloc[-1]
        last_adx = adx.iloc[-1]
        
        if last_adx > 25:
            if trend_direction == "BEARISH" and last_macd < last_signal:
                return True
            elif trend_direction == "BULLISH" and last_macd > last_signal:
                return True
    except Exception:
        pass
    return False

def get_pivot_levels(symbol):
    """4 Saatlik Pivot Seviyeleri (Destek ve Direnç)"""
    try:
        bars = fetch_ohlcv(symbol, '4h', limit=3)
        if len(bars) < 2:
            return None
        prev = bars[-2]
        high, low, close = float(prev[2]), float(prev[3]), float(prev[4])
        pivot = (high + low + close) / 3
        r1 = (2 * pivot) - low
        r2 = pivot + (high - low)
        s1 = (2 * pivot) - high
        s2 = pivot - (high - low)
        return {"R1": r1, "R2": r2, "S1": s1, "S2": s2}
    except Exception:
        return None

def analyze_symbol(symbol):
    try:
        # 1. Aşama: Makro Yön Teyidi (Aylık/Haftalık)
        bias = check_macro_bias(symbol)
        if not bias:
            return
            
        # 2. Aşama: Günlük Filtre
        if not check_daily_filter(symbol, bias):
            return
            
        # 3. Aşama: 12 Saatlik Filtre
        if not check_12h_filter(symbol, bias):
            return
            
        # 4. Aşama: 4 Saatlik Tetiklenme (Retest + RSI Dönüşü + Hacim Artışı)
        bars = fetch_ohlcv(symbol, '4h', limit=30)
        if len(bars) < 25:
            return
            
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()
        df["RSI"] = calculate_rsi(df["close"], 14)
        df["vol_sma"] = df["volume"].rolling(window=10).mean()
        
        close = float(df["close"].iloc[-1])
        vol = float(df["volume"].iloc[-1])
        vol_avg = float(df["vol_sma"].iloc[-1])
        
        # Hacim Artışı Kontrolü
        if pd.isna(vol_avg) or vol <= vol_avg * 1.3:
            return
            
        rsi_last = float(df["RSI"].iloc[-1])
        rsi_prev = float(df["RSI"].iloc[-2])
        pivots = get_pivot_levels(symbol)
        if not pivots:
            return
            
        clean_symbol = symbol.split(':')[0].replace("/", "")
        
        # --- SHORT SENARYOSU ---
        if bias == "BEARISH":
            if rsi_last >= rsi_prev: # RSI düşüşte olmalı
                return
            r1, r2 = pivots["R1"], pivots["R2"]
            at_resistance = (r1 * 0.997 <= close <= r1 * 1.003) or (r2 * 0.997 <= close <= r2 * 1.003) or (close >= r1)
            
            if at_resistance:
                giris = close
                stop = giris * 1.04
                hedef1 = giris * 0.90
                hedef2 = giris * 0.80
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
                
        # --- LONG SENARYOSU ---
        elif bias == "BULLISH":
            if rsi_last <= rsi_prev: # RSI yükselişte olmalı
                return
            s1, s2 = pivots["S1"], pivots["S2"]
            at_support = (s1 * 0.997 <= close <= s1 * 1.003) or (s2 * 0.997 <= close <= s2 * 1.003) or (close <= s1)
            
            if at_support:
                giris = close
                stop = giris * 0.96
                hedef1 = giris * 1.10
                hedef2 = giris * 1.20
                mesaj = (
                    f"🟢 *KURUMSAL LONG SİNYALİ* 🟢\n"
                    f"🪙 *Parite:* `{clean_symbol}` (4S Destek Retest)\n\n"
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
    print(f"\n[{time.strftime('%H:%M:%S')}] Çift Yönlü Kurumsal tarama başlıyor...", flush=True)
    symbols = get_symbols()
    if symbols:
        for symbol in symbols:
            analyze_symbol(symbol)
            time.sleep(0.3)
    print("Tarama tamamlandı.", flush=True)

def run_scheduler():
    print("CalmCapital çift yönlü bot başlatılıyor...", flush=True)
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
