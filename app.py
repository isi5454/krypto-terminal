import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Krypto Monitoring Terminal", page_icon="⚡", layout="wide")

# --- 🔑 SECRETS (in Streamlit Cloud unter "Secrets" eintragen, NICHT im Code) ---
BIN_ID = st.secrets["JSONBIN_BIN_ID"]
API_KEY = st.secrets["JSONBIN_API_KEY"]

# --- 🌐 DATENQUELLE: CoinGecko ---
# Wichtig: NICHT Binance, weil Binance Anfragen von Cloud-Servern (AWS/GCP) blockiert -
# dasträfe sowohl Streamlit Cloud als auch GitHub Actions. CoinGecko blockiert das nicht.
COINGECKO_BASIS = "https://api.coingecko.com/api/v3"
JSONBIN_BASIS = "https://api.jsonbin.io/v3/b"

TICKER_ZU_ID = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "XRP": "ripple", "ADA": "cardano", "LINK": "chainlink",
    "PAXG": "pax-gold",
}

TIMEFRAME_ZU_TAGE = {
    "⏱️ 1 Tag": 1,
    "🕐 1 Woche": 7,
    "🛑 1 Monat": 30,
    "📅 3 Monate": 90,
}

ALARM_TYP_ANZEIGE = {
    "preis_ueber": "Preis über",
    "preis_unter": "Preis unter",
    "rsi_ueber": "RSI über",
    "rsi_unter": "RSI unter",
}

# --- 🌍 HANDELSSITZUNGEN ---
# Gängige, häufig verwendete Richtwerte - keine offiziell regulierten Öffnungszeiten
# (Krypto und Gold-Token wie PAXG handeln durchgehend). Wichtig für Volatilität,
# NICHT für die Richtung (hoch/runter) - siehe Hinweis im entsprechenden Reiter.
SITZUNGEN = {
    "🌏 Asien (Tokio)": {"start_utc": 0, "ende_utc": 9},
    "🇬🇧 Europa (London)": {"start_utc": 8, "ende_utc": 17},
    "🇺🇸 Amerika (New York)": {"start_utc": 13, "ende_utc": 22},
}
LOKALE_ZEITZONE = "Europe/Vienna"

# --- 📈 AKTIEN (Finnhub) ---
# Wichtig: Finnhub gibt auf dem kostenlosen Plan keine historischen Kerzen für
# Aktien frei (getestet: "error" bei /stock/candle) - deshalb hier nur der
# Live-Snapshot über /quote, keine Indikatoren/Signale wie bei Krypto/Gold.
FINNHUB_API_KEY = st.secrets.get("FINNHUB_API_KEY", "")
FINNHUB_BASIS = "https://finnhub.io/api/v1"
AKTIEN_TICKER = ["AAPL", "NVDA", "TSLA"]


@st.cache_data(ttl=60, show_spinner=False)
def finnhub_quote_holen(symbol: str):
    if not FINNHUB_API_KEY:
        return None
    try:
        r = requests.get(f"{FINNHUB_BASIS}/quote", params={"symbol": symbol, "token": FINNHUB_API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def aktien_snapshot_auswerten(quote):
    if not quote or quote.get("c") in (None, 0):
        return None
    preis = quote["c"]
    pc = quote.get("pc") or 0
    o = quote.get("o") or 0
    return {
        "preis": preis,
        "veraenderung_tag": (preis - pc) / pc * 100 if pc else None,
        "veraenderung_seit_open": (preis - o) / o * 100 if o else None,
    }


def sitzungs_status():
    jetzt_utc = datetime.now(timezone.utc)
    stunde_utc = jetzt_utc.hour
    ergebnisse = []
    for name, zeiten in SITZUNGEN.items():
        start, ende = zeiten["start_utc"], zeiten["ende_utc"]
        offen = start <= stunde_utc < ende
        ergebnisse.append({"name": name, "start_utc": start, "ende_utc": ende, "offen": offen})
    return ergebnisse, jetzt_utc


def utc_stunde_zu_lokal(utc_stunde, ziel_zone=LOKALE_ZEITZONE):
    heute = datetime.now(timezone.utc).date()
    utc_zeit = datetime(heute.year, heute.month, heute.day, utc_stunde % 24, 0, tzinfo=timezone.utc)
    lokale_zeit = utc_zeit.astimezone(ZoneInfo(ziel_zone))
    return lokale_zeit.strftime("%H:%M")


@st.cache_data(ttl=1800, show_spinner=False)
def coingecko_preise_mit_zeit_holen(coingecko_id: str, tage: int = 90):
    """Stündliche (bei days 2-90) Schlusskurse mit Zeitstempel - für die
    Sitzungs-Statistik. Nur Nahepreis, keine echten OHLC-Kerzen nötig."""
    try:
        r = requests.get(
            f"{COINGECKO_BASIS}/coins/{coingecko_id}/market_chart",
            params={"vs_currency": "usd", "days": tage}, timeout=15,
        )
        r.raise_for_status()
        return r.json().get("prices", [])
    except requests.RequestException:
        return []


def stunden_analyse(punkte, vorschau_stunden=2):
    """Für jede der 24 UTC-Stunden: historische Ø-%-Veränderung X Stunden später.
    Reine Vergangenheitsstatistik, keine Vorhersage - Grundlage für die grafische
    24h-Übersicht (ersetzt die einzelnen Sitzungs-Expander durch EIN Bild)."""
    if len(punkte) < 50:
        return {"grund": "keine_daten"}
    zeiten = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in punkte]
    preise = [p[1] for p in punkte]
    veraenderungen_je_stunde = {h: [] for h in range(24)}
    for i in range(len(punkte) - vorschau_stunden):
        stunde = zeiten[i].hour
        veraenderung = (preise[i + vorschau_stunden] - preise[i]) / preise[i] * 100
        veraenderungen_je_stunde[stunde].append(veraenderung)
    stunden_werte = {}
    for h, werte in veraenderungen_je_stunde.items():
        if len(werte) >= 5:
            stunden_werte[h] = {
                "durchschnitt": sum(werte) / len(werte),
                "anzahl": len(werte),
                "prozent_positiv": sum(1 for w in werte if w > 0) / len(werte) * 100,
            }
    if not stunden_werte:
        return {"grund": "zu_wenig_pro_stunde"}
    return {"grund": "ok", "stunden": stunden_werte}


def stunden_chart(ergebnis, ziel_zone=LOKALE_ZEITZONE):
    zeilen = []
    for utc_stunde, werte in ergebnis.items():
        zeilen.append({"utc_stunde": utc_stunde, "lokal": utc_stunde_zu_lokal(utc_stunde, ziel_zone), **werte})
    zeilen.sort(key=lambda z: z["lokal"])
    x = [z["lokal"] for z in zeilen]
    y = [z["durchschnitt"] for z in zeilen]
    farben = ["#10b981" if v >= 0 else "#ef4444" for v in y]
    fig = go.Figure(go.Bar(
        x=x, y=y, marker_color=farben,
        text=[f"{v:+.2f}%" for v in y], textposition="outside",
        hovertext=[f"{z['anzahl']}× vorgekommen, {z['prozent_positiv']:.0f}% davon positiv" for z in zeilen],
    ))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=20, b=10), template="plotly_dark",
        yaxis_title="Ø Veränderung (%)", xaxis_title="Uhrzeit (deine Zeit)",
    )
    return fig


