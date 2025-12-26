import os
import time
import threading
import requests
import json
import telebot
import sys
import pandas as pd
import numpy as np
from collections import deque
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

# --- MÉMOIRE DE CONVERSATION (Chat Naturel) ---
# Stocke les 10 derniers messages de chaque utilisateur pour le contexte
user_histories = {}

def update_history(user_id, role, content):
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=10) # Garde max 10 échanges
    user_histories[user_id].append({"role": role, "content": content})

def get_history(user_id):
    return list(user_histories.get(user_id, []))

# --- MOTEUR D'ANALYSE TECHNIQUE (Calculs Mathématiques) ---

def get_binance_data(symbol="BTCUSDT", interval="15m", limit=100):
    """Récupère les bougies pour l'analyse technique."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        resp = requests.get(url, timeout=10).json()
        
        df = pd.DataFrame(resp, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)
        return df
    except Exception as e:
        print(f"Erreur Data: {e}")
        return None

def calculate_indicators(df):
    """Calcule TOUS les indicateurs : RSI, EMA, ATR, ADX, Volume MA."""
    
    # 1. RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 2. EMA 200 (Tendance Longue)
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # 3. ATR (Volatilité)
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    df['atr'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14).mean()

    # 4. Volume Moyen (20) - Pour détecter les faux mouvements
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # 5. ADX (Force de la tendance) - Pour éviter les marchés plats
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr = df['atr'] # Approximation acceptable pour TR
    plus_di = 100 * (plus_dm.ewm(alpha=1/14).mean() / tr.ewm(alpha=1/14).mean())
    minus_di = 100 * (minus_dm.ewm(alpha=1/14).mean() / tr.ewm(alpha=1/14).mean())
    dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df['adx'] = dx.ewm(alpha=1/14).mean()

    return df

def sniper_logic(df):
    """
    LA LOGIQUE SNIPER SECURISE (6 COUCHES DE PROTECTION)
    """
    last = df.iloc[-1]
    
    # --- ANALYSE DU CONTEXTE ---
    price = last['close']
    ema200 = last['ema200']
    rsi = last['rsi']
    adx = last['adx']
    vol = last['volume']
    vol_avg = last['vol_ma']
    
    # 1. Tendance (EMA 200)
    trend = "HAUSSIER" if price > ema200 else "BAISSIER"
    
    # 2. Filtre Bougie (Confirmation visuelle)
    is_green = last['close'] > last['open']
    
    # 3. Filtre Volume (Anti-Fakeout)
    is_volume_ok = vol > vol_avg # Le volume doit être supérieur à la moyenne
    
    # 4. Filtre ADX (Anti-Range/Marché plat)
    is_market_active = adx > 20 # Si < 20, le marché dort, on ne trade pas
    
    signal = "NEUTRE"

    # --- LOGIQUE D'ENTRÉE ---
    
    # ACHAT (LONG)
    if (trend == "HAUSSIER" and         # Tendance de fond OK
        rsi < 45 and                    # Achat sur repli (Dip)
        is_green and                    # La bougie remonte (Pas de couteau qui tombe)
        is_market_active):              # Le marché bouge vraiment
        
        signal = "LONG"
    
    # VENTE (SHORT)
    elif (trend == "BAISSIER" and 
          rsi > 55 and 
          not is_green and 
          is_market_active):
        
        signal = "SHORT"

    # --- CALCUL SL / TP STRUCTUREL (Anti-Mèche) ---
    
    atr = last['atr']
    
    # On cherche les plus bas/hauts des 10 dernières bougies (Support/Résistance réel)
    lowest_low = df['low'].tail(10).min()
    highest_high = df['high'].tail(10).max()
    
    sl_price, tp_price = 0, 0
    
    if signal == "LONG":
        # SL sous le plancher structurel + petite marge
        sl_price = lowest_low - (atr * 0.2)
        # TP Calculé pour un Ratio 1:2 (Gagner 2x la perte)
        risk = price - sl_price
        tp_price = price + (risk * 2.0)
        
    elif signal == "SHORT":
        # SL au-dessus du plafond structurel
        sl_price = highest_high + (atr * 0.2)
        risk = sl_price - price
        tp_price = price - (risk * 2.0)
        
    return {
        "price": price, "signal": signal, "trend": trend,
        "rsi": round(rsi, 2), "adx": round(adx, 2),
        "sl": round(sl_price, 2), "tp": round(tp_price, 2),
        "vol_ok": is_volume_ok
    }

# --- IA : VALIDATION & CHAT ---

def ask_ai_validation(data):
    """Valide le signal technique."""
    prompt = f"""
    Agis comme un Trader Professionnel.
    Analyse Technique BTC/USDT (15m):
    - Prix: {data['price']}
    - Tendance: {data['trend']}
    - RSI: {data['rsi']} (Momentum)
    - ADX: {data['adx']} (Force)
    - Volume OK: {data['vol_ok']}
    - Signal Python: {data['signal']}
    
    Si le volume est faible, sois méfiant.
    Réponds UNIQUEMENT ce JSON :
    {{
        "score": 85,
        "raison": "Rebond technique validé sur support haussier."
    }}
    """
    try:
        comp = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model=MODEL_NAME)
        return json.loads(comp.choices[0].message.content.replace('```json', '').replace('```', '').strip())
    except: return None

def chat_with_ai(user_id, message):
    """Discussion naturelle avec mémoire."""
    history = get_history(user_id)
    
    # On ajoute le contexte système
    system_prompt = {
        "role": "system", 
        "content": "Tu es un assistant Trading Crypto expert. Tu es concis, précis et pédagogue. Tu parles français."
    }
    
    messages = [system_prompt] + history + [{"role": "user", "content": message}]
    
    try:
        response = client.chat.completions.create(messages=messages, model=MODEL_NAME)
        reply = response.choices[0].message.content
        
        # Mise à jour mémoire
        update_history(user_id, "user", message)
        update_history(user_id, "assistant", reply)
        
        return reply
    except Exception as e:
        return f"Erreur IA: {e}"

# --- HANDLERS TELEGRAM ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 **Bot Sniper Connecté !**\nJe surveille le BTC. Pose-moi une question ou attends un signal.")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    analyze_market(manual_trigger=True, chat_id=message.chat.id)

@bot.message_handler(func=lambda message: True)
def handle_chat(message):
    """Gère le chat libre avec l'IA."""
    bot.send_chat_action(message.chat.id, 'typing')
    reply = chat_with_ai(message.from_user.id, message.text)
    bot.reply_to(message, reply, parse_mode="Markdown")

