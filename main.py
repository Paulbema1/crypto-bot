import os
import sys
import time
import threading
import requests
import json
import telebot
import pandas as pd
import numpy as np
from collections import deque
from threading import Lock
from groq import Groq
from flask import Flask

# --- FORCER UTF-8 PARTOUT ---
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['LANG'] = 'C.UTF-8'
os.environ['LC_ALL'] = 'C.UTF-8'

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except:
    pass

# --- VARIABLES D'ENVIRONNEMENT ---
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')
MODEL_NAME = os.environ.get('MODEL_NAME', 'llama-3.3-70b-versatile')

# Validation des variables d'environnement
if not all([GROQ_API_KEY, TG_TOKEN, TG_CHAT_ID]):
    print("ERREUR: Variables d'environnement manquantes!")
    print("Requis: GROQ_API_KEY, TG_TOKEN, TG_CHAT_ID")
    sys.exit(1)

client = Groq(api_key=GROQ_API_KEY)
app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- MÉMOIRE DE CONVERSATION ---
history_lock = Lock()
user_histories = {}

def update_history(user_id, role, content):
    with history_lock:
        if user_id not in user_histories:
            user_histories[user_id] = deque(maxlen=10)
        user_histories[user_id].append({"role": role, "content": content})

def get_history(user_id):
    with history_lock:
        return list(user_histories.get(user_id, []))

# --- MOTEUR D'ANALYSE TECHNIQUE ---

