import os
import sys
import time
import threading
import datetime
import requests
import json
import telebot
import pandas as pd
import numpy as np
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

if not all([GROQ_API_KEY, TG_TOKEN, TG_CHAT_ID]):
    print("ERREUR: Variables d'environnement manquantes!")
    sys.exit(1)

client = Groq(api_key=GROQ_API_KEY)
app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

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
    except Exception as e:
        print(f"Erreur Data: {e}")
        return None

def calculate_indicators(df):
    """Calcule les indicateurs techniques."""
    
    # RSI (14)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi'] = df['rsi'].fillna(50)

    # EMA 20 et EMA 50 (plus reactifs que EMA 200)
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = true_range.rolling(14).mean()

    # Volume Moyen
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # Nettoyer
    df = df.bfill().ffill().fillna(0)

    return df

def sniper_logic(df):
    """
    LOGIQUE SNIPER ASSOUPLIE - Plus de signaux !
    """
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    price = last['close']
    ema20 = last['ema20']
    ema50 = last['ema50']
    rsi = last['rsi']
    vol = last['volume']
    vol_avg = last['vol_ma']
    atr = last['atr']
    
    # Tendance basee sur EMA 20/50 (plus reactif)
    trend = "HAUSSIER" if ema20 > ema50 else "BAISSIER"
    
    # Bougie actuelle
    is_green = last['close'] > last['open']
    
    # Volume (optionnel maintenant)
    is_volume_ok = vol > (vol_avg * 0.8) if vol_avg > 0 else True  # 80% suffit
    
    signal = "NEUTRE"
    raison = ""

    # ========== CONDITIONS LONG (ACHAT) ==========
    # Option 1: RSI survente + rebond
    if rsi < 35 and is_green:
        signal = "LONG"
        raison = f"RSI survente ({rsi:.1f}) + bougie verte"
    
    # Option 2: RSI remonte de survente
    elif prev['rsi'] < 30 and rsi > 30 and rsi < 50:
        signal = "LONG"
        raison = f"RSI sort de survente ({prev['rsi']:.1f} -> {rsi:.1f})"
    
    # Option 3: Prix rebondit sur EMA20 en tendance haussiere
    elif trend == "HAUSSIER" and price > ema20 and prev['close'] < prev['ema20'] and is_green:
        signal = "LONG"
        raison = f"Rebond sur EMA20 en tendance haussiere"
    
    # Option 4: Croisement EMA haussier
    elif prev['ema20'] < prev['ema50'] and ema20 > ema50:
        signal = "LONG"
        raison = f"Croisement EMA20/EMA50 haussier"
    
    # Option 5: RSI momentum haussier
    elif trend == "HAUSSIER" and 40 < rsi < 60 and is_green and is_volume_ok:
        signal = "LONG"
        raison = f"Momentum haussier (RSI: {rsi:.1f}, Volume OK)"

    # ========== CONDITIONS SHORT (VENTE) ==========
    # Option 1: RSI surachat + rejet
    elif rsi > 65 and not is_green:
        signal = "SHORT"
        raison = f"RSI surachat ({rsi:.1f}) + bougie rouge"
    
    # Option 2: RSI descend de surachat
    elif prev['rsi'] > 70 and rsi < 70 and rsi > 50:
        signal = "SHORT"
        raison = f"RSI sort de surachat ({prev['rsi']:.1f} -> {rsi:.1f})"
    
    # Option 3: Prix rejette EMA20 en tendance baissiere
    elif trend == "BAISSIER" and price < ema20 and prev['close'] > prev['ema20'] and not is_green:
        signal = "SHORT"
        raison = f"Rejet sur EMA20 en tendance baissiere"
    
    # Option 4: Croisement EMA baissier
    elif prev['ema20'] > prev['ema50'] and ema20 < ema50:
        signal = "SHORT"
        raison = f"Croisement EMA20/EMA50 baissier"
    
    # Option 5: RSI momentum baissier
    elif trend == "BAISSIER" and 40 < rsi < 60 and not is_green and is_volume_ok:
        signal = "SHORT"
        raison = f"Momentum baissier (RSI: {rsi:.1f}, Volume OK)"

    # ========== CALCUL SL / TP ==========
    lowest_low = df['low'].tail(10).min()
    highest_high = df['high'].tail(10).max()
    
    sl_price, tp_price = 0.0, 0.0
    
    if signal == "LONG":
        sl_price = lowest_low - (atr * 0.3)
        risk = price - sl_price
        tp_price = price + (risk * 2.0)
    elif signal == "SHORT":
        sl_price = highest_high + (atr * 0.3)
        risk = sl_price - price
        tp_price = price - (risk * 2.0)
        
    return {
        "price": price, 
        "signal": signal, 
        "trend": trend,
        "rsi": round(rsi, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "sl": round(sl_price, 2), 
        "tp": round(tp_price, 2),
        "vol_ok": is_volume_ok,
        "raison": raison
    }

# --- IA : VALIDATION ---

def safe_string(text):
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
    Tu es un trader crypto expert. Analyse ce signal:
    
    - Prix BTC: ${data['price']}
    - Signal: {data['signal']}
    - Raison: {data['raison']}
    - Tendance: {data['trend']}
    - RSI: {data['rsi']}
    - EMA20: ${data['ema20']} | EMA50: ${data['ema50']}
    
    Donne un score de 0 a 100 pour ce signal.
    Reponds UNIQUEMENT en JSON:
    {{"score": 75, "raison": "Ton analyse courte ici"}}
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
        result['score'] = int(result.get('score', 50))
        result['raison'] = safe_string(result.get('raison', 'Pas de raison'))
        
        return result
        
    except Exception as e:
        print(f"Erreur IA: {e}")
        return {"score": 60, "raison": "Validation IA indisponible"}

# --- HANDLERS TELEGRAM ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    msg = (
        "Bot Sniper v2.0 Connecte!\n\n"
        "Nouveautes:\n"
        "- Conditions assouplies = plus de signaux\n"
        "- EMA 20/50 au lieu de EMA 200\n"
        "- Detection survente/surachat\n\n"
        "Commandes:\n"
        "/analyse - Analyse immediate\n"
        "/status - Status actuel\n\n"
        "Rapport automatique toutes les 25 min"
    )
    bot.reply_to(message, msg)

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    bot.reply_to(message, "Analyse en cours...")
    analyze_market(manual_trigger=True, chat_id=message.chat.id)

