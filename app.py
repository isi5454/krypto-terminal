import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import uuid

st.set_page_config(page_title="Krypto Monitoring Terminal", page_icon="⚡", layout="wide")

# --- 🔑 SECRETS (in Streamlit Cloud unter "Secrets" eintragen, NICHT im Code) ---
BIN_ID = st.secrets["JSONBIN_BIN_ID"]
API_KEY = st.secrets["JSONBIN_API_KEY"]

BINANCE_BASIS = "https://api.binance.com/api/v3"
JSONBIN_BASIS = "https://api.jsonbin.io/v3/b"

TIMEFRAME_ZU_INTERVALL = {
    "⏱️ 5 Min": "5m",
    "⏱️ 15 Min": "15m",
    "🕐 1 Stunde": "1h",
    "🛑 4 Stunden": "4h",
    "📅 1 Tag": "1d",
}

ALARM_TYP_ANZEIGE = {
    "preis_ueber": "Preis über",
    "preis_unter": "Preis unter",
    "rsi_ueber": "RSI über",
    "rsi_unter": "RSI unter",
}


# --- 💾 PERSISTENTER SPEICHER (JSONBin – überlebt Neustarts & Neuladen) ---

def zustand_laden():
    try:
        r = requests.get(f"{JSONBIN_BASIS}/{BIN_ID}/latest", headers={"X-Master-Key": API_KEY}, timeout=10)
        r.raise_for_status()
        record = r.json().get("record", {})
        record.setdefault("watchlist", ["BTC", "ETH", "SOL"])
        record.setdefault("portfolio", [])
        record.setdefault("alerts", [])
        return record
    except requests.RequestException:
        st.warning("Persistenter Speicher aktuell nicht erreichbar – Änderungen werden evtl. nicht gespeichert.")
        return {"watchlist": ["BTC", "ETH", "SOL"], "portfolio": [], "alerts": []}


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


# --- 🌐 BINANCE MARKTDATEN (öffentlich, kein API-Key nötig) ---