# --- 💾 PERSISTENTER SPEICHER (JSONBin – überlebt Neustarts & Neuladen) ---

def zustand_laden():
    try:
        r = requests.get(f"{JSONBIN_BASIS}/{BIN_ID}/latest", headers={"X-Master-Key": API_KEY}, timeout=10)
        r.raise_for_status()
        record = r.json().get("record", {})
        record.setdefault("watchlist", ["BTC", "ETH", "SOL"])
        record.setdefault("portfolio", [])
        record.setdefault("alerts", [])
        record.setdefault("hypo_trades", {"offen": [], "geschlossen": []})
        if "PAXG" not in record["watchlist"]:
            record["watchlist"].append("PAXG")
            try:
                requests.put(
                    f"{JSONBIN_BASIS}/{BIN_ID}", json=record,
                    headers={"X-Master-Key": API_KEY, "Content-Type": "application/json"}, timeout=10,
                )
            except requests.RequestException:
                pass
        return record
    except requests.RequestException:
        st.warning("Persistenter Speicher aktuell nicht erreichbar – Änderungen werden evtl. nicht gespeichert.")
        return {"watchlist": ["BTC", "ETH", "SOL", "PAXG"], "portfolio": [], "alerts": []}


def zustand_speichern():
    try:
        r = requests.put(
            f"{JSONBIN_BASIS}/{BIN_ID}",
            json=st.session_state.zustand,
            headers={"X-Master-Key": API_KEY, "Content-Type": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
    except requests.RequestException:
        st.warning("Speichern fehlgeschlagen – bitte gleich nochmal versuchen.")


if "zustand" not in st.session_state:
    st.session_state.zustand = zustand_laden()


# --- 🌐 COINGECKO MARKTDATEN ---

@st.cache_data(ttl=86400, show_spinner=False)
def coingecko_id_ermitteln(ticker: str):
    if ticker in TICKER_ZU_ID:
        return TICKER_ZU_ID[ticker]
    try:
        r = requests.get(f"{COINGECKO_BASIS}/search", params={"query": ticker}, timeout=10)
        r.raise_for_status()
        for coin in r.json().get("coins", []):
            if coin.get("symbol", "").upper() == ticker:
                return coin["id"]
    except requests.RequestException:
        pass
    return None


@st.cache_data(ttl=60, show_spinner=False)
def coingecko_ohlc_holen(coingecko_id: str, tage: int):
    try:
        r = requests.get(
            f"{COINGECKO_BASIS}/coins/{coingecko_id}/ohlc",
            params={"vs_currency": "usd", "days": tage}, timeout=15,
        )
        r.raise_for_status()
        rohdaten = r.json()
    except requests.RequestException:
        return None
    if not rohdaten:
        return None
    df = pd.DataFrame(rohdaten, columns=["zeit_ms", "open", "high", "low", "close"])
    df["zeit"] = pd.to_datetime(df["zeit_ms"], unit="ms")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def coingecko_volumen_holen(coingecko_id: str, tage: int):
    try:
        r = requests.get(
            f"{COINGECKO_BASIS}/coins/{coingecko_id}/market_chart",
            params={"vs_currency": "usd", "days": tage}, timeout=15,
        )
        r.raise_for_status()
        punkte = r.json().get("total_volumes", [])
        return [p[1] for p in punkte]
    except requests.RequestException:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def aktuellen_preis_holen(coingecko_id: str):
    try:
        r = requests.get(
            f"{COINGECKO_BASIS}/simple/price",
            params={"ids": coingecko_id, "vs_currencies": "usd"}, timeout=10,
        )
        r.raise_for_status()
        return r.json().get(coingecko_id, {}).get("usd")
    except (requests.RequestException, KeyError, ValueError):
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fear_greed_index_holen():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        r.raise_for_status()
        eintrag = r.json()["data"][0]
        return int(eintrag["value"]), eintrag["value_classification"]
    except (requests.RequestException, KeyError, IndexError):
        return None, None


@st.cache_data(ttl=300, show_spinner=False)
def coingecko_markt_uebersicht(seiten: int = 2):
    """Viele Coins mit 1h/24h-%-Veränderung für die Top-Bewegungen-Übersicht.
    Scannt die Top (seiten×250) Coins nach Marktkapitalisierung."""
    alle = []
    for seite in range(1, seiten + 1):
        try:
            r = requests.get(
                f"{COINGECKO_BASIS}/coins/markets",
                params={
                    "vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": 250, "page": seite,
                    "price_change_percentage": "1h,24h", "sparkline": "false",
                },
                timeout=15,
            )
            r.raise_for_status()
            daten = r.json()
            if not daten:
                break
            alle.extend(daten)
        except requests.RequestException:
            break
    return alle


def top_bewegungen(marktdaten, zeitraum="24h", schwelle=10.0, anzahl=10):
    """Filtert/sortiert Coins nach absoluter %-Veränderung (beide Richtungen)."""
    feld = "price_change_percentage_1h_in_currency" if zeitraum == "1h" else "price_change_percentage_24h_in_currency"
    kandidaten = []
    for coin in marktdaten:
        veraenderung = coin.get(feld)
        if veraenderung is None:
            continue
        if abs(veraenderung) >= schwelle:
            kandidaten.append({
                "symbol": coin.get("symbol", "").upper(),
                "name": coin.get("name"),
                "preis": coin.get("current_price"),
                "veraenderung": veraenderung,
            })
    kandidaten.sort(key=lambda k: abs(k["veraenderung"]), reverse=True)
    return kandidaten[:anzahl]


# --- 📐 INDIKATOREN ALS VOLLSTÄNDIGE ZEITREIHEN (für aktuelle Anzeige UND Backtest) ---

def indikator_serien_berechnen(closes, highs, lows):
    s = pd.Series(closes)
    h = pd.Series(highs)
    l = pd.Series(lows)

    delta = s.diff()
    gewinn = delta.clip(lower=0).rolling(14).mean()
    verlust = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gewinn / verlust.replace(0, 1e-9)
    rsi_serie = 100 - (100 / (1 + rs))

    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd_serie = ema12 - ema26
    signal_serie = macd_serie.ewm(span=9, adjust=False).mean()

    bb_mittel = s.rolling(20).mean()
    bb_std = s.rolling(20).std()
    bb_oben = bb_mittel + 2 * bb_std
    bb_unten = bb_mittel - 2 * bb_std

    tief_14 = l.rolling(14).min()
    hoch_14 = h.rolling(14).max()
    stoch_k = 100 * (s - tief_14) / (hoch_14 - tief_14).replace(0, 1e-9)
    stoch_d = stoch_k.rolling(3).mean()

    sma_trend = s.rolling(50).mean()

    prev_close = s.shift(1)
    prev_high = h.shift(1)
    prev_low = l.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    plus_dm_raw = h - prev_high
    minus_dm_raw = prev_low - l
    plus_dm = pd.Series(np.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0), plus_dm_raw, 0), index=s.index)
    minus_dm = pd.Series(np.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0), minus_dm_raw, 0), index=s.index)
    tr_glatt = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_dm_glatt = plus_dm.ewm(alpha=1 / 14, adjust=False).mean()
    minus_dm_glatt = minus_dm.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * plus_dm_glatt / tr_glatt.replace(0, 1e-9)
    minus_di = 100 * minus_dm_glatt / tr_glatt.replace(0, 1e-9)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
    adx_serie = dx.ewm(alpha=1 / 14, adjust=False).mean()

    return {
        "rsi": rsi_serie, "macd": macd_serie, "signal": signal_serie,
        "bb_mittel": bb_mittel, "bb_oben": bb_oben, "bb_unten": bb_unten,
        "stoch_k": stoch_k, "stoch_d": stoch_d, "sma_trend": sma_trend, "adx": adx_serie,
    }


