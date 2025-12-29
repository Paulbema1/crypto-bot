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

# --- FORCER UTF-8 ---
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

# --- ANTI-SPAM : Cooldown entre signaux ---
last_signal_time = None
SIGNAL_COOLDOWN = 3600  # 1 heure minimum entre chaque signal

def can_send_signal():
    """Verifie si on peut envoyer un signal (cooldown)."""
    global last_signal_time
    if last_signal_time is None:
        return True
    elapsed = time.time() - last_signal_time
    return elapsed >= SIGNAL_COOLDOWN

def mark_signal_sent():
    """Marque qu'un signal a ete envoye."""
    global last_signal_time
    last_signal_time = time.time()

def get_cooldown_remaining():
    """Retourne le temps restant avant prochain signal possible."""
    global last_signal_time
    if last_signal_time is None:
        return 0
    elapsed = time.time() - last_signal_time
    remaining = SIGNAL_COOLDOWN - elapsed
    return max(0, int(remaining / 60))  # en minutes

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

    # EMA 20, 50, 200
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = true_range.rolling(14).mean()

    # Volume
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # Nettoyer
    df = df.bfill().ffill().fillna(0)

    return df

def sniper_logic(df):
    """
    LOGIQUE SNIPER v3.0 - EQUILIBREE
    Moins de signaux mais meilleure qualite
    """
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    price = last['close']
    ema20 = last['ema20']
    ema50 = last['ema50']
    ema200 = last['ema200']
    rsi = last['rsi']
    vol = last['volume']
    vol_avg = last['vol_ma']
    atr = last['atr']
    
    # Tendance FORTE (prix au-dessus des 3 EMA)
    trend_strong_bull = price > ema20 > ema50 > ema200
    trend_strong_bear = price < ema20 < ema50 < ema200
    
    # Tendance simple
    trend = "HAUSSIER" if ema20 > ema50 else "BAISSIER"
    
    # Bougie
    is_green = last['close'] > last['open']
    body_size = abs(last['close'] - last['open'])
    avg_body = abs(df['close'] - df['open']).tail(20).mean()
    is_strong_candle = body_size > avg_body * 1.2  # Bougie 20% plus grande que moyenne
    
    # Volume FORT (pas juste OK)
    is_volume_strong = vol > (vol_avg * 1.2) if vol_avg > 0 else False
    
    signal = "NEUTRE"
    raison = ""
    force = 0  # Score de force du signal (0-100)

    # ========== LONG : Conditions strictes ==========
    if trend == "HAUSSIER":
        
        # Signal FORT : RSI survente extreme + bougie verte forte + volume
        if rsi < 30 and is_green and is_strong_candle and is_volume_strong:
            signal = "LONG"
            raison = f"RSI survente ({rsi:.1f}) + bougie forte + volume"
            force = 85
        
        # Signal MOYEN : RSI sort de survente avec confirmation
        elif prev['rsi'] < 30 and rsi > 32 and rsi < 45 and is_green:
            signal = "LONG"
            raison = f"RSI sort de survente ({prev['rsi']:.1f} -> {rsi:.1f})"
            force = 75
        
        # Signal MOYEN : Rebond sur EMA20 en tendance forte
        elif trend_strong_bull and price > ema20 and prev['low'] < prev['ema20'] and is_green and is_volume_strong:
            signal = "LONG"
            raison = f"Rebond EMA20 en tendance forte"
            force = 80

    # ========== SHORT : Conditions strictes ==========
    elif trend == "BAISSIER":
        
        # Signal FORT : RSI surachat extreme + bougie rouge forte + volume
        if rsi > 70 and not is_green and is_strong_candle and is_volume_strong:
            signal = "SHORT"
            raison = f"RSI surachat ({rsi:.1f}) + bougie forte + volume"
            force = 85
        
        # Signal MOYEN : RSI sort de surachat avec confirmation
        elif prev['rsi'] > 70 and rsi < 68 and rsi > 55 and not is_green:
            signal = "SHORT"
            raison = f"RSI sort de surachat ({prev['rsi']:.1f} -> {rsi:.1f})"
            force = 75
        
        # Signal MOYEN : Rejet sur EMA20 en tendance forte
        elif trend_strong_bear and price < ema20 and prev['high'] > prev['ema20'] and not is_green and is_volume_strong:
            signal = "SHORT"
            raison = f"Rejet EMA20 en tendance forte"
            force = 80

    # ========== SIGNAUX EXTREMES (tres rares) ==========
    if signal == "NEUTRE":
        # RSI < 20 = TRES survente = LONG peu importe la tendance
        if rsi < 20 and is_green:
            signal = "LONG"
            raison = f"RSI EXTREME ({rsi:.1f}) - Survente majeure"
            force = 90
        
        # RSI > 85 = TRES surachat = SHORT peu importe la tendance
        elif rsi > 85 and not is_green:
            signal = "SHORT"
            raison = f"RSI EXTREME ({rsi:.1f}) - Surachat majeur"
            force = 90

    # ========== CALCUL SL / TP ==========
    lowest_low = df['low'].tail(15).min()
    highest_high = df['high'].tail(15).max()
    
    sl_price, tp_price = 0.0, 0.0
    
    if signal == "LONG":
        sl_price = lowest_low - (atr * 0.5)
        risk = price - sl_price
        tp_price = price + (risk * 2.5)  # Ratio 2.5:1
    elif signal == "SHORT":
        sl_price = highest_high + (atr * 0.5)
        risk = sl_price - price
        tp_price = price - (risk * 2.5)  # Ratio 2.5:1
        
    return {
        "price": price, 
        "signal": signal, 
        "trend": trend,
        "rsi": round(rsi, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "sl": round(sl_price, 2), 
        "tp": round(tp_price, 2),
        "vol_ok": is_volume_strong,
        "raison": raison,
        "force": force
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
    Tu es un trader crypto professionnel tres strict.
    Analyse ce signal et donne un score REALISTE:
    
    - Prix BTC: ${data['price']}
    - Signal: {data['signal']}
    - Raison: {data['raison']}
    - Force calculee: {data['force']}/100
    - Tendance: {data['trend']}
    - RSI: {data['rsi']}
    - Volume fort: {data['vol_ok']}
    
    IMPORTANT: Sois STRICT. Un signal moyen = score 50-65. Bon signal = 70-80. Excellent = 85+.
    
    Reponds UNIQUEMENT en JSON:
    {{"score": 70, "raison": "Analyse courte"}}
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
        # Si IA indisponible, utiliser le score de force calcule
        return {"score": data.get('force', 50), "raison": "Score base sur analyse technique"}

# --- HANDLERS TELEGRAM ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    msg = (
        "Bot Sniper v3.0 - EQUILIBRE\n\n"
        "Nouveautes:\n"
        "- Moins de signaux, meilleure qualite\n"
        "- Cooldown 1h entre signaux\n"
        "- Conditions plus strictes\n"
        "- Score minimum: 70/100\n\n"
        "Commandes:\n"
        "/analyse - Analyse immediate\n"
        "/status - Status actuel\n\n"
        "Rapport toutes les 25 min"
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
            cooldown = get_cooldown_remaining()
            
            msg = (
                f"[{now}] Status\n\n"
                f"Prix: ${last['close']:,.2f}\n"
                f"Tendance: {trend}\n"
                f"RSI: {last['rsi']:.1f}\n\n"
                f"EMA20: ${last['ema20']:,.2f}\n"
                f"EMA50: ${last['ema50']:,.2f}\n\n"
                f"Cooldown: {cooldown} min restantes" if cooldown > 0 else f"Cooldown: Pret pour signal"
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
    
    cooldown_remaining = get_cooldown_remaining()
    
    # PAS DE SIGNAL
    if data['signal'] == "NEUTRE":
        msg = (
            f"[{now}] Analyse terminee\n\n"
            f"Prix: ${data['price']:,.2f}\n"
            f"Tendance: {data['trend']}\n"
            f"RSI: {data['rsi']}\n\n"
            f"Signal: AUCUN\n"
            f"Cooldown: {cooldown_remaining} min" if cooldown_remaining > 0 else f"Pret pour signal\n"
            f"\nProchaine analyse: 25 min"
        )
        bot.send_message(target_chat, msg)
        print(f"[{now}] Pas de signal")
        return

    # SIGNAL DETECTE - Verifier cooldown
    if not can_send_signal() and not manual_trigger:
        msg = (
            f"[{now}] Signal ignore (cooldown)\n\n"
            f"Type: {data['signal']}\n"
            f"Raison: {data['raison']}\n\n"
            f"Cooldown restant: {cooldown_remaining} min\n"
            f"Prochaine analyse: 25 min"
        )
        bot.send_message(target_chat, msg)
        print(f"[{now}] Signal ignore - Cooldown")
        return

    # Validation IA
    ai_verdict = ask_ai_validation(data)
    score = ai_verdict['score']
    
    # Score minimum: 70
    if score < 70:
        msg = (
            f"[{now}] Signal rejete\n\n"
            f"Type: {data['signal']}\n"
            f"Raison: {data['raison']}\n"
            f"Score: {score}/100 (min: 70)\n\n"
            f"Action: ATTENDRE\n"
            f"Prochaine analyse: 25 min"
        )
        bot.send_message(target_chat, msg)
        print(f"[{now}] Signal rejete - Score: {score}")
        return

    # BON SIGNAL !
    mark_signal_sent()  # Active le cooldown
    
    entry = data['price']
    tp_pct = round(((data['tp'] - entry) / entry) * 100, 2) if entry > 0 else 0
    sl_pct = round(((data['sl'] - entry) / entry) * 100, 2) if entry > 0 else 0
    
    emoji = "LONG (ACHAT)" if data['signal'] == "LONG" else "SHORT (VENTE)"
    
    msg = (
        f"[{now}] SIGNAL VALIDE !\n\n"
        f"Type: {emoji}\n"
        f"Raison: {data['raison']}\n\n"
        f"Entree: ${entry:,.2f}\n"
        f"TP: ${data['tp']:,.2f} ({tp_pct:+}%)\n"
        f"SL: ${data['sl']:,.2f} ({sl_pct:+}%)\n"
        f"Ratio: 2.5:1\n\n"
        f"Score: {score}/100\n"
        f"IA: {ai_verdict['raison']}\n\n"
        f"Tendance: {data['trend']}\n"
        f"Cooldown: 1h avant prochain signal"
    )
    
    bot.send_message(target_chat, msg)
    print(f"[{now}] SIGNAL {data['signal']} envoye - Score: {score}")

# --- LANCEMENT ---

@app.route('/')
def home(): 
    return "Sniper Bot v3.0 - Equilibre"

@app.route('/health')
def health():
    return {"status": "healthy"}

def run_loop():
    print("Boucle demarree (25 min)")
    
    try:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        bot.send_message(TG_CHAT_ID, f"[{now}] Bot v3.0 demarre!\n\nVersion equilibree - Moins de spam")
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
    print("SNIPER BOT v3.0 - EQUILIBRE")
    print("=" * 50)
    
    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"Flask sur port {port}")
    app.run(host='0.0.0.0', port=port)
