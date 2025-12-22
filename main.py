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

# Configuration Google Gemini
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- 1. FONCTIONS UTILES ---
def get_btc_data():
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        resp = requests.get(url).json()
        closes = [float(c[4]) for c in resp]
        return closes
    except:
        return None

def ask_gemini(prompt):
    try:
        if not GEMINI_KEY:
            return "❌ Erreur: Clé Gemini manquante sur Render."
            
        # On utilise le modèle Flash (Rapide et Gratuit)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erreur Gemini: {e}"

# --- 2. COMMANDES TELEGRAM ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Salut ! Je suis ton Bot Crypto (Propulsé par Google Gemini).\n/prix - Prix BTC\n/analyse - Analyse IA Gratuite")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        bot.reply_to(message, f"💰 BTC/USD : {data[-1]} $")
    else:
        bot.reply_to(message, "❌ Erreur Binance")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.reply_to(message, "🧠 Analyse Google Gemini en cours...")
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

# Chat libre avec Gemini
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    user_msg = message.text
    bot.send_chat_action(message.chat.id, 'typing') # Affiche "écrit..."
    
    reply = ask_gemini(f"Tu es un expert crypto. Réponse courte: {user_msg}")
    bot.reply_to(message, reply)

# --- 3. ANALYSE AUTOMATIQUE ---
def analyze_market(manual_trigger=False, chat_target=None):
    target_id = chat_target if manual_trigger else TG_CHAT_ID
    closes = get_btc_data()
    
    if not closes:
        if manual_trigger: bot.send_message(target_id, "Erreur données Binance")
        return

    current_price = closes[-1]
    
    # Prompt optimisé pour Gemini
    prompt = f"""
    Agis comme un trader professionnel. Analyse ces 5 dernières clôtures BTC (15m): {closes[-5:]}.
    Prix actuel: {current_price}.
    
    Retourne UNIQUEMENT ce JSON (sans texte autour, sans balises markdown ```json):
    {{
        "action": "ACHAT" ou "VENTE" ou "ATTENTE",
        "conf": 85,
        "raison": "Explication ultra courte en français"
    }}
    """
    
    raw_res = ask_gemini(prompt)
    
    # Nettoyage de la réponse Gemini (parfois il met des ```json autour)
    clean_res = raw_res.replace('```json', '').replace('```', '').strip()

    try:
        signal = json.loads(clean_res)
        
        # Logique d'envoi
        if manual_trigger:
            msg = f"🤖 *Gemini Analysis*\nAction: {signal['action']}\nConfiance: {signal['conf']}%\nRaison: {signal['raison']}"
            bot.send_message(target_id, msg, parse_mode="Markdown")
        
        elif signal['action'] != "ATTENTE" and signal['conf'] > 80:
            emoji = "🟢" if "ACHAT" in signal['action'] else "🔴"
            msg = f"{emoji} *ALERTE {signal['action']}*\nPrix: {current_price}\nConf: {signal['conf']}%\n{signal['raison']}"
            bot.send_message(target_id, msg, parse_mode="Markdown")
            
    except Exception as e:
        if manual_trigger:
            bot.send_message(target_id, f"Erreur lecture JSON: {clean_res}")

# --- 4. LANCEMENT ---
@app.route('/')
def home(): return "Gemini Bot Alive"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

def run_auto_loop():
    while True:
        analyze_market()
        time.sleep(600)

def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_auto_loop).start()
    threading.Thread(target=run_bot).start()
    run_flask()
