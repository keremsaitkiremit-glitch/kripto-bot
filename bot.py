import ccxt
import requests
import pandas as pd
import time
import schedule
import threading
import os
from flask import Flask


# =========================================================
# WEB SERVER - RENDER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "CalmCapital piyasaları tarıyor! ⏳🚀"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# TELEGRAM AYARLARI
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# =========================================================
# TELEGRAM MESAJ GÖNDERME
# =========================================================

def send_telegram_message(message):

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN bulunamadı!")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID bulunamadı!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        print("Telegram HTTP:", response.status_code)
        print("Telegram cevap:", response.text)

        if response.ok:
            print("✅ Telegram mesajı gönderildi.")
            return True

        print("❌ Telegram mesajı gönderilemedi.")
        return False

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            repr(e)
        )

        return False


# =========================================================
# TELEGRAM TEST MESAJI
# =========================================================

def send_test_message():

    message = (
        "🚀 *CalmCapital başladı!*\n\n"
        "Bot başarıyla çalışıyor.\n"
        "📊 Piyasalar taranıyor..."
    )

    send_telegram_message(message)


# =========================================================
# BINANCE
# =========================================================

exchange = ccxt.binance({
    "options": {
        "defaultType": "future"
    },
    "enableRateLimit": True
})


# =========================================================
# MTF DESTEK / DİRENÇ SEVİYELERİ
# =========================================================

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

            bars = exchange.fetch_ohlcv(
                symbol,
                timeframe=tf_code,
                limit=2
            )

            if len(bars) >= 2:

                # Son tamamlanmış mum
                prev = bars[-2]

                high = prev[2]
                low = prev[3]
                close = prev[4]

                pivot = (high + low + close) / 3

                r1 = (2 * pivot) - low
                r2 = pivot + (high - low)

                s1 = (2 * pivot) - high
                s2 = pivot - (high - low)

                levels[tf_name] = {
                    "R2": r2,
                    "R1": r1,
                    "Pivot": pivot,
                    "S1": s1,
                    "S2": s2
                }

        except Exception as e:

            print(
                f"⚠️ {symbol} - {tf_name} "
                f"seviye hatası: {repr(e)}"
            )

    return levels


# =========================================================
# PARİTE ANALİZİ
# =========================================================