def score_bei_index(serien, closes, highs, lows, i, fib_fenster=100):
    """Kombiniert 6 Indikatoren zu einem Score (-6 bis +6) und liefert die Gründe
    in Klartext. Rein beschreibend, was die Indikatoren JETZT zeigen -
    keine Vorhersage und keine Handlungsempfehlung.
    Fibonacci nutzt bewusst nur ein RÜCKBLICKENDES Fenster (kein Blick in die
    Zukunft) - sonst wäre der Backtest weiter unten geschönt."""
    preis = closes[i]
    rsi_wert = serien["rsi"].iloc[i]
    macd_wert = serien["macd"].iloc[i]
    signal_wert = serien["signal"].iloc[i]
    bb_oben = serien["bb_oben"].iloc[i]
    bb_unten = serien["bb_unten"].iloc[i]
    stoch_k = serien["stoch_k"].iloc[i]
    trend = serien["sma_trend"].iloc[i]
    adx_wert = serien["adx"].iloc[i]

    score = 0
    gruende = []
    if pd.notna(rsi_wert):
        if rsi_wert < 32:
            score += 1; gruende.append(f"RSI überverkauft ({rsi_wert:.0f})")
        elif rsi_wert > 70:
            score -= 1; gruende.append(f"RSI überkauft ({rsi_wert:.0f})")
    if pd.notna(macd_wert) and pd.notna(signal_wert):
        if macd_wert > signal_wert:
            score += 1; gruende.append("MACD über Signallinie")
        else:
            score -= 1; gruende.append("MACD unter Signallinie")
    if pd.notna(bb_oben) and pd.notna(bb_unten):
        if preis < bb_unten:
            score += 1; gruende.append("Preis unter unterem Bollinger-Band")
        elif preis > bb_oben:
            score -= 1; gruende.append("Preis über oberem Bollinger-Band")
    if pd.notna(stoch_k):
        if stoch_k < 20:
            score += 1; gruende.append(f"Stochastik überverkauft ({stoch_k:.0f})")
        elif stoch_k > 80:
            score -= 1; gruende.append(f"Stochastik überkauft ({stoch_k:.0f})")
    if pd.notna(trend):
        if preis > trend:
            score += 1; gruende.append("Preis über Trend-SMA(50)")
        else:
            score -= 1; gruende.append("Preis unter Trend-SMA(50)")

    # 6. Faktor: Fibonacci - nur rückblickendes Fenster, kein Blick in die Zukunft
    fenster_start = max(0, i - fib_fenster + 1)
    fib_level_lokal = fibonacci_level_berechnen(highs[fenster_start:i + 1], lows[fenster_start:i + 1])
    if fib_level_lokal and i >= fenster_start + 10:
        tiefstes_kuerzlich = min(lows[max(fenster_start, i - 2):i + 1])
        hoechstes_kuerzlich = max(highs[max(fenster_start, i - 2):i + 1])
        for name, wert in fib_level_lokal.items():
            if wert <= 0:
                continue
            if abs(tiefstes_kuerzlich - wert) / wert * 100 < 1.0 and preis > wert:
                score += 1; gruende.append(f"Preis hat Fib-Level {name} als Unterstützung bestätigt")
                break
            if abs(hoechstes_kuerzlich - wert) / wert * 100 < 1.0 and preis < wert:
                score -= 1; gruende.append(f"Preis an Fib-Level {name} abgewiesen")
                break

    if score >= 4:
        kategorie = "Stark bullisch"
    elif score >= 1:
        kategorie = "Leicht bullisch"
    elif score <= -4:
        kategorie = "Stark bärisch"
    elif score <= -1:
        kategorie = "Leicht bärisch"
    else:
        kategorie = "Neutral"

    trend_stark = bool(pd.notna(adx_wert) and adx_wert > 25)
    return score, kategorie, gruende, trend_stark, (float(adx_wert) if pd.notna(adx_wert) else None)


@st.cache_data(ttl=600, show_spinner=False)
def backtest_kategorie(closes, highs, lows, ziel_kategorie, vorschau=5):
    """Sucht in der Historie nach Momenten mit der GLEICHEN Signal-Kategorie und
    zeigt, wie sich der Kurs danach tatsächlich entwickelt hat. Echte historische
    Zahlen statt eines Versprechens - Vergangenheit ist keine Garantie für die Zukunft."""
    serien = indikator_serien_berechnen(closes, highs, lows)
    n = len(closes)
    start = 50
    ende = n - vorschau
    if ende <= start:
        return {"grund": "zu_kurzer_zeitraum"}
    treffer = []
    for i in range(start, ende):
        _, kategorie, _, _, _ = score_bei_index(serien, closes, highs, lows, i)
        if kategorie == ziel_kategorie:
            veraenderung = (closes[i + vorschau] - closes[i]) / closes[i] * 100
            treffer.append(veraenderung)
    if len(treffer) < 5:
        return {"grund": "zu_wenig_faelle", "anzahl": len(treffer)}
    serie = pd.Series(treffer)
    return {
        "grund": "ok",
        "anzahl": len(treffer),
        "prozent_positiv": float((serie > 0).mean() * 100),
        "durchschnitt": float(serie.mean()),
        "schlechtester": float(serie.min()),
        "bester": float(serie.max()),
    }


def fibonacci_level_berechnen(highs, lows):
    """Fibonacci-Retracement-Level zwischen höchstem Hoch und tiefstem Tief der
    geladenen Historie. Reine Referenz-Zonen für möglichen Support/Widerstand,
    kein Kauf-/Verkaufssignal - der Markt muss ein Level nicht respektieren."""
    hoch = max(highs)
    tief = min(lows)
    spanne = hoch - tief
    if spanne <= 0:
        return None
    return {
        "0.0%": hoch,
        "23.6%": hoch - spanne * 0.236,
        "38.2%": hoch - spanne * 0.382,
        "50.0%": hoch - spanne * 0.5,
        "61.8%": hoch - spanne * 0.618,
        "78.6%": hoch - spanne * 0.786,
        "100.0%": tief,
    }


def naechstes_fib_level(preis, level_dict):
    if not level_dict:
        return None
    name, wert = min(level_dict.items(), key=lambda kv: abs(kv[1] - preis))
    abstand_prozent = abs(preis - wert) / preis * 100
    return name, wert, abstand_prozent


def bollinger_baender_serie(werte, periode=20, anzahl_std=2):
    s = pd.Series(werte)
    mittel = s.rolling(periode).mean()
    std = s.rolling(periode).std()
    return mittel, mittel + anzahl_std * std, mittel - anzahl_std * std


