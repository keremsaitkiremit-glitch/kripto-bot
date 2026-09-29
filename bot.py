import requests
import pandas as pd
import time
import schedule
import threading
import os
from flask import Flask

app = Flask(**name**)

@app.route("/")
def home():
return "CalmCapital piyasaları tarıyor! ⏳🚀"

def run_flask():
port = int(os.environ.get("PORT", 10000))
app.run(host="0.0.0.0", port=port)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
if not TELEGRAM_TOKEN:
print("TELEGRAM_TOKEN bulunamadı!", flush=True)
return False

```
if not TELEGRAM_CHAT_ID:
    print("TELEGRAM_CHAT_ID bulunamadı!", flush=True)
    return False

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

try:
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=10
    )

    print(f"Telegram HTTP: {response.status_code}", flush=True)
    print(f"Telegram cevap: {response.text}", flush=True)

    return response.ok

except Exception as e:
    print(f"Telegram bağlantı hatası: {repr(e)}", flush=True)
    return False
```

def send_test_message():
send_telegram_message(
"🚀 CalmCapital başladı!\n\n"
"Bot başarıyla çalışıyor.\n"
"📊 Bybit piyasaları taranıyor..."
)

BYBIT_BASE_URL = "https://api.bybit.com"

session = requests.Session()
session.headers.update({
"User-Agent": "CalmCapital/1.0"
})

def bybit_get(endpoint, params=None):
url = f"{BYBIT_BASE_URL}{endpoint}"

```
response = session.get(
    url,
    params=params,
    timeout=15
)

response.raise_for_status()

data = response.json()

if data.get("retCode") != 0:
    raise Exception(
        f"Bybit API hatası: "
        f"{data.get('retCode')} - "
        f"{data.get('retMsg')}"
    )

return data
```

def get_symbols():
print(
"Bybit USDT Futures piyasaları yükleniyor...",
flush=True
)

```
symbols = []
cursor = None

try:
    while True:
        params = {
            "category": "linear",
            "limit": 500
        }

        if cursor:
            params["cursor"] = cursor

        data = bybit_get(
            "/v5/market/instruments-info",
            params
        )

        result = data.get("result", {})
        instruments = result.get("list", [])

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

        cursor = result.get("nextPageCursor")

        if not cursor:
            break

        time.sleep(0.2)

    symbols = sorted(list(set(symbols)))

    print(
        f"{len(symbols)} Bybit USDT paritesi bulundu.",
        flush=True
    )

    return symbols

except Exception as e:
    print(
        f"Bybit pariteleri alınamadı: {repr(e)}",
        flush=True
    )
    return []
```

def fetch_ohlcv(symbol, interval, limit=100):
params = {
"category": "linear",
"symbol": symbol,
"interval": interval,
"limit": limit
}

```
data = bybit_get(
    "/v5/market/kline",
    params
)

rows = data.get(
    "result",
    {}
).get(
    "list",
    []
)

if not rows:
    return []

rows = list(reversed(rows))

result = []

for row in rows:
    if len(row) < 7:
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
```

def get_mtf_levels(symbol):
levels = {}

```
timeframes = {
    "4 Saatlik": "240",
    "Günlük": "D",
    "Haftalık": "W",
    "Aylık": "M"
}

for tf_name, tf_code in timeframes.items():
    try:
        bars = fetch_ohlcv(
            symbol,
            tf_code,
            limit=3
        )

        if len(bars) < 2:
            continue

        prev = bars[-2]

        high = float(prev[2])
        low = float(prev[3])
        close = float(prev[4])

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
            f"{symbol} {tf_name} hata: {repr(e)}",
            flush=True
        )

return levels
```

def analyze_symbol(symbol):
try:
bars = fetch_ohlcv(
symbol,
"15",
limit=100
)

