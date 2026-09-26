# -*- coding: utf-8 -*-
import os, time, requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="KRIPTO RADAR V9", page_icon="📊", layout="wide")

st.markdown("""
    <html lang="de" class="notranslate" translate="no">
    <head><meta name="google" content="notranslate" /></head>
    </html>
    <style>
    .stApp { background-color: #0B0E11; color: #EAECEF; }
    h1, h2, h3, h4 { color: #EAECEF !important; margin-bottom: 2px !important; margin-top: 5px !important; }
    div[data-testid="stDataFrame"] > div { max-height: none !important; height: 350px !important; }
    </style>
    """, unsafe_allow_html=True)

if "gesendete_alarme" not in st.session_state:
    st.session_state.gesendete_alarme = {}

if "meine_favoriten" not in st.session_state:
    st.session_state.meine_favoriten = ["BTC", "ETH"]

if "letzter_ki_scan" not in st.session_state:
    st.session_state.letzter_ki_scan = 0

def send_telegram_message(message):
    try:
        token = st.secrets["TELEGRAM_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        url = f"https://telegram.org{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=2)
    except:
        pass

# Lädt historische Kerzen für den Chart und die Indikatoren einzeln (sehr sparsam)
def binance_kerzen_laden(ticker, intervall, limit=210):
    try:
        symbol = f"{ticker.upper()}USDT"
        binance_intervals = {"1 Minute": "1m", "5 Minuten": "5m", "15 Minuten": "15m", "1 Stunde": "1h", "4 Stunden": "4h", "1 Tag": "1d"}
        bi = binance_intervals.get(intervall, "1d")
        url = f"https://binance.com{symbol}&interval={bi}&limit={limit}"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res, columns=[
            'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume',
            'Close_time', 'Quote_asset_volume', 'Number_of_trades',
            'Taker_buy_base_asset_volume', 'Taker_buy_quote_asset_volume', 'Ignore'
        ])
        df['Open'] = df['Open'].astype(float)
        df['High'] = df['High'].astype(float)
        df['Low'] = df['Low'].astype(float)
        df['Close'] = df['Close'].astype(float)
        df.index = pd.to_datetime(df['Open_time'], unit='ms')
        return df[['Open', 'High', 'Low', 'Close']].copy()
    except:
        return None

