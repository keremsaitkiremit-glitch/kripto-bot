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

app = Flask(**name**)

@app.route("/")
def home():
return "CalmCapital piyasaları tarıyor! ⏳🚀"

def run_flask():
port = int(os.environ.get("PORT", 10000))
app.run(host="0.0.0.0", port=port)

# =========================================================

# TELEGRAM

# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_message(message):

```
if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN bulunamadı!", flush=True)
    return False

if not TELEGRAM_CHAT_ID:
    print("❌ TELEGRAM_CHAT_ID bulunamadı!", flush=True)
    return False

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": message
}

try:
    response = requests.post(
        url,
        json=payload,
        timeout=10
    )

    print(
        f"Telegram HTTP: {response.status_code}",
        flush=True
    )

    print(
        f"Telegram cevap: {response.text}",
        flush=True
    )

    if response.ok:
        print(
            "✅ Telegram mesajı gönderildi.",
            flush=True
        )
        return True

    return False

except Exception as e:
    print(
        "❌ Telegram bağlantı hatası:",
        repr(e),
        flush=True
    )
    return False
```

def send_test_message():

```
print(
    "🔵 Telegram test mesajı gönderiliyor...",
    flush=True
)

message = (
    "🚀 CalmCapital başladı!\n\n"
    "Bot başarıyla çalışıyor.\n"
    "📊 Bybit piyasaları taranıyor..."
)

send_telegram_message(message)
```

# =========================================================

# BYBIT

# =========================================================

BYBIT_BASE_URL = "https://api.bybit.com"

session = requests.Session()

session.headers.update({
"User-Agent": "CalmCapital/1.0"
})

def bybit_get(endpoint, params=None):

```
url = f"{BYBIT_BASE_URL}{endpoint}"

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

# =========================================================

# BYBIT PARİTELERİ

# =========================================================

def get_symbols():

```
print(
    "🔄 Bybit USDT Futures piyasaları yükleniyor...",
    flush=True
)

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

        instruments = result.get(
            "list",
            []
        )

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

        cursor = result.get(
            "nextPageCursor"
        )

        if not cursor:
            break

        time.sleep(0.2)

    symbols = sorted(
        list(set(symbols))
    )

    print(
        f"✅ {len(symbols)} Bybit USDT paritesi bulundu.",
        flush=True
    )

    return symbols

except Exception as e:

    print(
        "❌ Bybit pariteleri alınamadı:",
        repr(e),
        flush=True
    )

    return []
```

# =========================================================

# BYBIT KLINE

# =========================================================

def fetch_ohlcv(symbol, interval, limit=100):

```
params = {
    "category": "linear",
    "symbol": symbol,
    "interval": interval,
    "limit": limit
}

data = bybit_get(
    "/v5/market/kline",
    params
)

rows = (
    data
    .get("result", {})
    .get("list", [])
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

# =========================================================

# MTF DESTEK / DİRENÇ

# =========================================================

def get_mtf_levels(symbol):

```
levels = {}

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

        pivot = (
            high + low + close
        ) / 3

        r1 = (
            2 * pivot
        ) - low

        r2 = (
            pivot + (high - low)
        )

        s1 = (
            2 * pivot
        ) - high

        s2 = (
            pivot
```