def analyze_symbol(symbol):

    try:

        bars = exchange.fetch_ohlcv(
            symbol,
            timeframe="15m",
            limit=100
        )

        if len(bars) < 50:
            return

        df = pd.DataFrame(
            bars,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        # -------------------------------------------------
        # EMA
        # -------------------------------------------------

        df["EMA_9"] = df["close"].ewm(
            span=9,
            adjust=False
        ).mean()

        df["EMA_21"] = df["close"].ewm(
            span=21,
            adjust=False
        ).mean()

        # -------------------------------------------------
        # HACİM ORTALAMASI
        # -------------------------------------------------

        df["vol_sma"] = df["volume"].rolling(
            window=20
        ).mean()

        son_mum = df.iloc[-1]

        close = float(son_mum["close"])
        ema9 = float(son_mum["EMA_9"])
        ema21 = float(son_mum["EMA_21"])
        hacim = float(son_mum["volume"])
        hacim_ortalamasi = float(son_mum["vol_sma"])

        if pd.isna(hacim_ortalamasi):
            return

        # -------------------------------------------------
        # MTF SEVİYELER
        # -------------------------------------------------

        mtf_levels = get_mtf_levels(symbol)

        if not mtf_levels:
            return

        # -------------------------------------------------
        # HACİM ONAYI
        # -------------------------------------------------

        hacim_onayi = hacim > (
            hacim_ortalamasi * 1.8
        )

        if not hacim_onayi:
            return

        # =================================================
        # SHORT
        # =================================================

        if ema9 < ema21:

            for tf, lvl in mtf_levels.items():

                r1 = lvl["R1"]
                r2 = lvl["R2"]

                r1_yakin = (
                    close >= r1 * 0.997
                    and close <= r1 * 1.003
                )

                r2_yakin = (
                    close >= r2 * 0.997
                    and close <= r2 * 1.003
                )

                if r1_yakin or r2_yakin:

                    giris = close

                    stop = giris * 1.015
                    hedef1 = giris * 0.985
                    hedef2 = giris * 0.970

                    mesaj = (
                        "🚨 *SHORT SİNYALİ* 🚨\n\n"
                        f"🪙 *Parite:* `{symbol}`\n"
                        f"📍 *Seviye:* {tf} Direnci\n\n"
                        f"📥 *Giriş:* `{giris:.6f}`\n"
                        f"🎯 *TP1:* `{hedef1:.6f}`\n"
                        f"🎯 *TP2:* `{hedef2:.6f}`\n"
                        f"🛑 *Stop:* `{stop:.6f}`\n\n"
                        "📊 *Kaldıraç:* Max 5x-10x"
                    )

                    print(
                        f"🚨 SHORT SİNYALİ: "
                        f"{symbol} - {tf}"
                    )

                    send_telegram_message(mesaj)

                    return

        # =================================================
        # LONG
        # =================================================

        elif ema9 > ema21:

            for tf, lvl in mtf_levels.items():

                s1 = lvl["S1"]
                r1 = lvl["R1"]

                # -----------------------------------------
                # DESTEK LONG
                # -----------------------------------------

                destek_yakin = (
                    close >= s1 * 0.997
                    and close <= s1 * 1.003
                )

                if destek_yakin:

                    giris = close

                    stop = giris * 0.985
                    hedef1 = giris * 1.015
                    hedef2 = giris * 1.030

                    mesaj = (
                        "🟢 *LONG SİNYALİ* 🟢\n\n"
                        f"🪙 *Parite:* `{symbol}`\n"
                        f"📍 *Seviye:* {tf} Desteği\n\n"
                        f"📥 *Giriş:* `{giris:.6f}`\n"
                        f"🎯 *Hedef 1:* `{hedef1:.6f}`\n"
                        f"🎯 *Hedef 2:* `{hedef2:.6f}`\n"
                        f"🛑 *Stop:* `{stop:.6f}`\n\n"
                        "📊 *Kaldıraç:* Max 5x-10x"
                    )

                    print(
                        f"🟢 LONG SİNYALİ: "
                        f"{symbol} - {tf}"
                    )

                    send_telegram_message(mesaj)

                    return

                # -----------------------------------------
                # R1 KIRILIM LONG
                # -----------------------------------------

                kirilim = (
                    close > r1
                    and close < r1 * 1.006
                )

                if kirilim:

                    giris = close

                    stop = giris * 0.985
                    hedef1 = giris * 1.015
                    hedef2 = giris * 1.030

                    mesaj = (
                        "🟢 *LONG SİNYALİ - KIRILIM* 🟢\n\n"
                        f"🪙 *Parite:* `{symbol}`\n"
                        f"📍 *Seviye:* {tf} Kırılımı\n\n"
                        f"📥 *Giriş:* `{giris:.6f}`\n"
                        f"🎯 *Hedef 1:* `{hedef1:.6f}`\n"
                        f"🎯 *Hedef 2:* `{hedef2:.6f}`\n"
                        f"🛑 *Stop:* `{stop:.6f}`\n\n"
                        "📊 *Kaldıraç:* Max 5x-10x"
                    )

                    print(
                        f"🟢 LONG KIRILIM: "
                        f"{symbol} - {tf}"
                    )

                    send_telegram_message(mesaj)

                    return

    except Exception as e:

        print(
            f"❌ {symbol} analiz hatası: "
            f"{repr(e)}"
        )


# =========================================================
# TÜM PİYASAYI TARA
# =========================================================

def bot_run():

   print(
    f"\n[{time.strftime('%H:%M:%S')}] "
    "📊 Piyasalar taranıyor...",
    flush=True
)

    try:

        markets = exchange.load_markets()

        symbols = [
            s
            for s in markets
            if (
                s.endswith("/USDT")
                and markets[s].get("active")
                and "UP/" not in s
                and "DOWN/" not in s
            )
        ]

        print(
    f"🔎 {len(symbols)} parite bulundu.",
    flush=True
)

        for symbol in symbols:

            analyze_symbol(symbol)

            time.sleep(0.3)

        print("✅ Piyasa taraması tamamlandı.", flush=True)

    except Exception as e:

        print(
            "❌ Piyasa tarama hatası:",
            repr(e)
        )


# =========================================================
# SCHEDULER
# =========================================================

def run_scheduler():

    print("🚀 CalmCapital bot başlatılıyor...")

    # Telegram test mesajı
    send_test_message()

    # Her 15 dakikada bir
    schedule.every(15).minutes.do(bot_run)

    # Bot açılır açılmaz bir tarama
    bot_run()

    while True:

        try:

            schedule.run_pending()

        except Exception as e:

            print(
                "❌ Scheduler hatası:",
                repr(e)
            )

        time.sleep(1)


# =========================================================
# PROGRAMI BAŞLAT
# =========================================================

if __name__ == "__main__":

    print("======================================")
    print("🚀 CALMCAPITAL BAŞLATILIYOR")
    print("======================================")

    print(
        "Telegram token durumu:",
        "OK" if TELEGRAM_TOKEN else "YOK"
    )

    print(
        "Telegram chat ID durumu:",
        "OK" if TELEGRAM_CHAT_ID else "YOK"
    )

    # Scheduler ayrı thread
    t = threading.Thread(
        target=run_scheduler,
        daemon=True
    )

    t.start()

    # Flask / Render
    run_flask()
