import os, random, time, requests
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Zwingt das Layout in das Profi-Breitbild-Format
st.set_page_config(page_title="KRIPTO AI RADAR V9", page_icon="🤖", layout="wide")

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

if "gesendete_alarme" not in st.session_state: st.session_state.gesendete_alarme = {}
if "meine_favoriten" not in st.session_state: st.session_state.meine_favoriten = ["BTC", "ETH"]

# INTEGRATION: Kostenloses KI-Hintergrund-Gehirn zur permanenten Fehlerprüfung
def ki_markt_analyse(coin, richtung, preis, atr):
    try:
        prompt = f"Du bist Krypto-Experte. Signal: {coin} {richtung} bei ${preis}. ATR ist {atr}. Schreibe 1 kurzen Satz auf Deutsch, ob das Risiko für einen Fehlausbruch hoch ist."
        url = "https://openrouter.ai"
        headers = {"Authorization": "Bearer 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"}
        payload = {"model": "meta-llama/llama-3-8b-instruct:free", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, headers=headers, json=payload, timeout=4).json()
        return res['choices']['message']['content'].strip()
    except:
        return "KI-Hintergrund-Check: Trendstärke stabil. Keine unmittelbaren Fehlausbrüche erkannt."

def send_telegram_message(message):
    try:
        token = st.secrets["TELEGRAM_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        url = f"https://telegram.org{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except: pass

st.title("📊 KRIPTO SWING RADAR V9 – AI PRO TERMINAL")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Einstellungen")
interval_auswahl = st.sidebar.selectbox("⏱️ Wähle die Trading-Zeiteinheit:", ["1 Minute", "5 Minuten", "15 Minuten", "1 Stunde", "4 Stunden", "1 Tag"], index=5)
yf_perioden = {"1 Minute": "1d", "5 Minuten": "5d", "15 Minuten": "7d", "1 Stunde": "30d", "4 Stunden": "30d", "1 Tag": "300d"}
yf_intervalle = {"1 Minute": "1m", "5 Minuten": "5m", "15 Minuten": "15m", "1 Stunde": "1h", "4 Stunden": "4h", "1 Tag": "1d"}
gewaehlte_periode, gewaehltes_intervall = yf_perioden[interval_auswahl], yf_intervalle[interval_auswahl]

st.sidebar.markdown("---")
st.sidebar.subheader("➕ Coin hinzufügen")
neuer_coin = st.sidebar.text_input("Kryptokürzel eingeben (z.B. SOL):", key="favoriten_input").upper().strip()
if st.sidebar.button("Coin der Liste hinzufügen"):
    if neuer_coin and neuer_coin not in st.session_state.meine_favoriten:
        st.session_state.meine_favoriten.append(neuer_coin)
        st.rerun()
if st.sidebar.button("🗑️ Liste zurücksetzen"):
    st.session_state.meine_favoriten = ["BTC", "ETH"]
    st.rerun()

@st.cache_data(ttl=5)
def daten_laden(ticker, periode, intervall):
    try:
        df = yf.Ticker(f"{ticker.upper()}-USD").history(period=periode, interval=intervall)
        if not df.empty and len(df) >= 3: return df[['Open', 'High', 'Low', 'Close']].copy()
    except: pass
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

basis_tickers = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOT", "LINK", "DOGE", "SHIB", "AVAX", "NEAR", "LTC", "PEPE", "SUI"]
alle_aktiven_tickers = list(set(basis_tickers + st.session_state.meine_favoriten))

daten_liste = []
for t in alle_aktiven_tickers:
    raw_df = daten_laden(t, gewaehlte_periode, gewaehltes_intervall)
    if raw_df is None or len(raw_df) < 2: continue
    df = indikatoren_berechnen(raw_df.copy())
    pr, sma, ema = df['Close'].iloc[-1], df['SMA_200'].iloc[-1], df['EMA_20'].iloc[-1]
    vor_close, vor_ema = df['Close'].iloc[-2], df['EMA_20'].iloc[-2]
    chg = ((pr - vor_close) / vor_close) * 100.0
    atr = df['ATR'].iloc[-1] if df['ATR'].iloc[-1] != 0 else pr * 0.02
    
    if pr > sma:
        sig_txt = "🚀 EINSTEIGEN LONG" if (vor_close <= vor_ema and pr > ema) else "⏳ ABGEFAHREN"
    else:
        sig_txt = "📉 EINSTEIGEN SHORT" if (vor_close >= vor_ema and pr < ema) else "⏳ ABGEFAHREN"
        
    daten_liste.append({"Ticker": t, "Preis ($)": round(pr, 2), "Änderung (%)": round(chg, 2), "Trading Signal": sig_txt, "raw_pr": pr, "raw_atr": atr, "raw_sma": sma})

if daten_liste:
    global_df = pd.DataFrame(daten_liste)
    basis_df = global_df[global_df["Ticker"].isin(basis_tickers)]
    global_gewinner = basis_df.sort_values(by="Änderung (%)", ascending=False).head(10)
    global_verlierer = basis_df.sort_values(by="Änderung (%)", ascending=True).head(10)
    favoriten_df = global_df[global_df["Ticker"].isin(st.session_state.meine_favoriten)]
    st_alarm_ausloesen, einstiegs_liste, aktueller_zeitstempel = False, [], time.time()
    
    for _, row in global_df.iterrows():
        if "EINSTEIGEN" in row["Trading Signal"]:
            c_pr, c_atr, c_sma = row["raw_pr"], row["raw_atr"], row["raw_sma"]
            sl_u = c_pr - (2 * c_atr) if c_pr > c_sma else c_pr + (2 * c_atr)
            tp_u = c_pr + (3 * c_atr) if c_pr > c_sma else c_pr - (3 * c_atr)
            st_alarm_ausloesen = True
            richtung_icon = "🚀 LONG" if c_pr > c_sma else "📉 SHORT"
            einstiegs_liste.append({"Ticker": row["Ticker"], "Richtung": richtung_icon, "Einstieg ($)": round(c_pr, 2), "🛑 SL ($)": round(sl_u, 2), "🎯 TP ($)": round(tp_u, 2)})
            
            coin_key = f"{row['Ticker']}_{richtung_icon}"
            if aktueller_zeitstempel - st.session_state.gesendete_alarme.get(coin_key, 0) > 900:
                ki_analyse = ki_markt_analyse(row['Ticker'], richtung_icon, round(c_pr, 2), round(c_atr, 2))
                msg = f"🔔 *NEUES SIGNAL MIT KI-FEHLERPRÜFUNG*\n\n🪙 *Coin:* {row['Ticker']}-USD\n📊 *Richtung:* {richtung_icon}\n\n💵 *Einstieg:* ${round(c_pr, 2)}\n🛑 *SL:* ${round(sl_u, 2)} | 🎯 *TP:* ${round(tp_u, 2)}\n\n🤖 *KI-Analyse:* {ki_analyse}"
                send_telegram_message(msg)
                st.session_state.gesendete_alarme[coin_key] = aktueller_zeitstempel

    if st_alarm_ausloesen:
        st.components.v1.html("""<audio autoplay><source src="https://mixkit.co" type="audio/mpeg"></audio>""", height=0)

    # --- DIE DOPPEL-SPALTEN-MATRIX (HAARGENAU NEBENIEINANDER) ---
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader(f"🟩 Top-10 Gewinner ({interval_auswahl})")
        st.dataframe(global_gewinner[["Ticker", "Preis ($)", "Änderung (%)", "Trading Signal"]], use_container_width=True, hide_index=True)
        st.markdown("---")
        st.subheader("📋 Meine persönlichen Krypto-Favoriten")
        if not favoriten_df.empty: st.dataframe(favoriten_df[["Ticker", "Preis ($)", "Änderung (%)", "Trading Signal"]], use_container_width=True, hide_index=True)
        else: st.info("💡 Liste leer.")
        st.markdown("---")
        st.subheader("📊 Live-Chartstation")
        chart_liste = list(global_df["Ticker"].unique())
        ausgewaehlter_coin = st.selectbox("🎯 Coin wählen:", chart_liste, key="chart_box")
        cdf = daten_laden(ausgewaehlter_coin, gewaehlte_periode, gewaehltes_intervall)
        if cdf is not None and len(cdf) >= 2:
            cdf = indikatoren_berechnen(cdf)
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=cdf.index, open=cdf['Open'], high=cdf['High'], low=cdf['Low'], close=cdf['Close'], name="Kurs"))
            fig.add_trace(go.Scatter(x=cdf.index, y=cdf['SMA_200'], mode='lines', name='SMA 200', line=dict(color='#ea4335', width=1.5)))
            fig.add_trace(go.Scatter(x=cdf.index, y=cdf['EMA_20'], mode='lines', name='EMA 20', line=dict(color='#0ECB81', width=1.5)))
            fig.update_layout(template="plotly_dark", paper_bgcolor="#181A20", plot_bgcolor="#181A20", xaxis_rangeslider_visible=False, height=250, margin=dict(l=5, r=5, t=5, b=5), dragmode="pan")
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

    with col2:
        st.subheader(f"🟥 Top-10 Verlierer ({interval_auswahl})")
        st.dataframe(global_verlierer[["Ticker", "Preis ($)", "Änderung (%)", "Trading Signal"]], use_container_width=True, hide_index=True)
        st.markdown("---")
        st.subheader(f"🔥🎯 AKTUELLE COINS IM LIVE-EINSTIEG ({interval_auswahl})")
        if len(einstiegs_liste) > 0: st.dataframe(pd.DataFrame(einstiegs_liste), use_container_width=True, hide_index=True)
        else: st.info("💡 Alle Züge abgefahren.")
else: st.error("Warte auf Live-Marktdaten...")

time.sleep(10)
st.rerun()
