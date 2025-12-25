import os
import time
import threading
import requests
import json
import telebot
import sys
import pandas as pd
import numpy as np
from groq import Groq
from flask import Flask

# --- CONFIGURATION SYSTÈME ---
sys.stdout.reconfigure(encoding='utf-8')

# --- VARIABLES D'ENVIRONNEMENT ---
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')
MODEL_NAME = os.environ.get('MODEL_NAME', 'llama-3.3-70b-versatile')

client = Groq(api_key=GROQ_API_KEY)
app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- MOTEUR D'ANALYSE TECHNIQUE (LE CERVEAU MATHÉMATIQUE) ---

def get_binance_data(symbol="BTCUSDT", interval="15m", limit=100):
    """Récupère les données historiques pour calculer les indicateurs."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        resp = requests.get(url, timeout=10).json()
        
        # Création du DataFrame (Tableau de données)
        df = pd.DataFrame(resp, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
        
        # Conversion en nombres décimaux
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)
        
        return df
    except Exception as e:
        print(f"Erreur Data: {e}")
        return None

def calculate_indicators(df):
    """Calcule RSI, EMA, ATR pour la stratégie SMC."""
    # 1. RSI (14) - Pour savoir si c'est suracheté/survendu
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 2. EMA 200 - La Tendance de Fond (SMC: On suit la tendance)
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # 3. EMA 50 - Tendance court terme
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

    # 4. ATR (Average True Range) - Pour calculer TP et SL précis
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()

    return df

def smc_strategy_logic(df):
    """Détermine la direction et les niveaux clés (Python Logic)."""
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # Tendance
    trend = "HAUSSIER" if last['close'] > last['ema200'] else "BAISSIER"
    
    # Logique de pré-signal (Filtre mathématique)
    signal = "NEUTRE"
    
    # Condition ACHAT (LONG) : Tendance Hausse + RSI bas + Rebond
    if trend == "HAUSSIER" and last['rsi'] < 45:
        signal = "LONG"
    
    # Condition VENTE (SHORT) : Tendance Baisse + RSI haut + Rejet
    elif trend == "BAISSIER" and last['rsi'] > 55:
        signal = "SHORT"

    # Calcul SL / TP (Ratio 1:2 minimum)
    # On utilise l'ATR pour adapter le SL à la volatilité du moment
    atr = last['atr']
    price = last['close']
    
    if signal == "LONG":
        sl_price = price - (atr * 1.5) # SL sous le dernier mouvement
        tp_price = price + (atr * 3.0) # TP vise 2x le risque
    elif signal == "SHORT":
        sl_price = price + (atr * 1.5)
        tp_price = price - (atr * 3.0)
    else:
        sl_price = 0
        tp_price = 0
        
    return {
        "price": price,
        "signal": signal,
        "trend": trend,
        "rsi": round(last['rsi'], 2),
        "atr": round(atr, 2),
        "sl": round(sl_price, 2),
        "tp": round(tp_price, 2)
    }

# --- INTELLIGENCE ARTIFICIELLE ---

def ask_ai_validation(data):
    """Demande à l'IA de valider le signal et donner un score."""
    if data['signal'] == "NEUTRE":
        return None

    prompt = f"""
    Tu es un Expert Trader SMC (Smart Money Concepts).
    Je te donne les données techniques calculées par mon algorithme.
    
    CONTEXTE DU MARCHÉ (BTC/USDT 15m):
    - Prix Actuel: {data['price']} $
    - Tendance de fond (EMA200): {data['trend']}
    - RSI (Momentum): {data['rsi']}
    - Signal Technique suggéré: {data['signal']}
    
    TA MISSION:
    Agis comme un Sniper. Sois très strict.
    Estime un score de confiance de 0 à 100.
    Si le RSI est contradictoire avec la tendance, baisse le score.
    
    Réponds UNIQUEMENT avec ce JSON :
    {{
        "score": 85,
        "raison_courte": "Structure haussière validée par RSI faible."
    }}
    """
    
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME
        )
        content = completion.choices[0].message.content
        clean_json = content.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"Erreur IA: {e}")
        return {"score": 50, "raison_courte": "Analyse IA indisponible."}

# --- COMMANDES BOT ---

@bot.message_handler(commands=['analyse'])
def manual_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    analyze_market(manual_trigger=True, chat_id=message.chat.id)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🤖 **Bot Sniper SMC Actif.**\nJe scanne le marché en silence...\n/analyse pour forcer un scan.")

# --- COEUR DU SYSTÈME ---

def analyze_market(manual_trigger=False, chat_id=TG_CHAT_ID):
    if not chat_id: return

    # 1. Récupération Data
    df = get_binance_data()
    if df is None: return

    # 2. Calculs Maths
    df = calculate_indicators(df)
    
    # 3. Stratégie SMC Python
    data = smc_strategy_logic(df)
    
    # Si pas de signal technique et pas forcé manuellement -> On arrête
    if data['signal'] == "NEUTRE" and not manual_trigger:
        return

    # 4. Validation IA
    ai_verdict = ask_ai_validation(data)
    if not ai_verdict:
        if manual_trigger: bot.send_message(chat_id, "🥱 Marché neutre. Pas de setup SMC clair.")
        return

    score = ai_verdict['score']
    reason = ai_verdict['raison_courte']

    # FILTRE SNIPER : On envoie seulement si Score > 75 (ou si forcé)
    if score < 75 and not manual_trigger:
        return 

    # 5. Formatage du Message PRO
    # Calcul des pourcentages pour affichage
    entry = data['price']
    tp = data['tp']
    sl = data['sl']
    
    tp_pct = round(((tp - entry) / entry) * 100, 2)
    sl_pct = round(((sl - entry) / entry) * 100, 2)
    
    # Emojis dynamiques
    if data['signal'] == "LONG":
        header = "🟢 SIGNAL LONG DÉTECTÉ (ACHAT)"
        color = "🟩"
    else:
        header = "🔴 SIGNAL SHORT DÉTECTÉ (VENTE)"
        color = "🟥"
        
    msg = (
        f"{header}\n\n"
        f"💰 Prix Entrée: ${entry:,}\n"
        f"🟩 TP: ${tp:,} ({tp_pct}%)\n"
        f"🟥 SL: ${sl:,} ({sl_pct}%)\n\n"
        f"🎯 Score Sniper: {score}/100\n"
        f"🤖 IA: {reason}\n"
        f"📉 RSI: {data['rsi']} | Tendance: {data['trend']}"
    )
    
    bot.send_message(chat_id, msg)

# --- SERVEUR WEB (POUR RENDER) ---
@app.route('/')
def home(): return "Sniper Bot Online"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

def run_auto_loop():
    """Boucle infinie qui analyse toutes les 15 minutes"""
    while True:
        try:
            analyze_market()
            # On attend 15 minutes (900 sec) pour la prochaine bougie
            time.sleep(900) 
        except Exception as e:
            print(f"Erreur Loop: {e}")
            time.sleep(60)

def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_auto_loop, daemon=True).start()
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