@bot.message_handler(commands=['status'])
def send_status(message):
    try:
        df = get_binance_data()
        if df is not None:
            df = calculate_indicators(df)
            last = df.iloc[-1]
            now = datetime.datetime.now().strftime("%H:%M:%S")
            
            trend = "HAUSSIER" if last['ema20'] > last['ema50'] else "BAISSIER"
            
            msg = (
                f"[{now}] Status Detaille\n\n"
                f"Prix BTC: ${last['close']:,.2f}\n"
                f"Tendance: {trend}\n\n"
                f"RSI: {last['rsi']:.1f}\n"
                f"  < 30 = Survente (LONG)\n"
                f"  > 70 = Surachat (SHORT)\n\n"
                f"EMA20: ${last['ema20']:,.2f}\n"
                f"EMA50: ${last['ema50']:,.2f}\n"
                f"ATR: ${last['atr']:.2f}\n\n"
                f"Volume OK: {'Oui' if last['volume'] > last['vol_ma']*0.8 else 'Non'}"
            )
            bot.reply_to(message, msg)
        else:
            bot.reply_to(message, "Erreur Binance")
    except Exception as e:
        bot.reply_to(message, f"Erreur: {e}")

# --- LOGIQUE PRINCIPALE ---

def analyze_market(manual_trigger=False, chat_id=None):
    """Analyse et envoie rapport."""
    
    target_chat = chat_id or TG_CHAT_ID
    if not target_chat: 
        return

    now = datetime.datetime.now().strftime("%H:%M:%S")
    
    df = get_binance_data()
    if df is None: 
        bot.send_message(target_chat, f"[{now}] Erreur Binance")
        return

    df = calculate_indicators(df)
    data = sniper_logic(df)
    
    # PAS DE SIGNAL
    if data['signal'] == "NEUTRE":
        msg = (
            f"[{now}] Analyse terminee\n\n"
            f"Prix: ${data['price']:,.2f}\n"
            f"Tendance: {data['trend']}\n"
            f"RSI: {data['rsi']}\n"
            f"EMA20: ${data['ema20']:,.2f}\n"
            f"EMA50: ${data['ema50']:,.2f}\n\n"
            f"Signal: AUCUN\n"
            f"En attente de setup...\n\n"
            f"Prochaine analyse: 25 min"
        )
        bot.send_message(target_chat, msg)
        print(f"[{now}] Pas de signal - RSI: {data['rsi']}")
        return

    # SIGNAL DETECTE !
    ai_verdict = ask_ai_validation(data)
    score = ai_verdict['score']
    
    # Score minimum abaisse a 60
    if score < 60:
        msg = (
            f"[{now}] Signal faible\n\n"
            f"Type: {data['signal']}\n"
            f"Raison: {data['raison']}\n"
            f"Score IA: {score}/100\n\n"
            f"Action: ATTENDRE\n"
            f"Prochaine analyse: 25 min"
        )
        bot.send_message(target_chat, msg)
        return

    # BON SIGNAL !
    entry = data['price']
    tp_pct = round(((data['tp'] - entry) / entry) * 100, 2) if entry > 0 else 0
    sl_pct = round(((data['sl'] - entry) / entry) * 100, 2) if entry > 0 else 0
    
    emoji = "LONG (ACHAT)" if data['signal'] == "LONG" else "SHORT (VENTE)"
    
    msg = (
        f"[{now}] SIGNAL DETECTE !\n\n"
        f"Type: {emoji}\n"
        f"Raison: {data['raison']}\n\n"
        f"Entree: ${entry:,.2f}\n"
        f"TP: ${data['tp']:,.2f} ({tp_pct:+}%)\n"
        f"SL: ${data['sl']:,.2f} ({sl_pct:+}%)\n\n"
        f"Score IA: {score}/100\n"
        f"IA: {ai_verdict['raison']}\n\n"
        f"RSI: {data['rsi']} | Tendance: {data['trend']}\n"
        f"Prochaine analyse: 25 min"
    )
    
    bot.send_message(target_chat, msg)
    print(f"[{now}] SIGNAL {data['signal']} - Score: {score}")

# --- LANCEMENT ---

@app.route('/')
def home(): 
    return "Sniper Bot v2.0 Active"

@app.route('/health')
def health():
    return {"status": "healthy"}

def run_loop():
    print("Boucle demarree (25 min)")
    
    try:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        bot.send_message(TG_CHAT_ID, f"[{now}] Bot v2.0 demarre!\n\nConditions assouplies pour plus de signaux.")
    except:
        pass
    
    while True:
        try:
            analyze_market()
            time.sleep(1500)  # 25 min
        except Exception as e:
            print(f"Erreur: {e}")
            time.sleep(60)

def run_bot():
    print("Telegram Bot demarre")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"Erreur Telegram: {e}")
            time.sleep(10)

if __name__ == "__main__":
    print("=" * 50)
    print("SNIPER BOT v2.0 - Demarrage")
    print("=" * 50)
    
    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"Flask sur port {port}")
    app.run(host='0.0.0.0', port=port)