# --- LOGIQUE PRINCIPALE ---

def analyze_market(manual_trigger=False, chat_id=TG_CHAT_ID):
    if not chat_id: return

    df = get_binance_data()
    if df is None: return

    df = calculate_indicators(df)
    data = sniper_logic(df)
    
    # Si pas de signal et pas forcé, on s'arrête là (Silence radio)
    if data['signal'] == "NEUTRE" and not manual_trigger:
        return

    # Validation IA
    ai_verdict = ask_ai_validation(data)
    if not ai_verdict: 
        if manual_trigger: bot.send_message(chat_id, "❌ Erreur IA, pas de validation.")
        return

    score = ai_verdict['score']
    
    # FILTRE FINAL : Si score < 75 on n'envoie RIEN (sauf si forcé manuellement)
    if score < 75 and not manual_trigger:
        return

    # Formatage Message
    entry = data['price']
    tp_pct = round(((data['tp'] - entry) / entry) * 100, 2)
    sl_pct = round(((data['sl'] - entry) / entry) * 100, 2)
    
    emoji = "🟢" if data['signal'] == "LONG" else "🔴"
    
    msg = (
        f"{emoji} **SIGNAL {data['signal']} SNIPER**\n\n"
        f"💰 Prix Entrée: `${entry:,}`\n"
        f"🟩 TP: `${data['tp']:,}` ({tp_pct}%)\n"
        f"🟥 SL: `${data['sl']:,}` ({sl_pct}%)\n\n"
        f"🎯 Score: {score}/100\n"
        f"🧠 IA: {ai_verdict['raison']}\n"
        f"📊 RSI: {data['rsi']} | ADX: {data['adx']}"
    )
    
    bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- LANCEMENT ---

@app.route('/')
def home(): return "Sniper Bot Active"

def run_loop():
    while True:
        try:
            analyze_market()
            time.sleep(900) # Scan toutes les 15 min
        except: time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
