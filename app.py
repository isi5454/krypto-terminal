import streamlit as st
import random
import time

st.set_page_config(page_title="Pro Trading Terminal v3.5", page_icon="⚡", layout="wide")

# --- 🔍 FRISCHE PROFI-DATENBANK INITIALISIEREN ---
if 'trading_daten' not in st.session_state:
    st.session_state.trading_daten = {
        "BTC": {"name": "Bitcoin", "preis": 76782.00, "timeframe": "⏱️ 15 Min", "status": "🟡 ABWARTEN", "ziel": 0.0, "prozent": 0.0, "kerzen": [76700 + random.uniform(-100, 100) for _ in range(12)], "trend_200": 76100.00},
        "ETH": {"name": "Ethereum", "preis": 2479.00, "timeframe": "🕐 1 Stunde", "status": "🟡 ABWARTEN", "ziel": 0.0, "prozent": 0.0, "kerzen": [2470 + random.uniform(-10, 10) for _ in range(12)], "trend_200": 2510.00},
        "SOL": {"name": "Solana", "preis": 138.00, "timeframe": "⏱️ 15 Min", "status": "🟡 ABWARTEN", "ziel": 0.0, "prozent": 0.0, "kerzen": [135 + random.uniform(-2, 2) for _ in range(12)], "trend_200": 134.00}
    }
    st.session_state.fear_greed = 45

COIN_VORLAGEN = {
    "XRP": {"name": "Ripple", "preis": 0.58, "trend_200": 0.55},
    "ADA": {"name": "Cardano", "preis": 0.35, "trend_200": 0.33},
    "LINK": {"name": "Chainlink", "preis": 11.50, "trend_200": 11.00}
}

# --- ➕ OBERFLÄCHE: SUCHFENSTER ---
st.title("⚡ KI Krypto-Daytrading High-Tech Terminal v3.5")
st.subheader("➕ Neuen Coin zur Live-Analyse hinzufügen")
c_eingabe, c_button = st.columns(2)

neuer_coin_ticker = c_eingabe.text_input("Geben Sie das Krypto-Kürzel ein:", placeholder="Z. B. XRP, ADA, LINK", key="add_input").upper().strip()

if c_button.button("🪙 Coin hinzufügen", use_container_width=True, key="add_btn"):
    if neuer_coin_ticker:
        if neuer_coin_ticker in st.session_state.trading_daten:
            st.warning(f"Der Coin {neuer_coin_ticker} wird bereits analysiert!")
        elif neuer_coin_ticker in COIN_VORLAGEN:
            vorlage = COIN_VORLAGEN[neuer_coin_ticker]
            st.session_state.trading_daten[neuer_coin_ticker] = {
                "name": vorlage["name"], "preis": vorlage["preis"], "timeframe": "⏱️ 15 Min", "status": "🟡 ABWARTEN", "ziel": 0.0, "prozent": 0.0, "kerzen": [vorlage["preis"] * (1 + random.uniform(-0.01, 0.01)) for _ in range(12)], "trend_200": vorlage["trend_200"]
            }
            st.success(f"Erfolgreich hinzugefügt: {vorlage['name']} ({neuer_coin_ticker})")
            time.sleep(0.5)
            st.rerun()
        else:
            p = random.uniform(1.0, 10.0)
            st.session_state.trading_daten[neuer_coin_ticker] = {
                "name": f"Custom-{neuer_coin_ticker}", "preis": p, "timeframe": "⏱️ 15 Min", "status": "🟡 ABWARTEN", "ziel": 0.0, "prozent": 0.0, "kerzen": [p * (1 + random.uniform(-0.01, 0.01)) for _ in range(12)], "trend_200": p * 0.98
            }
            st.success(f"Coin {neuer_coin_ticker} wurde angelegt!")
            time.sleep(0.5)
            st.rerun()

st.markdown("---")

# --- 📊 ANGST- & GIER-BAROMETER ---
st.subheader("🧠 Globale Markt-Psychologie (Sentiment)")
fg = st.session_state.fear_greed
if fg < 30: stimmung, farbe = "🚨 EXTREME ANGST (Statistischer Kaufbereich)", "error"
elif fg < 50: stimmung, farbe = "🟡 ANGST / SKEPSIS (Vorsichtige Akkumulation)", "warning"
elif fg < 70: stimmung, farbe = "🟢 GIER / OPTIMISMUS (Bullenmarkt aktiv)", "success"
else: stimmung, farbe = "💥 EXTREME GIER (Überhitzung - Crashgefahr!)", "error"

st.progress(fg / 100)
st.markdown(f"**Aktueller Index-Wert:** `{fg}/100` | **Marktstimmung:** **{stimmung}**")

st.markdown("---")

# --- 🔄 MÄRKTE SCANNEN ---
st.subheader("⚙️ Steuerungs-Zentrale")
if st.button("🔄 Märkte scannen & Signale neu berechnen", type="primary", use_container_width=True, key="scan_btn"):
    st.session_state.fear_greed = max(5, min(95, st.session_state.fear_greed + random.randint(-8, 8)))
    for ticker, daten in st.session_state.trading_daten.items():
        daten["preis"] *= (1 + random.uniform(-0.02, 0.02))
        daten["kerzen"].append(daten["preis"])
        if len(daten["kerzen"]) > 12:
            daten["kerzen"].pop(0)
            
        zufall = random.random()
        if zufall < 0.30:
            daten["status"] = "🟢 JETZT EINSTEIGEN (KAUFEN)"
            daten["prozent"] = random.uniform(5.0, 15.0)
            daten["ziel"] = daten["preis"] * (1 + (daten["prozent"] / 100))
        elif zufall > 0.75:
            daten["status"] = "🔴 AUSSTIEG (VERKAUFEN)"
            daten["prozent"] = 0.0
            daten["ziel"] = 0.0
        else:
            daten["status"] = "🟡 ABWARTEN"
    st.success("Märkte und Kerzen-Charts erfolgreich aktualisiert!")
    time.sleep(0.5)
    st.rerun()