def atr_wert(highs, lows, closes, periode=14):
    """Aktueller ATR als absoluter Preis-Betrag (nicht Prozent) - für Stop/Ziel bei
    hypothetischen Positionen im Vorwärts-Tracking."""
    if len(closes) < periode + 1:
        return None
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(periode).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else None


def hypo_trades_aktualisieren(ticker, daten):
    """Vorwärts-Tracking: protokolliert, was passiert wäre, wenn man jedem starken
    Signal gefolgt wäre. Läuft nur, wenn die App offen ist (kein 24/7 wie die Alarme).
    Ziel/Stop nach ATR, ähnlich der Logik aus dem Vergleichs-Tool des Kollegen."""
    hypo = st.session_state.zustand.setdefault("hypo_trades", {"offen": [], "geschlossen": []})
    veraendert = False
    preis = daten["preis"]

    for trade in [t for t in hypo["offen"] if t["ticker"] == ticker]:
        ausgeloest = None
        if trade["richtung"] == "long":
            if preis >= trade["ziel"]:
                ausgeloest = "Ziel erreicht"
            elif preis <= trade["stop"]:
                ausgeloest = "Stop erreicht"
        else:
            if preis <= trade["ziel"]:
                ausgeloest = "Ziel erreicht"
            elif preis >= trade["stop"]:
                ausgeloest = "Stop erreicht"

        eroeffnet = datetime.fromisoformat(trade["eroeffnet_am"])
        if ausgeloest is None and (datetime.now(timezone.utc) - eroeffnet).days >= 30:
            ausgeloest = "Zeit abgelaufen"

        if ausgeloest:
            veraenderung_pct = (
                (preis - trade["einstieg"]) / trade["einstieg"] * 100 if trade["richtung"] == "long"
                else (trade["einstieg"] - preis) / trade["einstieg"] * 100
            )
            hypo["geschlossen"].insert(0, {
                **trade, "ausstieg": preis, "ergebnis": ausgeloest,
                "veraenderung_pct": veraenderung_pct,
                "geschlossen_am": datetime.now(timezone.utc).isoformat(),
            })
            hypo["geschlossen"] = hypo["geschlossen"][:50]
            hypo["offen"] = [t for t in hypo["offen"] if t["id"] != trade["id"]]
            veraendert = True

    hat_offene = any(t["ticker"] == ticker for t in hypo["offen"])
    if not hat_offene and daten["kategorie"] in ("Stark bullisch", "Stark bärisch"):
        atr = atr_wert(daten["highs"], daten["lows"], daten["closes"])
        if atr:
            einstieg = daten["preis_signal"]
            richtung = "long" if daten["kategorie"] == "Stark bullisch" else "short"
            stop = einstieg - atr if richtung == "long" else einstieg + atr
            ziel = einstieg + atr * 2 if richtung == "long" else einstieg - atr * 2
            hypo["offen"].append({
                "id": str(uuid.uuid4())[:8], "ticker": ticker, "richtung": richtung,
                "einstieg": einstieg, "stop": stop, "ziel": ziel,
                "eroeffnet_am": datetime.now(timezone.utc).isoformat(),
            })
            veraendert = True

    if veraendert:
        zustand_speichern()


def coin_daten_laden(ticker: str, intervall_label: str):
    coingecko_id = coingecko_id_ermitteln(ticker)
    if not coingecko_id:
        return None
    tage = TIMEFRAME_ZU_TAGE.get(intervall_label, 7)
    df = coingecko_ohlc_holen(coingecko_id, tage)
    if df is None or df.empty or len(df) < 20:
        return None

    closes_chart = df["close"].tolist()
    highs_chart = df["high"].tolist()
    lows_chart = df["low"].tolist()

    bb_mittel_serie, bb_oben_serie, bb_unten_serie = bollinger_baender_serie(closes_chart)
    df["bb_mittel"] = bb_mittel_serie.values
    df["bb_oben"] = bb_oben_serie.values
    df["bb_unten"] = bb_unten_serie.values

    volumen_liste = coingecko_volumen_holen(coingecko_id, tage)

    # Signale NUR aus abgeschlossenen Kerzen berechnen - die letzte Kerze läuft bei
    # CoinGecko evtl. noch, sonst würde sich der Score bei jedem Neuladen "verflackern"
    # (Praxis übernommen aus dem Vergleichs-Tool des Kollegen).
    n_signal = len(closes_chart) - 1 if len(closes_chart) > 21 else len(closes_chart)
    closes = closes_chart[:n_signal]
    highs = highs_chart[:n_signal]
    lows = lows_chart[:n_signal]

    serien = indikator_serien_berechnen(closes, highs, lows)
    letzter_index = len(closes) - 1
    score, kategorie, gruende, trend_stark, adx_wert = score_bei_index(serien, closes, highs, lows, letzter_index)

    fib_level = fibonacci_level_berechnen(highs, lows)
    fib_naechstes = naechstes_fib_level(closes[-1], fib_level) if fib_level else None

    return {
        "df": df,
        "preis": closes_chart[-1],
        "preis_signal": closes[-1],
        "rsi": serien["rsi"].iloc[-1] if pd.notna(serien["rsi"].iloc[-1]) else None,
        "stoch_k": serien["stoch_k"].iloc[-1] if pd.notna(serien["stoch_k"].iloc[-1]) else None,
        "adx": adx_wert,
        "trend_stark": trend_stark,
        "score": score,
        "kategorie": kategorie,
        "gruende": gruende,
        "bb_oben": bb_oben_serie.iloc[-1] if len(bb_oben_serie) else None,
        "bb_unten": bb_unten_serie.iloc[-1] if len(bb_unten_serie) else None,
        "volumen_aktuell": volumen_liste[-1] if volumen_liste else None,
        "volumen_schnitt": pd.Series(volumen_liste).rolling(min(20, max(len(volumen_liste) - 1, 1))).mean().iloc[-1] if volumen_liste else None,
        "closes": closes, "highs": highs, "lows": lows,
        "fib_level": fib_level, "fib_naechstes": fib_naechstes,
        "coingecko_id": coingecko_id,
    }


