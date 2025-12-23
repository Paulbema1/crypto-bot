import os
import time
import threading
import requests
import json
import telebot
import google.generativeai as genai
from flask import Flask

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get('GEMINI_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Configuration de l'IA
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- OUTILS ---

def get_btc_data():
    """Récupère le prix BTC sur Binance"""
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        resp = requests.get(url, timeout=10).json()
        closes = [float(c[4]) for c in resp]
        return closes
    except:
        return None

def ask_gemini(prompt):
    """Interroge Google Gemini"""
    try:
        if not GEMINI_KEY: return "❌ Erreur: Clé GEMINI manquante."
        
        # Le modèle Flash est rapide et gratuit
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erreur IA: {e}"

# --- TELEGRAM ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Bot Crypto (Gemini) Prêt !\n/prix - Prix actuel\n/analyse - Avis IA")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        bot.reply_to(message, f"💰 BTC : {data[-1]} $")
    else:
        bot.reply_to(message, "❌ Erreur Binance")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.reply_to(message, "⚡ Analyse Gemini Flash en cours...")
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.send_chat_action(message.chat.id, 'typing')
    reply = ask_gemini(f"Tu es un expert crypto. Réponds court : {message.text}")
    bot.reply_to(message, reply)

# --- CŒUR DE L'ANALYSE ---

def analyze_market(manual_trigger=False, chat_target=None):
    target_id = chat_target if manual_trigger else TG_CHAT_ID
    closes = get_btc_data()
    if not closes: return

    current_price = closes[-1]
    
    prompt = f"""
    Agis comme un trader expert. Analyse ces clôtures BTC (15m): {closes[-5:]}.
    Prix actuel: {current_price}.
    
    Réponds UNIQUEMENT avec ce JSON strict (pas de markdown):
    {{
        "action": "ACHAT" ou "VENTE" ou "ATTENTE",
        "conf": 85,
        "raison": "Phrase courte en français"
    }}
    """
    
    raw_res = ask_gemini(prompt)
    # Nettoyage vital pour éviter les erreurs JSON
    clean_res = raw_res.replace('```json', '').replace('```', '').strip()

    try:
        signal = json.loads(clean_res)
        
        if manual_trigger:
            msg = f"🤖 *Analyse*\nAction: {signal['action']}\nConfiance: {signal['conf']}%\nRaison: {signal['raison']}"
            bot.send_message(target_id, msg, parse_mode="Markdown")
        
        elif signal['action'] != "ATTENTE" and signal['conf'] > 80:
            emoji = "🟢" if "ACHAT" in signal['action'] else "🔴"
            msg = f"{emoji} *ALERTE {signal['action']}*\nPrix: {current_price}\nConf: {signal['conf']}%\n{signal['raison']}"
            bot.send_message(target_id, msg, parse_mode="Markdown")
            
    except:
        if manual_trigger: bot.send_message(target_id, f"Réponse brute: {clean_res}")

# --- LANCEMENT ---

@app.route('/')
def home(): return "Bot en ligne"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

def run_auto_loop():
    while True:
        analyze_market()
        time.sleep(600)

def run_bot_safe():
    # Suppression du webhook pour éviter l'erreur 409
    try:
        bot.remove_webhook()
        time.sleep(1)
    except: pass
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=5)
        except:
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_auto_loop).start()
    threading.Thread(target=run_bot_safe).start()
    run_flask()
