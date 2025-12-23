import os
import time
import threading
import requests
import json
import telebot
import sys
import google.generativeai as genai
from flask import Flask

# --- FORCE L'AFFICHAGE DES LOGS ---
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get('GEMINI_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Config Gemini
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- OUTILS ---

def get_btc_data():
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        resp = requests.get(url, timeout=10).json()
        closes = [float(c[4]) for c in resp]
        return closes
    except Exception as e:
        print(f"Erreur Binance: {e}", flush=True)
        return None

def ask_gemini(prompt):
    try:
        # ICI LE CHANGEMENT : On utilise 'gemini-pro' qui est 100% compatible
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Erreur Gemini: {e}", flush=True)
        return "Désolé, une erreur IA est survenue."

# --- TELEGRAM (COMMANDES) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_msg = (
        "👋 **Salut ! Je suis ton Assistant Crypto.**\n\n"
        "💰 /prix - Voir le prix du Bitcoin\n"
        "🧠 /analyse - Analyse technique\n"
        "💬 *Tu peux aussi me parler normalement !*"
    )
    bot.reply_to(message, welcome_msg, parse_mode="Markdown")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        bot.reply_to(message, f"💰 **Bitcoin (BTC)** : {data[-1]} $", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Impossible de joindre Binance.")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    bot.reply_to(message, "🧐 Analyse Gemini Pro en cours...")
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

# --- DISCUSSION LIBRE ---

@bot.message_handler(func=lambda message: True)
def chat_with_ai(message):
    bot.send_chat_action(message.chat.id, 'typing')
    
    # Prompt pour lui donner une personnalité
    system_prompt = (
        "Tu es un assistant expert en crypto-trading et un ami sympa. "
        "Réponds de manière concise et utile. "
        f"\nQuestion utilisateur : {message.text}"
    )
    
    reply = ask_gemini(system_prompt)
    bot.reply_to(message, reply) # On envoie en texte normal pour éviter les bugs Markdown

# --- ANALYSE AUTOMATIQUE ---

def analyze_market(manual_trigger=False, chat_target=None):
    target_id = chat_target if manual_trigger else TG_CHAT_ID
    closes = get_btc_data()
    if not closes: return

    current_price = closes[-1]
    
    prompt = f"""
    Agis comme un analyste pro. Analyse ces clôtures BTC (15m): {closes[-5:]}.
    Prix actuel: {current_price}.
    
    Donne-moi UNIQUEMENT ce JSON strict :
    {{
        "action": "ACHAT" ou "VENTE" ou "ATTENTE",
        "conf": 85,
        "raison": "Une phrase courte d'analyse."
    }}
    """
    
    raw_res = ask_gemini(prompt)
    clean_res = raw_res.replace('```json', '').replace('```', '').strip()

    try:
        signal = json.loads(clean_res)
        
        if manual_trigger:
            msg = f"📊 **ANALYSE**\n\n🔹 Action: **{signal['action']}**\n🔹 Confiance: `{signal['conf']}%`\n💡 *{signal['raison']}*"
            bot.send_message(target_id, msg, parse_mode="Markdown")
        
        elif signal['action'] != "ATTENTE" and signal['conf'] > 80:
            emoji = "🟢" if "ACHAT" in signal['action'] else "🔴"
            msg = f"{emoji} **SIGNAL {signal['action']}**\n\n💵 Prix: `{current_price}$`\n🧠 Confiance: `{signal['conf']}%`\n\n📝 _{signal['raison']}_"
            bot.send_message(target_id, msg, parse_mode="Markdown")
            
    except Exception as e:
        if manual_trigger: 
            bot.send_message(target_id, f"Réponse brute IA (Erreur JSON): {clean_res}")

# --- LANCEMENT ---

@app.route('/')
def home(): return "Bot En Ligne"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

def run_auto_loop():
    while True:
        try:
            analyze_market()
            time.sleep(600)
        except: time.sleep(60)

def run_bot_safe():
    try:
        bot.remove_webhook()
        time.sleep(1)
    except: pass
    
    while True:
        try:
            print("🎧 Bot prêt...", flush=True)
            bot.infinity_polling(timeout=20, long_polling_timeout=5)
        except:
            time.sleep(5)

if __name__ == "__main__":
    t1 = threading.Thread(target=run_auto_loop)
    t1.start()
    
    t2 = threading.Thread(target=run_bot_safe)
    t2.start()
    
    run_flask()