def candlestick_chart(df: pd.DataFrame, fib_level=None, fib_anzeigen=True, projektion=None, aktueller_preis=None, vorschau=5):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["zeit"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Kurs",
    ))
    fig.add_trace(go.Scatter(x=df["zeit"], y=df["bb_oben"], line=dict(width=1, color="rgba(150,150,255,0.5)"), name="BB oben"))
    fig.add_trace(go.Scatter(x=df["zeit"], y=df["bb_unten"], line=dict(width=1, color="rgba(150,150,255,0.5)"), name="BB unten", fill="tonexty", fillcolor="rgba(150,150,255,0.07)"))
    fig.add_trace(go.Scatter(x=df["zeit"], y=df["bb_mittel"], line=dict(width=1, dash="dot", color="orange"), name="BB Mitte"))

    if fib_anzeigen and fib_level:
        fib_farben = {
            "0.0%": "rgba(180,180,180,0.5)", "23.6%": "rgba(255,200,120,0.6)",
            "38.2%": "rgba(255,160,90,0.6)", "50.0%": "rgba(255,120,120,0.7)",
            "61.8%": "rgba(255,90,90,0.7)", "78.6%": "rgba(255,60,60,0.6)",
            "100.0%": "rgba(180,180,180,0.5)",
        }
        for name, wert in fib_level.items():
            fig.add_hline(
                y=wert, line_dash="dot", line_width=1, line_color=fib_farben.get(name, "gray"),
                annotation_text=f"Fib {name}", annotation_position="right",
                annotation_font_size=10,
            )

    # Projektions-Zone: KEINE Ziel-Linie (das wäre eine Vorhersage), sondern eine
    # Bandbreite aus dem historischen Backtest - beste/schlechteste Entwicklung nach
    # ähnlichen Signalen in der Vergangenheit dieses Coins.
    if projektion and projektion.get("grund") == "ok" and aktueller_preis and len(df) >= 2:
        letzter_zeitpunkt = df["zeit"].iloc[-1]
        delta = df["zeit"].iloc[-1] - df["zeit"].iloc[-2]
        projektions_zeitpunkt = letzter_zeitpunkt + delta * vorschau

        oben = aktueller_preis * (1 + projektion["bester"] / 100)
        unten = aktueller_preis * (1 + projektion["schlechtester"] / 100)
        mitte = aktueller_preis * (1 + projektion["durchschnitt"] / 100)

        fig.add_shape(
            type="rect", x0=letzter_zeitpunkt, x1=projektions_zeitpunkt,
            y0=min(oben, unten), y1=max(oben, unten),
            fillcolor="rgba(167,139,250,0.15)", line_width=0, layer="below",
        )
        fig.add_shape(
            type="line", x0=letzter_zeitpunkt, x1=projektions_zeitpunkt, y0=mitte, y1=mitte,
            line=dict(color="rgba(167,139,250,0.9)", dash="dot", width=1.5),
        )
        fig.add_annotation(
            x=projektions_zeitpunkt, y=mitte, text=f"Ø {projektion['durchschnitt']:+.1f}%",
            showarrow=False, font=dict(size=10, color="rgba(216,180,254,1)"), xanchor="left",
        )

    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False, template="plotly_dark", showlegend=False,
    )
    return fig


# --- 🖥️ OBERFLÄCHE ---
st.title("⚡ Krypto Monitoring Terminal (Live-Daten, CoinGecko)")
st.caption(
    "Kurse & Kerzen: CoinGecko · Angst-&-Gier-Index: alternative.me · "
    "Nur Beobachtung – **keine automatische Order-Ausführung, keine Anlageberatung.** "
    "Signale sind statistische Tendenzen aus der Vergangenheit, keine Garantie."
)

tab_beobachtung, tab_portfolio, tab_alarme, tab_sitzungen, tab_bewegungen = st.tabs(
    ["📊 Beobachtung", "💰 Portfolio", "🔔 Alarme", "🌍 Handelssitzungen", "🔥 Top Bewegungen"]
)

