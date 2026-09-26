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

# Cache für gesendete Alarme und Favoriten initialisieren
if "gesendete_alarme" not in st.session_state:
    st.session_state.gesendete_alarme = {}

if "meine_favoriten" not in st.session_state:
    st.session_state.meine_favoriten = ["BTC", "ETH"]

# Funktion zum Senden von Telegram-Nachrichten
def send_telegram_message(message):
    try:
        token = st.secrets["TELEGRAM_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        url = f"https://telegram.org{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=3)
    except:
        pass

# NEU: Professioneller Daten-Loader direkt von der öffentlichen Binance-API
@st.cache_data(ttl=1)
def binance_daten_laden(ticker, intervall, limit=250):
    try:
        # Binance nutzt Symbole wie BTCUSDT
        symbol = f"{ticker.upper()}USDT"
        # Umrechnung der Zeiteinheiten für Binance
        binance_intervals = {"1 Minute": "1m", "5 Minuten": "5m", "15 Minuten": "15m", "1 Stunde": "1h", "4 Stunden": "4h", "1 Tag": "1d"}
        bi = binance_intervals.get(intervall, "1d")
        
        url = f"https://binance.com{symbol}&interval={bi}&limit={limit}"
        res = requests.get(url, timeout=3).json()
        
        # Umwandlung der Binance-Rohdaten in eine saubere Tabelle
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

st.title("📊 KRIPTO SWING RADAR V9 – PRO TRADER TERMINAL (BINANCE LIVE)")

st.sidebar.header("⚙️ Einstellungen")
# Das Auswahl-Intervall steuert ab jetzt NUR NOCH das, was Sie AUF DEM BILDSCHIRM sehen!
interval_auswahl = st.sidebar.selectbox(
    "🎯 Sichtbare Zeiteinheit im Terminal:",
    ["1 Minute", "5 Minuten", "15 Minuten", "1 Stunde", "4 Stunden", "1 Tag"],
    index=2  # Startet übersichtlich mit 15 Minuten
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
st.sidebar.markdown(" Taktung: **1 Sekunde Echtzeit**")

basis_tickers = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOT", "LINK", "DOGE", "SHIB", "AVAX", "NEAR", "LTC", "PEPE", "SUI"]
alle_aktiven_tickers = list(set(basis_tickers + st.session_state.meine_favoriten))

daten_liste = []
einstiegs_liste = []
st_alarm_ausloesen = False
aktueller_zeitstempel = time.time()

# Zeiteinheiten, die das KI-System parallel im Hintergrund scannt
hintergrund_zeiteinheiten = ["1 Minute", "5 Minuten", "15 Minuten", "1 Stunde"]

# 1. HINTERGRUND-KI SCANNER (Prüft im Hintergrund alle Zeiteinheiten auf Alarme)
for t in alle_aktiven_tickers:
    for hz in hintergrund_zeiteinheiten:
        hdf = binance_daten_laden(t, hz, limit=205)
        if hdf is None or len(hdf) < 3: continue
        hdf = indikatoren_berechnen(hdf)
        
        h_pr = hdf['Close'].iloc[-1]
        h_sma = hdf['SMA_200'].iloc[-1]
        h_ema = hdf['EMA_20'].iloc[-1]
        h_vor_close = hdf['Close'].iloc[-2]
        h_vor_ema = hdf['EMA_20'].iloc[-2]
        h_atr = hdf['ATR'].iloc[-1] if hdf['ATR'].iloc[-1] != 0 else h_pr * 0.02
        
        # Signalprüfung für den aktuellen Takt
        if h_pr > h_sma and h_vor_close <= h_vor_ema and h_pr > h_ema:
            h_sig = "🚀 LONG"
        elif h_pr < h_sma and h_vor_close >= h_vor_ema and h_pr < h_ema:
            h_sig = "📉 SHORT"
        else:
            h_sig = None
            
        if h_sig:
            h_sl = h_pr - (2 * h_atr) if "LONG" in h_sig else h_pr + (2 * h_atr)
            h_tp = h_pr + (3 * h_atr) if "LONG" in h_sig else h_pr - (3 * h_atr)
            
            # Wenn das Signal auf der vom Nutzer gewählten Zeiteinheit liegt, kommt es in die Tabelle
            if hz == interval_auswahl:
                st_alarm_ausloesen = True
                einstiegs_liste.append({"Ticker": t, "Richtung": h_sig, "Einstieg ($)": round(h_pr, 4 if h_pr < 1 else 2), "🛑 SL ($)": round(h_sl, 4 if h_sl < 1 else 2), "🎯 TP ($)": round(h_tp, 4 if h_tp < 1 else 2)})
            
            # Telegram Alarm Logik für ALLE Hintergrund-Signale (15 Minuten Spam-Schutz)
            alarm_schluessel = f"{t}_{h_sig}_{hz}"
            letzter_alarm = st.session_state.gesendete_alarme.get(alarm_schluessel, 0)
            if aktueller_zeitstempel - letzter_alarm > 900:
                msg = (
                    f"🔔 *KI-RADAR EINSTIEG GEFUNDEN!*\n\n"
                    f"🪙 *Coin:* {t}-USDT\n"
                    f"⏱️ *Zeiteinheit:* {hz}\n"
                    f"🚦 *Richtung:* {h_sig}\n"
                    f"💵 *Einstieg:* ${round(h_pr, 4 if h_pr < 1 else 2)}\n"
                    f"🛑 *Stop Loss:* ${round(h_sl, 4 if h_sl < 1 else 2)}\n"
                    f"🎯 *Take Profit:* ${round(h_tp, 4 if h_tp < 1 else 2)}"
                )
                send_telegram_message(msg)
                st.session_state.gesendete_alarme[alarm_schluessel] = aktueller_zeitstempel

    # 2. GENERIERUNG DER DYNAMISCHEN SICHTBAREN TABELLEN
    df_sichtbar = binance_daten_laden(t, interval_auswahl, limit=205)
    if df_sichtbar is None or len(df_sichtbar) < 2: continue
    df_sichtbar = indikatoren_berechnen(df_sichtbar)
    
    s_pr = df_sichtbar['Close'].iloc[-1]
    s_sma = df_sichtbar['SMA_200'].iloc[-1]
    s_ema = df_sichtbar['EMA_20'].iloc[-1]
    s_vor_close = df_sichtbar['Close'].iloc[-2]
    s_vor_ema = df_sichtbar['EMA_20'].iloc[-2]
    s_chg = ((s_pr - s_vor_close) / s_vor_close) * 100.0
    
    if s_pr > s_sma:
        s_sig_txt = "🚀 EINSTEIGEN LONG" if (s_vor_close <= s_vor_ema and s_pr > s_ema) else "⏳ ABGEFAHREN"
    else:
        s_sig_txt = "📉 EINSTEIGEN SHORT" if (s_vor_close >= s_vor_ema and s_pr < s_ema) else "⏳ ABGEFAHREN"
        
    daten_liste.append({"Ticker": t, "Preis ($)": round(s_pr, 4 if s_pr < 1 else 2), "Änderung (%)": round(s_chg, 2), "Trading Signal": s_sig_txt})

if daten_liste:
    global_df = pd.DataFrame(daten_liste)
    basis_df = global_df[global_df["Ticker"].isin(basis_tickers)]
    global_gewinner = basis_df.sort_values(by="Änderung (%)", ascending=False).head(10)
    global_verlierer = basis_df.sort_values(by="Änderung (%)", ascending=True).head(10)
    favoriten_df = global_df[global_df["Ticker"].isin(st.session_state.meine_favoriten)]

    if st_alarm_ausloesen:
        st.components.v1.html("""<audio autoplay><source src="https://mixkit.co" type="audio/wav"></audio>""", height=0)

    # 2-Spalten Layout Aufbau
    col_links, col_rechts = st.columns(2)
    with col_links:
        st.subheader(f"🟩 Globale Binance Top-10 Gewinner ({interval_auswahl})")
        st.dataframe(global_gewinner, use_container_width=True, hide_index=True)
        st.markdown("---")
        st.subheader("📋 Meine persönlichen Krypto-Favoriten")
        if not favoriten_df.empty:
            st.dataframe(favoriten_df, use_container_width=True, hide_index=True)
        else:
            st.info("💡 Deine Liste ist aktuell leer.")
        st.markdown("---")
        
        # Live-Chartstation
        st.subheader("📊 Live-Chartstation")
        chart_liste = list(global_df["Ticker"].unique())
        ausgewaehlter_coin = st.selectbox("🎯 Coin wählen:", chart_liste, key="chart_box")
        st.markdown(f"**Aktuell geladen: {ausgewaehlter_coin}-USDT ({interval_auswahl})**")
        
        cdf = binance_daten_laden(ausgewaehlter_coin, interval_auswahl, limit=100)
        if cdf is not None and len(cdf) >= 2:
            cdf = indikatoren_berechnen(cdf)
            fig = go.Figure()
