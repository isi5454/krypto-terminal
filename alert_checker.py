"""
Separates Skript für 24/7-Preis-Alarme.
Wird von GitHub Actions per Zeitplan ausgefuehrt (siehe .github/workflows/alarme.yml).
Braucht KEINE Streamlit-Umgebung, nur: pip install requests pandas
"""
import os
import requests
import pandas as pd

BIN_ID = os.environ["JSONBIN_BIN_ID"]
API_KEY = os.environ["JSONBIN_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

JSONBIN_BASIS = "https://api.jsonbin.io/v3/b"
BINANCE_BASIS = "https://api.binance.com/api/v3"


def zustand_laden():
    r = requests.get(f"{JSONBIN_BASIS}/{BIN_ID}/latest", headers={"X-Master-Key": API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()["record"]


def zustand_speichern(zustand):
    r = requests.put(
        f"{JSONBIN_BASIS}/{BIN_ID}", json=zustand,
        headers={"X-Master-Key": API_KEY, "Content-Type": "application/json"}, timeout=15,
    )
    r.raise_for_status()


def binance_closes_holen(symbol, intervall="15m", limit=100):
    r = requests.get(
        f"{BINANCE_BASIS}/klines",
        params={"symbol": symbol, "interval": intervall, "limit": limit}, timeout=15,
    )
    r.raise_for_status()
    rohdaten = r.json()
    return [float(k[4]) for k in rohdaten]


def rsi(werte, periode=14):
    s = pd.Series(werte)
    if len(s) <= periode:
        return None
    delta = s.diff()
    gewinn = delta.clip(lower=0).rolling(periode).mean()
    verlust = (-delta.clip(upper=0)).rolling(periode).mean()
    rs = gewinn / verlust.replace(0, 1e-9)
    return float(100 - (100 / (1 + rs)).iloc[-1])


def telegram_nachricht_senden(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text}, timeout=15,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def main():
    zustand = zustand_laden()
    alerts = zustand.get("alerts", [])
    veraendert = False

    for alarm in alerts:
        if alarm.get("ausgeloest"):
            continue

        symbol = f"{alarm['ticker']}USDT"
        try:
            closes = binance_closes_holen(symbol)
        except requests.RequestException as fehler:
            print(f"Konnte Daten fuer {symbol} nicht laden: {fehler}")
            continue

        if not closes:
            continue

        preis = closes[-1]
        rsi_wert = rsi(closes)
        typ = alarm["typ"]
        schwelle = alarm["schwelle"]
        ausgeloest = False
        text = None

        if typ == "preis_ueber" and preis > schwelle:
            ausgeloest = True
            text = f"🔔 {alarm['ticker']}: Preis $ {preis:,.2f} liegt über deiner Schwelle $ {schwelle:,.2f}"
        elif typ == "preis_unter" and preis < schwelle:
            ausgeloest = True
            text = f"🔔 {alarm['ticker']}: Preis $ {preis:,.2f} liegt unter deiner Schwelle $ {schwelle:,.2f}"
        elif typ == "rsi_ueber" and rsi_wert is not None and rsi_wert > schwelle:
            ausgeloest = True
            text = f"🔔 {alarm['ticker']}: RSI {rsi_wert:.1f} liegt über deiner Schwelle {schwelle}"
        elif typ == "rsi_unter" and rsi_wert is not None and rsi_wert < schwelle:
            ausgeloest = True
            text = f"🔔 {alarm['ticker']}: RSI {rsi_wert:.1f} liegt unter deiner Schwelle {schwelle}"

        if ausgeloest:
            gesendet = telegram_nachricht_senden(text)
            if gesendet:
                alarm["ausgeloest"] = True
                veraendert = True
                print(f"Alarm ausgelöst und gesendet: {text}")

    if veraendert:
        zustand_speichern(zustand)
    else:
        print("Keine neuen Alarme ausgelöst.")


if __name__ == "__main__":
    main()