# ============================== TAB 1: BEOBACHTUNG ==============================
with tab_beobachtung:
    st.subheader("➕ Neuen Coin beobachten")
    c_eingabe, c_button = st.columns(2)
    neuer_ticker = c_eingabe.text_input(
        "Krypto-Kürzel eingeben:", placeholder="Z. B. XRP, ADA, LINK, PHA", key="add_input"
    ).upper().strip()

    if c_button.button("🪙 Coin hinzufügen", use_container_width=True, key="add_btn"):
        watchlist = st.session_state.zustand["watchlist"]
        if neuer_ticker in watchlist:
            st.warning(f"{neuer_ticker} wird bereits beobachtet.")
        elif coingecko_id_ermitteln(neuer_ticker):
            watchlist.append(neuer_ticker)
            zustand_speichern()
            st.success(f"{neuer_ticker} hinzugefügt.")
            time.sleep(0.3)
            st.rerun()
        else:
            st.error(f'Kein Coin mit Kürzel "{neuer_ticker}" auf CoinGecko gefunden.')

    st.markdown("---")
    st.subheader("🧠 Krypto-Angst-&-Gier-Index")
    fg_wert, fg_klasse = fear_greed_index_holen()
    if fg_wert is None:
        st.info("Angst-&-Gier-Index aktuell nicht abrufbar.")
    else:
        st.progress(fg_wert / 100)
        st.markdown(f"**Index-Wert:** `{fg_wert}/100` | **Einstufung:** **{fg_klasse}**")

    st.markdown("---")
    if st.button("🔄 Daten neu laden", type="primary", use_container_width=True, key="scan_btn"):
        coingecko_ohlc_holen.clear()
        coingecko_volumen_holen.clear()
        aktuellen_preis_holen.clear()
        fear_greed_index_holen.clear()
        backtest_kategorie.clear()
        st.session_state.zustand = zustand_laden()
        st.rerun()

    st.markdown("---")
    st.subheader("📊 Live-Kerzen, Signal-Score & Indikatoren")

    watchlist = st.session_state.zustand["watchlist"]
    optionen = list(TIMEFRAME_ZU_TAGE.keys())

    for ticker in list(watchlist):
        aktueller_zeitraum = st.session_state.get(f"select_{ticker}", optionen[1])
        with st.spinner(f"Lade {ticker}…"):
            daten = coin_daten_laden(ticker, aktueller_zeitraum)

        st.markdown("---")
        if daten is None:
            st.error(f"**{ticker}**: Keine Daten verfügbar (API nicht erreichbar, Rate-Limit, unbekanntes Kürzel oder zu wenig Historie).")
            continue

        hypo_trades_aktualisieren(ticker, daten)

        kategorie = daten["kategorie"]
        score = daten["score"]
        if kategorie.startswith("Stark bullisch") or kategorie.startswith("Leicht bullisch"):
            ampel, ampel_text = "🟢", "Bullische Signale"
        elif kategorie.startswith("Stark bärisch") or kategorie.startswith("Leicht bärisch"):
            ampel, ampel_text = "🔴", "Bärische Signale"
        else:
            ampel, ampel_text = "🟡", "Neutral"

        c_ampel, c_info = st.columns([1, 5])
        with c_ampel:
            st.markdown(f"## {ampel}")
        with c_info:
            st.markdown(f"**{ticker}** — $ {daten['preis']:,.2f} — **{ampel_text}** ({score:+d}/6)")
            if daten["gruende"]:
                st.caption(" · ".join(daten["gruende"][:3]))
            else:
                st.caption("Keine ausschlaggebenden Indikator-Signale")

        with st.expander(f"📈 Details zu {ticker} (Chart, alle Indikatoren, Backtest)", expanded=False):
            neues_intervall = st.selectbox(
                "Zeitraum:", options=optionen, index=optionen.index(aktueller_zeitraum), key=f"select_{ticker}"
            )
            fib_anzeigen = st.checkbox("📐 Fibonacci-Level anzeigen", value=True, key=f"fib_toggle_{ticker}")

            with st.spinner("Werte Historie aus…"):
                backtest_ergebnis = backtest_kategorie(
                    tuple(daten["closes"]), tuple(daten["highs"]), tuple(daten["lows"]),
                    daten["kategorie"], vorschau=5,
                )

            st.plotly_chart(
                candlestick_chart(
                    daten["df"], fib_level=daten["fib_level"], fib_anzeigen=fib_anzeigen,
                    projektion=backtest_ergebnis, aktueller_preis=daten["preis"], vorschau=5,
                ),
                use_container_width=True,
            )
            if backtest_ergebnis.get("grund") == "ok":
                st.caption(
                    "🟣 Violette Zone im Chart: Spanne aus bester/schlechtester historischer Entwicklung "
                    "nach diesem Signal – keine Ziel-Vorhersage, sondern eine Bandbreite aus der Vergangenheit."
                )

            c1, c2, c3, c4 = st.columns(4)

            with c1:
                st.write("🎯 Signal-Score:")
                anzeige = f"{kategorie} ({score:+d}/6)"
                if ampel == "🟢":
                    st.success(f"🟢 {anzeige}")
                elif ampel == "🔴":
                    st.error(f"🔴 {anzeige}")
                else:
                    st.info(f"🟡 {anzeige}")
                for grund in daten["gruende"]:
                    st.caption(f"• {grund}")

            with c2:
                st.write("📐 Weitere Indikatoren:")
                st.write(f"RSI (14): **{daten['rsi']:.1f}**" if daten["rsi"] is not None else "RSI: —")
                st.write(f"Stochastik: **{daten['stoch_k']:.1f}**" if daten["stoch_k"] is not None else "Stochastik: —")
                if daten["adx"] is not None:
                    trend_text = "starker Trend" if daten["trend_stark"] else "seitwärts/schwach"
                    st.write(f"ADX: **{daten['adx']:.1f}** ({trend_text})")
                    if not daten["trend_stark"]:
                        st.caption("⚠️ Schwacher Trend – Signale hier tendenziell weniger verlässlich")
                else:
                    st.write("ADX: —")

            with c3:
                st.write("📏 Bollinger Bänder:")
                if daten["bb_oben"] is not None:
                    st.write(f"Oben: **$ {daten['bb_oben']:,.2f}**")
                    st.write(f"Unten: **$ {daten['bb_unten']:,.2f}**")
                else:
                    st.write("Noch zu wenig Historie.")
                if daten["fib_naechstes"]:
                    fib_name, fib_wert, fib_abstand = daten["fib_naechstes"]
                    st.write(f"Nächstes Fib-Level: **{fib_name}** (${fib_wert:,.2f})")
                    st.caption(f"Abstand: {fib_abstand:.2f}% – reine Referenzzone, kein Signal")

            with c4:
                st.write("📦 Volumen (24h, ca.):")
                if daten["volumen_aktuell"] is not None:
                    st.write(f"Aktuell: **$ {daten['volumen_aktuell']:,.0f}**")
                    if daten["volumen_schnitt"]:
                        verhaeltnis = daten["volumen_aktuell"] / daten["volumen_schnitt"]
                        st.write(f"Ø: **$ {daten['volumen_schnitt']:,.0f}**")
                        st.write(f"{verhaeltnis:.1f}× Durchschnitt")
                else:
                    st.write("Nicht verfügbar.")

            with st.expander("📊 Historische Trefferquote für dieses Signal (Backtest)"):
                ergebnis = backtest_ergebnis
                if ergebnis["grund"] == "zu_kurzer_zeitraum":
                    st.info(
                        "Der gewählte Zeitraum lädt zu wenige Kerzen für einen Backtest "
                        "(braucht mindestens ca. 55). Wähle oben \"1 Monat\" oder \"3 Monate\", "
                        "um historische Statistik zu sehen."
                    )
                elif ergebnis["grund"] == "zu_wenig_faelle":
                    st.info(
                        f"'{daten['kategorie']}' trat in der geladenen Historie nur "
                        f"{ergebnis['anzahl']}× auf – zu wenig für eine verlässliche Aussage."
                    )
                else:
                    st.markdown(
                        f"In der geladenen Historie trat **'{daten['kategorie']}'** bisher "
                        f"**{ergebnis['anzahl']}×** auf. 5 Kerzen später:"
                    )
                    st.write(f"📈 Kurs höher: **{ergebnis['prozent_positiv']:.0f}%** der Fälle")
                    st.write(f"Ø Veränderung: **{ergebnis['durchschnitt']:+.2f}%**")
                    st.write(f"Beste / schlechteste Entwicklung: **{ergebnis['bester']:+.2f}%** / **{ergebnis['schlechtester']:+.2f}%**")
                    st.caption("Reine Vergangenheitsstatistik dieses Coins – keine Vorhersage für das nächste Mal.")

    st.markdown("---")
    with st.expander("📈 Vorwärts-Tracking: Wie hätten die Signale seitdem abgeschnitten?", expanded=False):
        st.caption(
            "Seit du diese App nutzt, wird automatisch mitgeschrieben: Zeigt ein Coin 'Stark bullisch/bärisch', "
            "wird notiert, was passiert wäre, wenn du dem gefolgt wärst (Ziel = Einstieg ± 2×ATR, "
            "Stop = Einstieg ∓ 1×ATR, Zeit-Ablauf nach 30 Tagen). "
            "Läuft nur, während die App offen ist – anders als die Telegram-Alarme kein 24/7-Hintergrundprozess."
        )
        hypo = st.session_state.zustand.get("hypo_trades", {"offen": [], "geschlossen": []})
        offen_liste = hypo.get("offen", [])
        geschlossen_liste = hypo.get("geschlossen", [])

        ziel_treffer = sum(1 for t in geschlossen_liste if t["ergebnis"] == "Ziel erreicht")
        stop_treffer = sum(1 for t in geschlossen_liste if t["ergebnis"] == "Stop erreicht")
        zeit_treffer = sum(1 for t in geschlossen_liste if t["ergebnis"] == "Zeit abgelaufen")
        avg_veraenderung = (
            sum(t["veraenderung_pct"] for t in geschlossen_liste) / len(geschlossen_liste)
            if geschlossen_liste else 0
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Offen", len(offen_liste))
        m2.metric("Ziel / Stop / Zeit", f"{ziel_treffer}/{stop_treffer}/{zeit_treffer}")
        m3.metric("Geschlossen gesamt", len(geschlossen_liste))
        m4.metric("Ø Veränderung", f"{avg_veraenderung:+.2f}%")

        if offen_liste:
            st.write("**Offene hypothetische Positionen:**")
            for t in offen_liste:
                st.write(
                    f"{t['ticker']} — **{t['richtung'].upper()}** @ $ {t['einstieg']:,.2f} "
                    f"(Ziel $ {t['ziel']:,.2f} / Stop $ {t['stop']:,.2f})"
                )
        if geschlossen_liste:
            st.write("**Letzte geschlossene:**")
            for t in geschlossen_liste[:10]:
                zeichen = "🟢" if t["veraenderung_pct"] > 0 else "🔴"
                st.write(
                    f"{zeichen} {t['ticker']} {t['richtung'].upper()}: {t['ergebnis']} "
                    f"({t['veraenderung_pct']:+.2f}%)"
                )
        if not offen_liste and not geschlossen_liste:
            st.info("Noch keine hypothetischen Positionen – entsteht automatisch beim nächsten starken Signal.")

    if st.button("🗑️ Watchlist zurücksetzen (Nur Core-Coins)", key="reset_btn"):
        st.session_state.zustand["watchlist"] = ["BTC", "ETH", "SOL", "PAXG"]
        zustand_speichern()
        st.rerun()

# ============================== TAB 2: PORTFOLIO ==============================
with tab_portfolio:
    st.subheader("💰 Portfolio-Tracking")
    st.caption("Reine Nachverfolgung deiner eigenen Angaben – keine Verbindung zu einem echten Börsenkonto.")

    with st.expander("➕ Neue Position hinzufügen"):
        p_ticker = st.text_input("Coin-Kürzel:", key="portfolio_ticker").upper().strip()
        p_kaufpreis = st.number_input("Kaufpreis pro Coin ($):", min_value=0.0, value=0.0, format="%.4f", key="portfolio_preis")
        p_menge = st.number_input("Menge:", min_value=0.0, value=0.0, format="%.6f", key="portfolio_menge")
        if st.button("Position speichern", key="portfolio_add_btn"):
            if p_ticker and p_kaufpreis > 0 and p_menge > 0:
                st.session_state.zustand["portfolio"].append({
                    "id": str(uuid.uuid4())[:8], "ticker": p_ticker,
                    "kaufpreis": p_kaufpreis, "menge": p_menge,
                })
                zustand_speichern()
                st.success("Position gespeichert.")
                st.rerun()
            else:
                st.warning("Bitte Kürzel, Kaufpreis und Menge angeben.")

    portfolio = st.session_state.zustand.get("portfolio", [])
    if portfolio:
        zeilen = []
        gesamt_wert = 0.0
        gesamt_einsatz = 0.0
        for position in portfolio:
            coingecko_id = coingecko_id_ermitteln(position["ticker"])
            aktueller_preis = aktuellen_preis_holen(coingecko_id) if coingecko_id else None
            wert = (aktueller_preis if aktueller_preis is not None else position["kaufpreis"]) * position["menge"]
            einsatz = position["kaufpreis"] * position["menge"]
            gesamt_wert += wert
            gesamt_einsatz += einsatz
            zeilen.append({
                "Coin": position["ticker"],
                "Menge": position["menge"],
                "Kaufpreis ($)": position["kaufpreis"],
                "Akt. Preis ($)": aktueller_preis,
                "Wert ($)": round(wert, 2),
                "G/V ($)": round(wert - einsatz, 2),
                "G/V (%)": round((wert - einsatz) / einsatz * 100, 1) if einsatz else 0,
            })
        st.dataframe(pd.DataFrame(zeilen), use_container_width=True, hide_index=True)

        gesamt_gv = gesamt_wert - gesamt_einsatz
        gesamt_gv_prozent = (gesamt_gv / gesamt_einsatz * 100) if gesamt_einsatz else 0
        st.markdown(f"**Gesamtwert:** $ {gesamt_wert:,.2f} &nbsp;|&nbsp; **Gesamt G/V:** $ {gesamt_gv:,.2f} ({gesamt_gv_prozent:.1f}%)")

        loeschen_optionen = ["–"] + [f"{p['id']}: {p['ticker']} ({p['menge']})" for p in portfolio]
        auswahl = st.selectbox("Position entfernen:", options=loeschen_optionen, key="portfolio_remove_select")
        if st.button("Ausgewählte Position löschen", key="portfolio_remove_btn") and auswahl != "–":
            loeschen_id = auswahl.split(":")[0]
            st.session_state.zustand["portfolio"] = [p for p in portfolio if p["id"] != loeschen_id]
            zustand_speichern()
            st.rerun()
    else:
        st.info("Noch keine Positionen im Portfolio.")

# ============================== TAB 3: ALARME ==============================
with tab_alarme:
    st.subheader("🔔 Preis-Alarme")
    st.caption(
        "Läuft unabhängig über GitHub Actions – funktioniert auch, wenn diese Seite geschlossen ist. "
        "Prüfung erfolgt alle 15 Minuten, Benachrichtigung per Telegram."
    )

    with st.expander("➕ Neuen Alarm hinzufügen"):
        a_ticker = st.text_input("Coin-Kürzel:", key="alert_ticker").upper().strip()
        a_typ_anzeige = st.selectbox("Bedingung:", options=[
            "Preis über Schwelle", "Preis unter Schwelle",
            "RSI über Schwelle (überkauft)", "RSI unter Schwelle (überverkauft)",
        ], key="alert_typ")
        a_schwelle = st.number_input("Schwellenwert:", value=0.0, key="alert_schwelle")
        if st.button("Alarm speichern", key="alert_add_btn"):
            typ_map = {
                "Preis über Schwelle": "preis_ueber",
                "Preis unter Schwelle": "preis_unter",
                "RSI über Schwelle (überkauft)": "rsi_ueber",
                "RSI unter Schwelle (überverkauft)": "rsi_unter",
            }
            if a_ticker and a_schwelle != 0.0:
                st.session_state.zustand["alerts"].append({
                    "id": str(uuid.uuid4())[:8], "ticker": a_ticker,
                    "typ": typ_map[a_typ_anzeige], "schwelle": a_schwelle, "ausgeloest": False,
                })
                zustand_speichern()
                st.success("Alarm gespeichert – wird spätestens in 15 Minuten aktiv überwacht.")
                st.rerun()
            else:
                st.warning("Bitte Kürzel und einen Schwellenwert ungleich 0 angeben.")

    alerts = st.session_state.zustand.get("alerts", [])
    if alerts:
        for alarm in alerts:
            status = "✅ Ausgelöst" if alarm.get("ausgeloest") else "⏳ Aktiv"
            st.write(f"{status} — **{alarm['ticker']}**: {ALARM_TYP_ANZEIGE.get(alarm['typ'], alarm['typ'])} {alarm['schwelle']}")

        loeschen_optionen = ["–"] + [f"{a['id']}: {a['ticker']}" for a in alerts]
        auswahl = st.selectbox("Alarm löschen:", options=loeschen_optionen, key="alert_remove_select")
        if st.button("Ausgewählten Alarm löschen", key="alert_remove_btn") and auswahl != "–":
            loeschen_id = auswahl.split(":")[0]
            st.session_state.zustand["alerts"] = [a for a in alerts if a["id"] != loeschen_id]
            zustand_speichern()
            st.rerun()
    else:
        st.info("Noch keine Alarme eingerichtet.")

    st.markdown("---")
    st.markdown(
        """
        **⚠️ Wichtig:** Alarme sind reine Schwellenwert-Benachrichtigungen, keine Kauf-/Verkaufsempfehlung.
        Ein ausgelöster Alarm deaktiviert sich automatisch (kein Dauer-Spam) – zum Neustart einfach löschen
        und neu anlegen.
        """
    )

# ============================== TAB 4: HANDELSSITZUNGEN ==============================
with tab_sitzungen:
    st.subheader("🌍 Handelssitzungen – Live-Status")
    st.caption(
        "Sitzungszeiten beeinflussen zuverlässig die **Volatilität** (wie stark sich der Kurs bewegt) – "
        "aber NICHT die Richtung (ob er steigt oder fällt). Das hier ist eine Info-Übersicht plus "
        "historische Statistik, **keine Vorhersage und keine Handelsempfehlung.**"
    )

    sitzungen, jetzt_utc = sitzungs_status()
    st.markdown(f"Aktuelle Uhrzeit (UTC): **{jetzt_utc.strftime('%H:%M')}** | Deine Zeit (Wien): **{jetzt_utc.astimezone(ZoneInfo(LOKALE_ZEITZONE)).strftime('%H:%M')}**")

    for s in sitzungen:
        start_lokal = utc_stunde_zu_lokal(s["start_utc"])
        ende_lokal = utc_stunde_zu_lokal(s["ende_utc"])
        status = "🟢 Geöffnet" if s["offen"] else "⚪ Geschlossen"
        st.write(f"**{s['name']}**: {status} — öffnet {start_lokal} Uhr, schließt {ende_lokal} Uhr (deine Zeit)")

    st.caption(
        "Zeiten sind gängige, häufig verwendete Richtwerte für Handelssitzungen – keine offiziell "
        "regulierten Öffnungszeiten. Krypto und Gold-Token wie PAXG handeln durchgehend (24/7)."
    )

    st.markdown("---")
    st.subheader("📊 24-Stunden-Analyse: Historische Ø-Kursbewegung je Uhrzeit")
    st.caption(
        "Grün = historisch eher long-lastig (Kurs stieg im Schnitt), Rot = eher short-lastig "
        "(Kurs fiel im Schnitt). Das ist eine Beschreibung der Vergangenheit, **keine Vorhersage "
        "und keine Handelsempfehlung** für heute."
    )

    watchlist_optionen = st.session_state.zustand.get("watchlist", ["BTC", "ETH", "SOL", "PAXG"])
    if watchlist_optionen:
        index_gold = watchlist_optionen.index("PAXG") if "PAXG" in watchlist_optionen else 0
        coin_auswahl = st.selectbox("Coin auswählen:", options=watchlist_optionen, index=index_gold, key="sitzung_coin")
        vorschau_stunden = st.slider(
            "Kursentwicklung wie viele Stunden später betrachten?",
            min_value=1, max_value=6, value=2, key="sitzung_vorschau",
        )

        coingecko_id = coingecko_id_ermitteln(coin_auswahl)
        if coingecko_id:
            with st.spinner("Werte Historie aus…"):
                punkte = coingecko_preise_mit_zeit_holen(coingecko_id, tage=90)

            analyse = stunden_analyse(punkte, vorschau_stunden)
            if analyse["grund"] == "keine_daten":
                st.warning(
                    "Keine Kursdaten von CoinGecko erhalten – meist ein kurzes Rate-Limit "
                    "(z. B. nach vielen Anfragen im Beobachtung-Tab). Kurz warten und "
                    "\"🔄 Daten neu laden\" oben klicken, oder Seite neu laden."
                )
            elif analyse["grund"] == "zu_wenig_pro_stunde":
                st.info("Zu wenig historische Vorkommen pro Stunde für eine verlässliche Aussage.")
            else:
                ergebnis = analyse["stunden"]
                st.plotly_chart(stunden_chart(ergebnis), use_container_width=True)
                bullischste = max(ergebnis.items(), key=lambda kv: kv[1]["durchschnitt"])
                baerischste = min(ergebnis.items(), key=lambda kv: kv[1]["durchschnitt"])
                c1, c2 = st.columns(2)
                c1.metric(
                    f"Historisch stärkste Stunde ({utc_stunde_zu_lokal(bullischste[0])} Uhr)",
                    f"{bullischste[1]['durchschnitt']:+.2f}%",
                )
                c2.metric(
                    f"Historisch schwächste Stunde ({utc_stunde_zu_lokal(baerischste[0])} Uhr)",
                    f"{baerischste[1]['durchschnitt']:+.2f}%",
                )
                st.caption(f"Basis: letzte 90 Tage, {coin_auswahl}. Werte je Stunde beruhen auf mindestens 5 historischen Vorkommen.")
        else:
            st.warning("Coin konnte nicht aufgelöst werden.")
    else:
        st.info("Noch keine Coins auf der Watchlist (Reiter 📊 Beobachtung).")

    st.markdown("---")
    st.subheader("📈 Aktien – Live-Snapshot")
    if not FINNHUB_API_KEY:
        st.info("Finnhub-Key noch nicht in den Secrets eingetragen (FINNHUB_API_KEY) – dieser Bereich bleibt bis dahin leer.")
    else:
        st.caption(
            "Finnhub bietet auf dem kostenlosen Plan keine historischen Kerzen für Aktien – deshalb nur "
            "der aktuelle Live-Stand, keine Indikatoren, kein Signal-Score wie bei Krypto/Gold."
        )
        for symbol in AKTIEN_TICKER:
            quote = finnhub_quote_holen(symbol)
            snapshot = aktien_snapshot_auswerten(quote)
            if snapshot is None:
                st.warning(f"{symbol}: Keine Daten verfügbar (Rate-Limit oder API nicht erreichbar).")
                continue
            zeichen = "🟢" if (snapshot["veraenderung_tag"] or 0) >= 0 else "🔴"
            tag_text = f"{snapshot['veraenderung_tag']:+.2f}%" if snapshot["veraenderung_tag"] is not None else "—"
            open_text = f"{snapshot['veraenderung_seit_open']:+.2f}%" if snapshot["veraenderung_seit_open"] is not None else "—"
            st.write(
                f"{zeichen} **{symbol}**: $ {snapshot['preis']:,.2f} — "
                f"seit Vortagesschluss **{tag_text}** — seit Markteröffnung heute **{open_text}**"
            )

# ============================== TAB 5: TOP BEWEGUNGEN ==============================
with tab_bewegungen:
    st.subheader("🔥 Größte Marktbewegungen")
    st.caption(
        "Scannt die Top 500 Coins nach Marktkapitalisierung auf CoinGecko nach den stärksten "
        "Ausschlägen in beide Richtungen. Reine Kursbewegung – **keine Kauf-/Verkaufsempfehlung.**"
    )

    c1, c2, c3 = st.columns(3)
    zeitraum_anzeige = c1.selectbox("Zeitraum:", options=["1 Stunde", "24 Stunden"], index=1, key="bewegung_zeitraum")
    schwelle = c2.number_input("Mindest-Veränderung (%):", min_value=1.0, value=10.0, step=5.0, key="bewegung_schwelle")
    anzahl = c3.slider("Wie viele anzeigen?", min_value=5, max_value=10, value=10, key="bewegung_anzahl")

    if st.button("🔄 Markt neu scannen", key="bewegung_scan_btn"):
        coingecko_markt_uebersicht.clear()
        st.rerun()

    with st.spinner("Scanne Markt (Top 500 Coins)…"):
        marktdaten = coingecko_markt_uebersicht(seiten=2)

    if not marktdaten:
        st.error("Marktdaten aktuell nicht abrufbar (API nicht erreichbar oder Rate-Limit).")
    else:
        zeitraum_code = "1h" if zeitraum_anzeige == "1 Stunde" else "24h"
        treffer = top_bewegungen(marktdaten, zeitraum_code, schwelle, anzahl)

        if not treffer:
            st.info(
                f"Aktuell kein Coin unter den Top 500 mit {schwelle:.0f}%+ Veränderung in {zeitraum_anzeige}. "
                "Das ist normal – so starke Bewegungen sind selten. Schwellenwert oben ggf. senken."
            )
        else:
            st.caption(f"{len(treffer)} Treffer, sortiert nach Stärke der Bewegung ({zeitraum_anzeige}):")
            for coin in treffer:
                richtung = "🟢" if coin["veraenderung"] > 0 else "🔴"
                st.write(
                    f"{richtung} **{coin['symbol']}** ({coin['name']}) — "
                    f"$ {coin['preis']:,.4f} — **{coin['veraenderung']:+.1f}%** ({zeitraum_anzeige})"
                )