def get_binance_data(symbol="BTCUSDT", interval="15m", limit=100):
    """Recupere les bougies pour l'analyse technique."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        resp = requests.get(url, timeout=10).json()
        
        if isinstance(resp, dict) and 'code' in resp:
            print(f"Erreur Binance API: {resp}")
            return None
        
        df = pd.DataFrame(resp, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
        ])
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)
        return df
    except requests.exceptions.RequestException as e:
        print(f"Erreur Reseau Binance: {e}")
        return None
    except Exception as e:
        print(f"Erreur Data: {e}")
        return None

def calculate_indicators(df):
    """Calcule TOUS les indicateurs : RSI, EMA, ATR, ADX, Volume MA."""
    
    # 1. RSI (14)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi'] = df['rsi'].fillna(50)

    # 2. EMA 200
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # 3. True Range & ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = true_range.rolling(14).mean()

    # 4. Volume Moyen
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # 5. ADX
    plus_dm = df['high'].diff()
    minus_dm = df['low'].shift() - df['low']
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr_smooth = true_range.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/14, adjust=False).mean() / tr_smooth.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1/14, adjust=False).mean() / tr_smooth.replace(0, np.nan))
    di_sum = plus_di + minus_di
    dx = (np.abs(plus_di - minus_di) / di_sum.replace(0, np.nan)) * 100
    df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()
    
    # Nettoyer les NaN
    df['rsi'] = df['rsi'].fillna(50)
    df['ema200'] = df['ema200'].bfill().ffill()
    df['atr'] = df['atr'].bfill().ffill().fillna(0)
    df['vol_ma'] = df['vol_ma'].bfill().ffill().fillna(0)
    df['adx'] = df['adx'].fillna(0)

    return df

def sniper_logic(df):
    """LA LOGIQUE SNIPER SECURISEE (6 COUCHES DE PROTECTION)"""
    last = df.iloc[-1]
    
    price = last['close']
    ema200 = last['ema200']
    rsi = last['rsi']
    adx = last['adx']
    vol = last['volume']
    vol_avg = last['vol_ma']
    
    trend = "HAUSSIER" if price > ema200 else "BAISSIER"
    is_green = last['close'] > last['open']
    is_volume_ok = vol > vol_avg if vol_avg > 0 else True
    is_market_active = adx > 20
    
    signal = "NEUTRE"

    if (trend == "HAUSSIER" and rsi < 45 and is_green and is_market_active and is_volume_ok):
        signal = "LONG"
    elif (trend == "BAISSIER" and rsi > 55 and not is_green and is_market_active and is_volume_ok):
        signal = "SHORT"

    atr = last['atr']
    lowest_low = df['low'].tail(10).min()
    highest_high = df['high'].tail(10).max()
    
    sl_price, tp_price = 0.0, 0.0
    
    if signal == "LONG":
        sl_price = lowest_low - (atr * 0.2)
        risk = price - sl_price
        tp_price = price + (risk * 2.0)
    elif signal == "SHORT":
        sl_price = highest_high + (atr * 0.2)
        risk = sl_price - price
        tp_price = price - (risk * 2.0)
        
    return {
        "price": price, 
        "signal": signal, 
        "trend": trend,
        "rsi": round(rsi, 2), 
        "adx": round(adx, 2),
        "sl": round(sl_price, 2), 
        "tp": round(tp_price, 2),
        "vol_ok": is_volume_ok
    }

# --- IA : VALIDATION & CHAT ---

def safe_string(text):
    """Convertit le texte en string safe pour l'encodage."""
    if text is None:
        return ""
    try:
        if isinstance(text, bytes):
            return text.decode('utf-8', errors='ignore')
        return str(text)
    except:
        return str(text).encode('ascii', errors='ignore').decode('ascii')

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
    
    Si le volume est faible, sois mefiant.
    Reponds UNIQUEMENT ce JSON (rien d'autre) :
    {{"score": 85, "raison": "Rebond technique valide sur support haussier."}}
    """
    try:
        comp = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], 
            model=MODEL_NAME,
            temperature=0.1
        )
        
        raw = safe_string(comp.choices[0].message.content)
        raw = raw.replace('```json', '').replace('```', '').strip()
        
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        
        result = json.loads(raw)
        
        if 'score' not in result:
            result['score'] = 50
        if 'raison' not in result:
            result['raison'] = "Analyse IA incomplete"
            
        result['score'] = int(result['score'])
        result['raison'] = safe_string(result['raison'])
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"Erreur parsing JSON IA: {e}")
        return {"score": 50, "raison": "Reponse IA non parseable"}
    except Exception as e:
        print(f"Erreur validation IA: {e}")
        return None

def chat_with_ai(user_id, message):
    """Discussion naturelle avec memoire."""
    history = get_history(user_id)
    
    system_prompt = {
        "role": "system", 
        "content": "Tu es un assistant Trading Crypto expert. Tu es concis, precis et pedagogue. Tu parles francais."
    }
    
    messages = [system_prompt] + history + [{"role": "user", "content": safe_string(message)}]
    
    try:
        response = client.chat.completions.create(
            messages=messages, 
            model=MODEL_NAME,
            temperature=0.7
        )
        reply = safe_string(response.choices[0].message.content)
        
        update_history(user_id, "user", safe_string(message))
        update_history(user_id, "assistant", reply)
        
        return reply
    except Exception as e:
        error_msg = safe_string(str(e))
        print(f"Erreur Chat IA: {error_msg}")
        return f"Erreur IA: {error_msg}"

# --- HANDLERS TELEGRAM ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    msg = "Bot Sniper Connecte!\n\nCommandes:\n- /analyse - Forcer une analyse\n- /status - Voir le status\n- Message libre - Discuter avec l'IA\n\nJe surveille le BTC automatiquement."
    bot.reply_to(message, msg)

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    analyze_market(manual_trigger=True, chat_id=message.chat.id)

@bot.message_handler(commands=['status'])
def send_status(message):
    try:
        df = get_binance_data()
        if df is not None:
            df = calculate_indicators(df)
            last = df.iloc[-1]
            msg = (
                f"Status Bot\n\n"
                f"Prix BTC: ${last['close']:,.2f}\n"
                f"RSI: {last['rsi']:.2f}\n"
                f"ADX: {last['adx']:.2f}\n"
                f"EMA200: ${last['ema200']:,.2f}\n"
                f"ATR: ${last['atr']:.2f}\n"
                f"Volume OK: {last['volume'] > last['vol_ma']}"
            )
            bot.reply_to(message, msg)
        else:
            bot.reply_to(message, "Erreur recuperation donnees Binance")
    except Exception as e:
        bot.reply_to(message, f"Erreur: {safe_string(str(e))}")

@bot.message_handler(func=lambda message: True)
def handle_chat(message):
    """Gere le chat libre avec l'IA."""
    bot.send_chat_action(message.chat.id, 'typing')
    reply = chat_with_ai(message.from_user.id, message.text)
    bot.reply_to(message, reply)

# --- LOGIQUE PRINCIPALE ---

def analyze_market(manual_trigger=False, chat_id=None):
    """Analyse le marche et envoie un signal si pertinent."""
    
    target_chat = chat_id or TG_CHAT_ID
    if not target_chat: 
        print("Pas de chat_id configure")
        return

    df = get_binance_data()
    if df is None: 
        if manual_trigger:
            bot.send_message(target_chat, "Erreur recuperation donnees Binance")
        return

    df = calculate_indicators(df)
    data = sniper_logic(df)
    
    if data['signal'] == "NEUTRE":
        if manual_trigger:
            msg = (
                f"Pas de signal actuellement\n\n"
                f"Prix: ${data['price']:,.2f}\n"
                f"Tendance: {data['trend']}\n"
                f"RSI: {data['rsi']} | ADX: {data['adx']}\n"
                f"Volume OK: {'Oui' if data['vol_ok'] else 'Non'}"
            )
            bot.send_message(target_chat, msg)
        return

    ai_verdict = ask_ai_validation(data)
    if not ai_verdict: 
        if manual_trigger: 
            bot.send_message(target_chat, "Erreur IA, pas de validation possible.")
        return

    score = ai_verdict['score']
    
    if score < 75:
        if manual_trigger:
            msg = (
                f"Signal detecte mais score trop faible\n\n"
                f"Signal: {data['signal']}\n"
                f"Score: {score}/100 (minimum: 75)\n"
                f"Raison: {ai_verdict['raison']}"
            )
            bot.send_message(target_chat, msg)
        return

    entry = data['price']
    
    if entry > 0:
        tp_pct = round(((data['tp'] - entry) / entry) * 100, 2)
        sl_pct = round(((data['sl'] - entry) / entry) * 100, 2)
    else:
        tp_pct, sl_pct = 0, 0
    
    emoji = "LONG" if data['signal'] == "LONG" else "SHORT"
    
    msg = (
        f"SIGNAL {emoji} SNIPER\n\n"
        f"Prix Entree: ${entry:,.2f}\n"
        f"TP: ${data['tp']:,.2f} ({tp_pct:+}%)\n"
        f"SL: ${data['sl']:,.2f} ({sl_pct:+}%)\n\n"
        f"Score IA: {score}/100\n"
        f"Analyse: {ai_verdict['raison']}\n\n"
        f"RSI: {data['rsi']} | ADX: {data['adx']}\n"
        f"Tendance: {data['trend']} | Vol: {'Oui' if data['vol_ok'] else 'Non'}"
    )
    
    bot.send_message(target_chat, msg)
    print(f"Signal {data['signal']} envoye - Score: {score}")

# --- LANCEMENT ---

@app.route('/')
def home(): 
    return "Sniper Bot Active - Trading BTC/USDT"

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}

def run_loop():
    print("Boucle d'analyse demarree (intervalle: 15min)")
    while True:
        try:
            analyze_market()
            time.sleep(900)
        except Exception as e:
            print(f"Erreur boucle: {safe_string(str(e))}")
            time.sleep(60)

def run_bot():
    print("Bot Telegram demarre")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"Erreur Bot Telegram: {safe_string(str(e))}")
            time.sleep(10)

if __name__ == "__main__":
    print("=" * 50)
    print("SNIPER BOT - Demarrage")
    print("=" * 50)
    
    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur Flask sur port {port}")
    app.run(host='0.0.0.0', port=port)