```
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

    df["EMA_9"] = df["close"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["EMA_21"] = df["close"].ewm(
        span=21,
        adjust=False
    ).mean()

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

    if hacim <= hacim_ortalamasi * 1.8:
        return

    mtf_levels = get_mtf_levels(symbol)

    if not mtf_levels:
        return

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
                    "🚨 SHORT SİNYALİ 🚨\n\n"
                    f"🪙 Parite: {symbol}\n"
                    f"📍 Seviye: {tf} Direnci\n\n"
                    f"📥 Giriş: {giris:.6f}\n"
                    f"🎯 TP1: {hedef1:.6f}\n"
                    f"🎯 TP2: {hedef2:.6f}\n"
                    f"🛑 Stop: {stop:.6f}\n\n"
                    "📊 Kaldıraç: Max 5x-10x"
                )

                print(
                    f"SHORT: {symbol} - {tf}",
                    flush=True
                )

                send_telegram_message(mesaj)
                return

    elif ema9 > ema21:
        for tf, lvl in mtf_levels.items():
            s1 = lvl["S1"]
            r1 = lvl["R1"]

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
                    "🟢 LONG SİNYALİ 🟢\n\n"
                    f"🪙 Parite: {symbol}\n"
                    f"📍 Seviye: {tf} Desteği\n\n"
                    f"📥 Giriş: {giris:.6f}\n"
                    f"🎯 Hedef 1: {hedef1:.6f}\n"
                    f"🎯 Hedef 2: {hedef2:.6f}\n"
                    f"🛑 Stop: {stop:.6f}\n\n"
                    "📊 Kaldıraç: Max 5x-10x"
                )

                print(
                    f"LONG: {symbol} - {tf}",
                    flush=True
                )

                send_telegram_message(mesaj)
                return

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
                    "🟢 LONG KIRILIM SİNYALİ 🟢\n\n"
                    f"🪙 Parite: {symbol}\n"
                    f"📍 Seviye: {tf} Kırılımı\n\n"
                    f"📥 Giriş: {giris:.6f}\n"
                    f"🎯 Hedef 1: {hedef1:.6f}\n"
                    f"🎯 Hedef 2: {hedef2:.6f}\n"
                    f"🛑 Stop: {stop:.6f}\n\n"
                    "📊 Kaldıraç: Max 5x-10x"
                )

                print(
                    f"LONG KIRILIM: {symbol} - {tf}",
                    flush=True
                )

                send_telegram_message(mesaj)
                return

except Exception as e:
    print(
        f"{symbol} analiz hatası: {repr(e)}",
        flush=True
    )
```

def bot_run():
print(
f"\n[{time.strftime('%H:%M:%S')}] "
"Piyasalar taranıyor...",
flush=True
)

```
try:
    symbols = get_symbols()

    if not symbols:
        print(
            "Analiz edilecek parite bulunamadı.",
            flush=True
        )
        return

    print(
        f"Tarama başlayacak: {len(symbols)} parite",
        flush=True
    )

    for index, symbol in enumerate(
        symbols,
        start=1
    ):
        print(
            f"Analiz: {index}/{len(symbols)} - {symbol}",
            flush=True
        )

        analyze_symbol(symbol)
        time.sleep(0.25)

    print(
        "Piyasa taraması tamamlandı.",
        flush=True
    )

except Exception as e:
    print(
        f"Piyasa tarama hatası: {repr(e)}",
        flush=True
    )
```

def run_scheduler():
print(
"CalmCapital bot başlatılıyor...",
flush=True
)

```
send_test_message()

schedule.every(15).minutes.do(
    bot_run
)

print(
    "15 dakikalık tarama zamanlayıcısı kuruldu.",
    flush=True
)

bot_run()

while True:
    try:
        schedule.run_pending()
    except Exception as e:
        print(
            f"Scheduler hatası: {repr(e)}",
            flush=True
        )

    time.sleep(1)
```

if **name** == "**main**":
print(
"======================================",
flush=True
)

```
print(
    "CALMCAPITAL BAŞLATILIYOR",
    flush=True
)

print(
    "======================================",
    flush=True
)

print(
    "Telegram token durumu:",
    "OK" if TELEGRAM_TOKEN else "YOK",
    flush=True
)

print(
    "Telegram chat ID durumu:",
    "OK" if TELEGRAM_CHAT_ID else "YOK",
    flush=True
)

scheduler_thread = threading.Thread(
    target=run_scheduler,
    daemon=True
)

scheduler_thread.start()

print(
    "Flask sunucusu başlatılıyor...",
    flush=True
)

run_flask()
```