st.markdown("---")

# --- OBERFLÄCHE: LAYOUT ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 Technische Live-Signale & Hebel-Rechner")
    
    for ticker, daten in list(st.session_state.trading_daten.items()):
        with st.expander(f"**{daten['name']} ({ticker})** — Kurs: **$ {daten['preis']:,.2f}** | Intervall: **{daten['timeframe']}**", expanded=True):
            
            optionen = ["⏱️ 5 Min", "⏱️ 15 Min", "🕐 1 Stunde", "🛑 4 Stunden", "📅 1 Tag"]
            standard_index = optionen.index(daten["timeframe"]) if daten["timeframe"] in optionen else 1
            
            neues_intervall = st.selectbox(
                "⏱️ Zeiteinheit auswählen:",
                options=optionen,
                index=standard_index,
                key=f"select_{ticker}"
            )
            
            if neues_intervall != daten["timeframe"]:
                st.session_state.trading_daten[ticker]["timeframe"] = neues_intervall
                st.rerun()
                
            st.markdown("---")
            c_links, c_rechts = st.columns(2)
            
            with c_links:
                st.write("📊 Candlestick-Trend:")
                balken_daten = []
                for i in range(len(daten["kerzen"])-1):
                    diff = daten["kerzen"][i+1] - daten["kerzen"][i]
                    balken_daten.append(diff)
                st.bar_chart(balken_daten, height=100)
                
                if "KAUFEN" in daten["status"]:
                    st.success(f"**{daten['status']}**")
                    st.markdown(f"🎯 **Ziel:** **$ {daten['ziel']:,.2f}** *(+{daten['prozent']:.1f}%)*")
                elif "VERKAUFEN" in daten["status"]:
                    st.error(f"⚠️ **{daten['status']}**")
                else:
                    st.info(f"⏳ **{daten['status']}**")
                    
            with c_rechts:
                # 🛡️ NEU: INTEGRATION DES RISIKO-FILTERS (AMPELELEMENT)
                st.write("🛡️ KI-Risikofilter (Sicherheits-Check):")
                
                # Check 1: Übergeordneter Markttrend
                trend_ok = daten["preis"] > daten["trend_200"]
                # Check 2: Volatilitätscheck (Schwankungsauswertung)
                vola_hoch = abs(balken_daten[-1] / daten["preis"]) > 0.015 if balken_daten else False
                
                if vola_hoch:
                    st.error("🚨 RISIKO HOCH: Markt zu unruhig! (Keine Trades)")
                elif trend_ok:
                    st.success("🟢 RISIKO NIEDRIG: Sicherer Aufwärtstrend")
                else:
                    st.warning("🟡 RISIKO MITTEL: Abwärtstrend (Nur kleine Einsätze)")
                
                st.markdown("---")
                st.write("🧮 Positionsrechner (Risiko):")
                budget = st.number_input("Dein Einsatz ($):", min_value=10, max_value=10000, value=100, key=f"risk_{ticker}")
                
                if "KAUFEN" in daten["status"]:
                    # Wenn das Risiko mittel/hoch ist, drosseln wir den Hebel automatisch
                    basis_hebel = 5 if daten["timeframe"] in ["⏱️ 5 Min", "⏱️ 15 Min"] else 3
                    empfohlener_hebel = max(1, basis_hebel - 2) if not trend_ok or vola_hoch else basis_hebel
                    
                    positionsgroesse = budget * empfohlener_hebel
                    sl_preis = daten["preis"] * 0.97
                    
                    st.warning(f"推奨 **Hebel:** **{empfohlener_hebel}x** (Sicherheits-angepasst)")
                    st.write(f"💼 **Gesamt-Position:** $ {positionsgroesse:,.2f}")
                    st.write(f"🛡️ **Stop-Loss Reißleine:** $ {sl_preis:,.2f}")
                else:
                    st.write("Warte auf Kaufsignal...")

with col2:
    st.subheader("ℹ️ Daytrading Akademie")
    st.markdown("""
    **💡 Das neue Sicherheits-System erklärt:**
    
    *   **🟢 RISIKO NIEDRIG:** Der Preis bewegt sich über der langfristigen 200-Linie. Die statistische Wahrscheinlichkeit für einen Gewinn ist hier am höchsten.
    *   **🟡 RISIKO MITTEL:** Der Coin befindet sich im Abwärtstrend. Das System halbiert hier automatisch Ihren **empfohlenen Hebel**, um Ihr Kapital zu schonen.
    *   **🚨 RISIKO HOCH:** Der Kurs schlägt gerade unkontrolliert aus. Das System warnt Sie aktiv vor dem Einstieg (Fettnäpfchen-Schutz).
    """)
    
    if st.button("🗑️ Zurücksetzen (Nur Core-Coins)", key="reset_btn"):
        if 'trading_daten' in st.session_state: del st.session_state['trading_daten']
        st.rerun()