def indikatoren_berechnen(df):
    anzahl_kerzen = len(df)
    f_sma = 200 if anzahl_kerzen >= 200 else (20 if anzahl_kerzen >= 20 else anzahl_kerzen)
    f_ema = 20 if anzahl_kerzen >= 20 else anzahl_kerzen
    f_atr = 14 if anzahl_kerzen >= 14 else anzahl_kerzen
    df['SMA_200'] = df['Close'].rolling(window=f_sma).mean().bfill()
    df['EMA_20'] = df['Close'].ewm(span=f_ema, adjust=False).mean().bfill()
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    df['ATR'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(window=f_atr).mean().bfill()
    return df

st.title("📊 KRIPTO SWING RADAR V9 – PRO TRADER TERMINAL")

st.sidebar.header("⚙️ Einstellungen")
interval_auswahl = st.sidebar.selectbox(
    "🎯 Sichtbare Zeiteinheit im Terminal:",
    ["1 Minute", "5 Minuten", "15 Minuten", "1 Stunde", "4 Stunden", "1 Tag"],
    index=2
)

st.sidebar.markdown("---")
st.sidebar.subheader("➕ Coin hinzufügen")
neuer_coin = st.sidebar.text_input("Kryptokürzel eingeben (z.B. SOL, PEPE):", key="favoriten_input").upper().strip()
if st.sidebar.button("Coin der Liste hinzufügen"):
    if neuer_coin and neuer_coin not in st.session_state.meine_favoriten:
        st.session_state.meine_favoriten.append(neuer_coin)
        st.rerun()
if st.sidebar.button("🗑️ Liste zurücksetzen"):
    st.session_state.meine_favoriten = ["BTC", "ETH"]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown(" Datenquelle: **Binance Live API**")
st.sidebar.markdown(" Taktung: **2 Sekunden Echtzeit**")

basis_tickers = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOT", "LINK", "DOGE", "SHIB", "AVAX", "NEAR", "LTC", "PEPE", "SUI"]
alle_aktiven_tickers = list(set(basis_tickers + st.session_state.meine_favoriten))

daten_liste = []
einstiegs_liste = []
st_alarm_ausloesen = False
aktueller_zeitstempel = time.time()

# EINE EINZIGE ANFRAGE für alle Live-Preise der Top-10 (Verhindert jede Blockade!)
try:
    ticker_res = requests.get("https://binance.com", timeout=2).json()
    ticker_dict = {item['symbol']: item for item in ticker_res if item['symbol'].endswith('USDT')}
except:
    ticker_dict = {}

# 1. SICHTBARE GEWINNER / VERLIERER TABELLEN GENERIEREN
for t in alle_aktiven_tickers:
    sym = f"{t}USDT"
    if sym in ticker_dict:
        live_data = ticker_dict[sym]
        s_pr = float(live_data['lastPrice'])
        s_chg = float(live_data['priceChangePercent'])
        daten_liste.append({"Ticker": t, "Preis ($)": round(s_pr, 4 if s_pr < 1 else 2), "Änderung (%)": round(s_chg, 2), "Trading Signal": "⏳ LIVE SCANNEN"})

# 2. DYNAMISCHER EINSTIEGS-SCANNER FÜR DIE ABLAGE
# Scannt die Indikatoren für den Live-Einstieg sehr sparsam im Hintergrund
for t in st.session_state.meine_favoriten:
    df_sichtbar = binance_kerzen_laden(t, interval_auswahl, limit=205)
    if df_sichtbar is None or len(df_sichtbar) < 3: continue
    df_sichtbar = indikatoren_berechnen(df_sichtbar)
    
    pr = df_sichtbar['Close'].iloc[-1]
    sma = df_sichtbar['SMA_200'].iloc[-1]
    ema = df_sichtbar['EMA_20'].iloc[-1]
    vor_close = df_sichtbar['Close'].iloc[-2]
    vor_ema = df_sichtbar['EMA_20'].iloc[-2]
    atr = df_sichtbar['ATR'].iloc[-1] if df_sichtbar['ATR'].iloc[-1] != 0 else pr * 0.02
    
    sig = None
    if pr > sma and vor_close <= vor_ema and pr > ema:
        sig = "🚀 LONG"
    elif pr < sma and vor_close >= vor_ema and pr < ema:
        sig = "📉 SHORT"
        
    if sig:
        sl = pr - (2 * atr) if "LONG" in sig else pr + (2 * atr)
        tp = pr + (3 * atr) if "LONG" in sig else pr - (3 * atr)
        st_alarm_ausloesen = True
        einstiegs_liste.append({"Ticker": t, "Richtung": sig, "Einstieg ($)": round(pr, 2), "🛑 SL ($)": round(sl, 2), "🎯 TP ($)": round(tp, 2)})
        
        # Telegram-Alarm abfeuern
        alarm_schluessel = f"{t}_{sig}_{interval_auswahl}"
        letzter_alarm = st.session_state.gesendete_alarme.get(alarm_schluessel, 0)
        if aktueller_zeitstempel - letzter_alarm > 900:
            msg = f"🔔 *LIVE-EINSTIEG GEFUNDEN!*\n\n🪙 *Coin:* {t}-USDT\n🚦 *Richtung:* {sig}\n💵 *Einstieg:* ${round(pr, 2)}\n🛑 *SL:* ${round(sl, 2)}\n🎯 *TP:* ${round(tp, 2)}\n⏱️ *Zeiteinheit:* {interval_auswahl}"
            send_telegram_message(msg)
            st.session_state.gesendete_alarme[alarm_schluessel] = aktueller_zeitstempel

if daten_liste:
    global_df = pd.DataFrame(daten_liste)
    basis_df = global_df[global_df["Ticker"].isin(basis_tickers)]
    global_gewinner = basis_df.sort_values(by="Änderung (%)", ascending=False).head(10)
    global_verlierer = basis_df.sort_values(by="Änderung (%)", ascending=True).head(10)
    favoriten_df = global_df[global_df["Ticker"].isin(st.session_state.meine_favoriten)]

    if st_alarm_ausloesen:
        st.components.v1.html("""<audio autoplay><source src="https://mixkit.co" type="audio/wav"></audio>""", height=0)

    col_links, col_rechts = st.columns(2)
    with col_links:
        st.subheader(f"🟩 Globale Binance Top-10 Gewinner (24h)")
        st.dataframe(global_gewinner[["Ticker", "Preis ($)", "Änderung (%)"]], use_container_width=True, hide_index=True)
        st.markdown("---")
        st.subheader("📋 Meine persönlichen Krypto-Favoriten")
        if not favoriten_df.empty:
            st.dataframe(favoriten_df[["Ticker", "Preis ($)", "Änderung (%)"]], use_container_width=True, hide_index=True)
        else:
            st.info("💡 Deine Liste ist aktuell leer.")
        st.markdown("---")
        
        # Live-Chartstation
        st.subheader("📊 Live-Chartstation")
        chart_liste = list(global_df["Ticker"].unique())
        ausgewaehlter_coin = st.selectbox("🎯 Coin wählen:", chart_liste, key="chart_box")
        st.markdown(f"**Aktuell geladen: {ausgewaehlter_coin}-USDT ({interval_auswahl})**")
        
        cdf = binance_kerzen_laden(ausgewaehlter_coin, interval_auswahl, limit=100)
        if cdf is not None and len(cdf) >= 2:
            cdf = indikatoren_berechnen(cdf)
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=cdf.index, open=cdf['Open'], high=cdf['High'], low=cdf['Low'], close=cdf['Close'], name="Kurs"))
            fig.add_trace(go.Scatter(x=cdf.index, y=cdf['SMA_200'], mode='lines', name='SMA 200', line=dict(color='#ea4335', width=1.5)))
            fig.add_trace(go.Scatter(x=cdf.index, y=cdf['EMA_20'], mode='lines', name='EMA 20', line=dict(color='#0ECB81', width=1.5)))
            
            try:
                c_pr = float(cdf['Close'].iloc[-1])
                high_low = cdf['High'] - cdf['Low']
                high_close = np.abs(cdf['High'] - cdf['Close'].shift())
                low_close = np.abs(cdf['Low'] - cdf['Close'].shift())
                c_atr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(window=14).mean().bfill().iloc[-1]
                c_sma = float(cdf['SMA_200'].iloc[-1])
                
                sl_u = c_pr - (2 * c_atr) if c_pr > c_sma else c_pr + (2 * c_atr)
                tp_u = c_pr + (3 * c_atr) if c_pr > c_sma else c_pr - (3 * c_atr)
                
                fig.add_shape(type="line", x0=cdf.index, x1=cdf.index[-1], y0=c_pr, y1=c_pr, line=dict(color="#2B6CB0", width=1.5, dash="dash"))