@st.cache_data(ttl=3600, show_spinner=False)
def binance_symbol_gueltig(symbol: str) -> bool:
    try:
        r = requests.get(f"{BINANCE_BASIS}/exchangeInfo", params={"symbol": symbol}, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def binance_klines_holen(symbol: str, intervall: str, limit: int = 150):
    try:
        r = requests.get(
            f"{BINANCE_BASIS}/klines",
            params={"symbol": symbol, "interval": intervall, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        rohdaten = r.json()
    except requests.RequestException:
        return None
    if not rohdaten:
        return None
    df = pd.DataFrame(rohdaten, columns=[
        "open_zeit", "open", "high", "low", "close", "volumen",
        "close_zeit", "quote_volumen", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for spalte in ["open", "high", "low", "close", "volumen"]:
        df[spalte] = df[spalte].astype(float)
    df["zeit"] = pd.to_datetime(df["open_zeit"], unit="ms")
    return df


@st.cache_data(ttl=30, show_spinner=False)
def aktuellen_preis_holen(symbol: str):
    try:
        r = requests.get(f"{BINANCE_BASIS}/ticker/price", params={"symbol": symbol}, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
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


# --- 📐 INDIKATOREN ---

def sma(werte, periode):
    s = pd.Series(werte)
    if len(s) < periode:
        return None
    return float(s.rolling(periode).mean().iloc[-1])


def rsi(werte, periode=14):
    s = pd.Series(werte)
    if len(s) <= periode:
        return None
    delta = s.diff()
    gewinn = delta.clip(lower=0).rolling(periode).mean()
    verlust = (-delta.clip(upper=0)).rolling(periode).mean()
    rs = gewinn / verlust.replace(0, 1e-9)
    return float(100 - (100 / (1 + rs)).iloc[-1])


def macd(werte, fast=12, slow=26, signal=9):
    s = pd.Series(werte)
    if len(s) < slow + signal:
        return None, None
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_linie = ema_fast - ema_slow
    signal_linie = macd_linie.ewm(span=signal, adjust=False).mean()
    return float(macd_linie.iloc[-1]), float(signal_linie.iloc[-1])


def atr_prozent(highs, lows, closes, periode=14):
    if len(closes) < periode + 1:
        return 0.0
    df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(periode).mean().iloc[-1]
    letzter = closes[-1]
    return float(atr / letzter * 100) if letzter else 0.0


def bollinger_baender_serie(werte, periode=20, anzahl_std=2):
    s = pd.Series(werte)
    mittel = s.rolling(periode).mean()
    std = s.rolling(periode).std()
    return mittel, mittel + anzahl_std * std, mittel - anzahl_std * std


def konstellation_klassifizieren(closes):
    if len(closes) < 30:
        return "Neutral (zu wenig Historie)"
    letzter = closes[-1]
    rsi_wert = rsi(closes)
    macd_linie, signal_linie = macd(closes)
    trend = sma(closes, min(50, len(closes) - 1))

    bullisch = (rsi_wert is not None and rsi_wert < 32) or (
        macd_linie is not None and signal_linie is not None and macd_linie > signal_linie
    )
    baerisch = (rsi_wert is not None and rsi_wert > 70) or (
        macd_linie is not None and signal_linie is not None and macd_linie < signal_linie
    )
    trend_auf = trend is not None and letzter > trend

    if bullisch and not baerisch:
        return "Bullisch" + (" + Preis über Trend-SMA" if trend_auf else " (aber Preis unter Trend-SMA)")
    if baerisch and not bullisch:
        return "Bärisch" + (" (Preis unter Trend-SMA)" if not trend_auf else " (trotz Preis über Trend-SMA)")
    return "Gemischt / kein klares Signal"


def coin_daten_laden(ticker: str, intervall_label: str):
    symbol = f"{ticker}USDT"
    intervall = TIMEFRAME_ZU_INTERVALL.get(intervall_label, "15m")
    df = binance_klines_holen(symbol, intervall)
    if df is None or df.empty:
        return None

    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    volumen = df["volumen"].tolist()

    bb_mittel_serie, bb_oben_serie, bb_unten_serie = bollinger_baender_serie(closes)
    df["bb_mittel"] = bb_mittel_serie
    df["bb_oben"] = bb_oben_serie
    df["bb_unten"] = bb_unten_serie

    return {
        "df": df,
        "preis": closes[-1],
        "rsi": rsi(closes),
        "trend_sma": sma(closes, min(50, len(closes) - 1)),
        "atr_prozent": atr_prozent(highs, lows, closes),
        "konstellation": konstellation_klassifizieren(closes),
        "bb_oben": bb_oben_serie.iloc[-1] if len(bb_oben_serie) else None,
        "bb_unten": bb_unten_serie.iloc[-1] if len(bb_unten_serie) else None,
        "volumen_aktuell": volumen[-1],
        "volumen_schnitt": sma(volumen, min(20, len(volumen) - 1)),
    }


def candlestick_chart(df: pd.DataFrame):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.04)

    fig.add_trace(go.Candlestick(
        x=df["zeit"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Kurs",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["zeit"], y=df["bb_oben"], line=dict(width=1, color="rgba(150,150,255,0.5)"), name="BB oben"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["zeit"], y=df["bb_unten"], line=dict(width=1, color="rgba(150,150,255,0.5)"), name="BB unten", fill="tonexty", fillcolor="rgba(150,150,255,0.07)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["zeit"], y=df["bb_mittel"], line=dict(width=1, dash="dot", color="orange"), name="BB Mitte"), row=1, col=1)

    farben = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(x=df["zeit"], y=df["volumen"], marker_color=farben, name="Volumen"), row=2, col=1)

    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False, template="plotly_dark", showlegend=False,
    )
    return fig


# --- 🖥️ OBERFLÄCHE ---
st.title("⚡ Krypto Monitoring Terminal (Live-Daten, Binance)")
st.caption(
    "Kurse & Kerzen: Binance Public API · Angst-&-Gier-Index: alternative.me · "
    "Nur Beobachtung – **keine automatische Order-Ausführung, keine Anlageberatung.**"
)

tab_beobachtung, tab_portfolio, tab_alarme = st.tabs(["📊 Beobachtung", "💰 Portfolio", "🔔 Alarme"])

# ============================== TAB 1: BEOBACHTUNG ==============================
with tab_beobachtung:
    st.subheader("➕ Neuen Coin beobachten")
    c_eingabe, c_button = st.columns(2)
    neuer_ticker = c_eingabe.text_input(
        "Krypto-Kürzel eingeben:", placeholder="Z. B. XRP, ADA, LINK", key="add_input"
    ).upper().strip()

    if c_button.button("🪙 Coin hinzufügen", use_container_width=True, key="add_btn"):
        watchlist = st.session_state.zustand["watchlist"]
        if neuer_ticker in watchlist:
            st.warning(f"{neuer_ticker} wird bereits beobachtet.")
        elif binance_symbol_gueltig(f"{neuer_ticker}USDT"):
            watchlist.append(neuer_ticker)
            zustand_speichern()
            st.success(f"{neuer_ticker} hinzugefügt.")
            time.sleep(0.3)
            st.rerun()
        else:
            st.error(f'Kein Handelspaar "{neuer_ticker}USDT" auf Binance gefunden.')

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
        binance_klines_holen.clear()
        aktuellen_preis_holen.clear()
        fear_greed_index_holen.clear()
        st.session_state.zustand = zustand_laden()
        st.rerun()

    st.markdown("---")
    st.subheader("📊 Live-Kerzen, Bollinger Bänder & Volumen")

    watchlist = st.session_state.zustand["watchlist"]
    for ticker in list(watchlist):
        with st.expander(f"**{ticker} / USDT**", expanded=True):
            optionen = list(TIMEFRAME_ZU_INTERVALL.keys())
            neues_intervall = st.selectbox("Zeitraum:", options=optionen, index=1, key=f"select_{ticker}")

            with st.spinner(f"Lade Live-Daten für {ticker}…"):
                daten = coin_daten_laden(ticker, neues_intervall)

            if daten is None:
                st.error("Keine Daten verfügbar (API nicht erreichbar, Rate-Limit oder ungültiges Paar).")
                continue

            st.markdown(f"Kurs: **$ {daten['preis']:,.4f}**")
            st.plotly_chart(candlestick_chart(daten["df"]), use_container_width=True)

            c_links, c_mitte, c_rechts = st.columns(3)
            with c_links:
                st.write("📐 Indikatoren:")
                st.write(f"RSI (14): **{daten['rsi']:.1f}**" if daten["rsi"] is not None else "RSI: —")
                st.write(f"Volatilität (ATR): **{daten['atr_prozent']:.2f}% / Kerze**")
                label = daten["konstellation"]
                if label.startswith("Bullisch"):
                    st.success(f"🟢 {label}")
                elif label.startswith("Bärisch"):
                    st.error(f"🔴 {label}")
                else:
                    st.info(f"🟡 {label}")

            with c_mitte:
                st.write("📏 Bollinger Bänder:")
                if daten["bb_oben"] is not None:
                    st.write(f"Oben: **$ {daten['bb_oben']:,.2f}**")
                    st.write(f"Unten: **$ {daten['bb_unten']:,.2f}**")
                    if daten["preis"] > daten["bb_oben"]:
                        st.warning("Preis über oberem Band")
                    elif daten["preis"] < daten["bb_unten"]:
                        st.warning("Preis unter unterem Band")
                    else:
                        st.write("Preis im normalen Band")
                else:
                    st.write("Noch zu wenig Historie.")

            with c_rechts:
                st.write("📦 Volumen:")
                st.write(f"Aktuell: **{daten['volumen_aktuell']:,.0f}**")
                if daten["volumen_schnitt"]:
                    verhaeltnis = daten["volumen_aktuell"] / daten["volumen_schnitt"]
                    st.write(f"Ø(20): **{daten['volumen_schnitt']:,.0f}**")
                    if verhaeltnis > 1.5:
                        st.warning(f"{verhaeltnis:.1f}× über Durchschnitt")
                    else:
                        st.write(f"{verhaeltnis:.1f}× Durchschnitt")

    if st.button("🗑️ Watchlist zurücksetzen (Nur Core-Coins)", key="reset_btn"):
        st.session_state.zustand["watchlist"] = ["BTC", "ETH", "SOL"]
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
            aktueller_preis = aktuellen_preis_holen(f"{position['ticker']}USDT")
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
