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
from flask import Flask

# --- CONFIGURATION ---
os.environ['PYTHONIOENCODING'] = 'utf-8'

TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

if not all([TG_TOKEN, TG_CHAT_ID]):
    print("ERREUR: Variables manquantes!")
    sys.exit(1)

app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- TRADES ACTIFS ET HISTORIQUE ---
active_trades = []  # Trades en cours
trade_history = []  # Trades termines

# --- CONFIGURATION TRADING ---
RISK_PERCENT = 1.0  # Risque par trade (fictif)
STARTING_BALANCE = 10000  # Balance demo fictive
current_balance = STARTING_BALANCE

# --- FONCTIONS PRIX ---

def get_btc_price():
    """Recupere le prix BTC actuel."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        resp = requests.get(url, timeout=10).json()
        return float(resp['price'])
    except:
        return None

def get_btc_data():
    """Recupere les bougies BTC."""
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=50"
        resp = requests.get(url, timeout=10).json()
        
        df = pd.DataFrame(resp, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['open'] = df['open'].astype(float)
        return df
    except Exception as e:
        print(f"Erreur: {e}")
        return None

def calculate_rsi(df, period=14):
    """Calcule le RSI."""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 1)

# --- GESTION DES TRADES ---

def open_trade(signal_type, entry_price, sl_price, tp_price, rsi):
    """Ouvre un nouveau trade."""
    global active_trades
    
    trade_id = len(trade_history) + len(active_trades) + 1
    
    trade = {
        "id": trade_id,
        "type": signal_type,
        "entry": entry_price,
        "sl": sl_price,
        "tp": tp_price,
        "rsi": rsi,
        "open_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "OPEN"
    }
    
    active_trades.append(trade)
    return trade

def check_active_trades():
    """Verifie si les trades actifs ont touche TP ou SL."""
    global active_trades, trade_history, current_balance
    
    if not active_trades:
        return []
    
    current_price = get_btc_price()
    if current_price is None:
        return []
    
    closed_trades = []
    
    for trade in active_trades[:]:  # Copie pour iteration
        
        result = None
        
        if trade['type'] == "LONG":
            if current_price >= trade['tp']:
                result = "WIN"
            elif current_price <= trade['sl']:
                result = "LOSS"
                
        elif trade['type'] == "SHORT":
            if current_price <= trade['tp']:
                result = "WIN"
            elif current_price >= trade['sl']:
                result = "LOSS"
        
        if result:
            # Fermer le trade
            trade['status'] = result
            trade['close_time'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            trade['close_price'] = current_price
            
            # Calculer profit/perte
            if trade['type'] == "LONG":
                pnl_pct = ((current_price - trade['entry']) / trade['entry']) * 100
            else:
                pnl_pct = ((trade['entry'] - current_price) / trade['entry']) * 100
            
            trade['pnl_pct'] = round(pnl_pct, 2)
            
            # Mettre a jour balance
            pnl_amount = current_balance * (pnl_pct / 100)
            current_balance += pnl_amount
            trade['balance_after'] = round(current_balance, 2)
            
            # Deplacer vers historique
            trade_history.append(trade)
            active_trades.remove(trade)
            closed_trades.append(trade)
    
    return closed_trades

def get_stats():
    """Calcule les statistiques."""
    if not trade_history:
        return None
    
    wins = [t for t in trade_history if t['status'] == "WIN"]
    losses = [t for t in trade_history if t['status'] == "LOSS"]
    
    total_pnl = sum(t['pnl_pct'] for t in trade_history)
    
    return {
        "total": len(trade_history),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(len(wins) / len(trade_history) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "balance": round(current_balance, 2),
        "gain_pct": round(((current_balance - STARTING_BALANCE) / STARTING_BALANCE) * 100, 2)
    }

# --- LOGIQUE DE SIGNAL ---

def check_for_signal(df):
    """Verifie si un signal est present."""
    
    # Pas de nouveau signal si trade deja ouvert
    if active_trades:
        return None
    
    rsi = calculate_rsi(df)
    price = df['close'].iloc[-1]
    
    # ATR pour SL/TP
    high_low = df['high'] - df['low']
    atr = high_low.tail(14).mean()
    
    signal = None
    
    # LONG : RSI < 30
    if rsi < 30:
        sl = price - (atr * 1.5)
        tp = price + (atr * 3.0)  # Ratio 2:1
        
        signal = {
            "type": "LONG",
            "entry": round(price, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "rsi": rsi
        }
    
    # SHORT : RSI > 70
    elif rsi > 70:
        sl = price + (atr * 1.5)
        tp = price - (atr * 3.0)  # Ratio 2:1
        
        signal = {
            "type": "SHORT",
            "entry": round(price, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "rsi": rsi
        }
    
    return signal

# --- COMMANDES TELEGRAM ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    msg = (
        "BOT AUTO-TRACKING\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Ce bot:\n"
        "1. Detecte les signaux (RSI)\n"
        "2. Ouvre des trades fictifs\n"
        "3. Surveille TP/SL automatiquement\n"
        "4. Calcule ton winrate reel\n\n"
        "Commandes:\n"
        "/status - Prix et RSI actuel\n"
        "/trades - Trades en cours\n"
        "/stats - Tes statistiques\n"
        "/history - Historique\n"
        "/reset - Reinitialiser\n\n"
        "Balance demo: $10,000"
    )
    bot.reply_to(message, msg)

@bot.message_handler(commands=['status'])
def send_status(message):
    df = get_btc_data()
    if df is None:
        bot.reply_to(message, "Erreur Binance")
        return
    
    price = df['close'].iloc[-1]
    rsi = calculate_rsi(df)
    now = datetime.datetime.now().strftime("%H:%M")
    
    active = len(active_trades)
    
    msg = (
        f"[{now}] STATUS\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Prix BTC: ${price:,.2f}\n"
        f"RSI: {rsi}\n\n"
        f"Trades actifs: {active}\n"
        f"Balance: ${current_balance:,.2f}"
    )
    bot.reply_to(message, msg)

@bot.message_handler(commands=['trades'])
def send_trades(message):
    if not active_trades:
        bot.reply_to(message, "Aucun trade en cours.")
        return
    
    msg = "TRADES EN COURS\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    current_price = get_btc_price()
    
    for trade in active_trades:
        # Calculer PnL actuel
        if trade['type'] == "LONG":
            pnl = ((current_price - trade['entry']) / trade['entry']) * 100
        else:
            pnl = ((trade['entry'] - current_price) / trade['entry']) * 100
        
        emoji = "🟢" if pnl > 0 else "🔴"
        
        msg += (
            f"#{trade['id']} | {trade['type']}\n"
            f"   Entry: ${trade['entry']:,.2f}\n"
            f"   SL: ${trade['sl']:,.2f}\n"
            f"   TP: ${trade['tp']:,.2f}\n"
            f"   {emoji} PnL: {pnl:+.2f}%\n\n"
        )
    
    msg += f"Prix actuel: ${current_price:,.2f}"
    bot.reply_to(message, msg)

@bot.message_handler(commands=['stats'])
def send_stats(message):
    stats = get_stats()
    
    if not stats:
        msg = (
            "STATISTIQUES\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Aucun trade termine.\n"
            "Attends que TP ou SL soit touche."
        )
        bot.reply_to(message, msg)
        return
    
    msg = (
        "STATISTIQUES\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Trades termines: {stats['total']}\n\n"
        f"Gagnes: {stats['wins']}\n"
        f"Perdus: {stats['losses']}\n\n"
        f"WINRATE: {stats['winrate']}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"PnL Total: {stats['total_pnl']:+.2f}%\n"
        f"Balance: ${stats['balance']:,.2f}\n"
        f"Gain: {stats['gain_pct']:+.2f}%\n\n"
        f"(Demo $10,000 initial)"
    )
    bot.reply_to(message, msg)

@bot.message_handler(commands=['history'])
def send_history(message):
    if not trade_history:
        bot.reply_to(message, "Aucun trade dans l'historique.")
        return
    
    msg = "HISTORIQUE\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # 10 derniers trades
    for trade in trade_history[-10:]:
        emoji = "✅" if trade['status'] == "WIN" else "❌"
        
        msg += (
            f"{emoji} #{trade['id']} | {trade['type']}\n"
            f"   {trade['open_time']}\n"
            f"   Entry: ${trade['entry']:,.0f}\n"
            f"   PnL: {trade['pnl_pct']:+.2f}%\n\n"
        )
    
    bot.reply_to(message, msg)

@bot.message_handler(commands=['reset'])
def reset_stats(message):
    global active_trades, trade_history, current_balance
    active_trades = []
    trade_history = []
    current_balance = STARTING_BALANCE
    bot.reply_to(message, "Stats reinitialises.\nBalance: $10,000")

# --- BOUCLE PRINCIPALE ---

def main_loop():
    """Boucle principale : signaux + surveillance."""
    
    print("Bot demarre...")
    
    try:
        bot.send_message(TG_CHAT_ID, 
            "BOT AUTO-TRACKING DEMARRE\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Balance demo: $10,000\n"
            "Ratio: 2:1 (TP = 2x SL)\n\n"
            "Je detecte les signaux et\n"
            "surveille TP/SL automatiquement.\n\n"
            "Commandes: /stats /trades"
        )
    except:
        pass
    
    while True:
        try:
            now = datetime.datetime.now().strftime("%H:%M")
            
            # 1. Verifier les trades actifs
            closed = check_active_trades()
            
            for trade in closed:
                emoji = "✅ WIN" if trade['status'] == "WIN" else "❌ LOSS"
                
                msg = (
                    f"[{now}] TRADE FERME\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"#{trade['id']} | {trade['type']}\n"
                    f"Resultat: {emoji}\n\n"
                    f"Entry: ${trade['entry']:,.2f}\n"
                    f"Close: ${trade['close_price']:,.2f}\n"
                    f"PnL: {trade['pnl_pct']:+.2f}%\n\n"
                    f"Balance: ${trade['balance_after']:,.2f}\n\n"
                    f"Voir stats: /stats"
                )
                bot.send_message(TG_CHAT_ID, msg)
            
            # 2. Chercher nouveau signal (si pas de trade actif)
            if not active_trades:
                df = get_btc_data()
                if df is not None:
                    signal = check_for_signal(df)
                    
                    if signal:
                        # Ouvrir le trade
                        trade = open_trade(
                            signal['type'],
                            signal['entry'],
                            signal['sl'],
                            signal['tp'],
                            signal['rsi']
                        )
                        
                        tp_pct = abs((signal['tp'] - signal['entry']) / signal['entry'] * 100)
                        sl_pct = abs((signal['sl'] - signal['entry']) / signal['entry'] * 100)
                        
                        emoji = "🟢 LONG" if signal['type'] == "LONG" else "🔴 SHORT"
                        
                        msg = (
                            f"[{now}] NOUVEAU TRADE\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"#{trade['id']} | {emoji}\n\n"
                            f"Entry: ${signal['entry']:,.2f}\n"
                            f"TP: ${signal['tp']:,.2f} (+{tp_pct:.2f}%)\n"
                            f"SL: ${signal['sl']:,.2f} (-{sl_pct:.2f}%)\n\n"
                            f"RSI: {signal['rsi']}\n"
                            f"Ratio: 2:1\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"Surveillance auto activee.\n"
                            f"Je t'alerte quand TP ou SL touche."
                        )
                        bot.send_message(TG_CHAT_ID, msg)
            
            # Attendre 1 minute avant prochaine verification
            time.sleep(60)
            
        except Exception as e:
            print(f"Erreur: {e}")
            time.sleep(30)

def run_bot():
    """Lance le bot Telegram."""
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"Erreur Telegram: {e}")
            time.sleep(10)

# --- LANCEMENT ---

@app.route('/')
def home():
    return "Bot Auto-Tracking Actif"

@app.route('/health')
def health():
    stats = get_stats()
    return {
        "status": "ok",
        "active_trades": len(active_trades),
        "total_trades": len(trade_history),
        "balance": current_balance
    }

if __name__ == "__main__":
    print("=" * 40)
    print("BOT AUTO-TRACKING")
    print("=" * 40)
    
    threading.Thread(target=main_loop, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
