import os
import time
import threading
import requests
import json
import telebot
import sys
from groq import Groq
from flask import Flask

# --- CONFIGURATION SYSTÈME ---
sys.stdout.reconfigure(encoding='utf-8')

# --- VARIABLES D'ENVIRONNEMENT (À configurer sur Render) ---
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')
# Modèle par défaut (Llama 3.3 est le plus stable actuellement)
MODEL_NAME = os.environ.get('MODEL_NAME', 'llama-3.3-70b-versatile')

# Initialisation Groq
client = Groq(api_key=GROQ_API_KEY)

# Initialisation Flask & Telegram
app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- OUTILS DE RÉCUPÉRATION DE PRIX ---

def get_btc_data():
    """Récupère le prix SPOT réel du Bitcoin sur Binance."""
    try:
        # 1. On récupère le prix exact à la seconde près
        price_url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        price_resp = requests.get(price_url, timeout=10).json()
        current_price = float(price_resp['price'])
        
        # 2. On récupère l'historique récent pour l'analyse
        klines_url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        klines_resp = requests.get(klines_url, timeout=10).json()
        closes = [float(c[4]) for c in klines_resp]
        
        # On remplace la dernière clôture par le prix exact en direct
        closes[-1] = current_price
        
        print(f"DEBUG: Prix BTC récupéré : {current_price}", flush=True)
        return closes
    except Exception as e:
        print(f"Erreur Binance: {e}", flush=True)
        return None

def ask_ai(prompt):
    """Envoie une requête à Groq."""
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Erreur Groq ({MODEL_NAME}): {e}", flush=True)
        return "Désolé, une erreur est survenue avec l'IA."

# --- COMMANDES TELEGRAM ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_msg = (
        "👋 **Bot Assistant Crypto Connecté !**\n\n"
        "💰 /prix - Voir le prix réel (Binance Spot)\n"
        "🧠 /analyse - Analyse technique (Llama 3.3)\n"
        "💬 *Pose-moi n'importe quelle question sur le trading.*"
    )
    bot.reply_to(message, welcome_msg, parse_mode="Markdown")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        price = data[-1]
        bot.reply_to(message, f"💰 **Bitcoin (BTC)** : `{price:,} $`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Erreur de connexion Binance.")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    bot.reply_to(message, "🧐 Analyse du marché en cours...")
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

# --- CHAT LIBRE ---

@bot.message_handler(func=lambda message: True)
def chat_with_ai(message):
    bot.send_chat_action(message.chat.id, 'typing')
    
    system_prompt = (
        "Tu es un expert en trading crypto. "
        "Réponds en français de manière courte et efficace. "
        f"\nQuestion : {message.text}"
    )
    
    reply = ask_ai(system_prompt)
    bot.reply_to(message, reply)

# --- LOGIQUE D'ANALYSE ---

def analyze_market(manual_trigger=False, chat_target=None):
    target_id = chat_target if manual_trigger else TG_CHAT_ID
    if not target_id: return

    closes = get_btc_data()
    if not closes: return

    current_price = closes[-1]
    
    prompt = f"""
    Agis comme un analyste financier. Voici les derniers prix BTC (15m): {closes}.
    Prix actuel: {current_price}.
    
    Réponds uniquement avec ce JSON strict :
    {{
        "action": "ACHAT", "VENTE" ou "ATTENTE",
        "conf": 85,
        "raison": "Une phrase courte expliquant pourquoi."
    }}
    """
    
    raw_res = ask_ai(prompt)
    if not raw_res: return

    clean_res = raw_res.replace('```json', '').replace('```', '').strip()

    try:
        signal = json.loads(clean_res)
        emoji = "🟢" if "ACHAT" in signal['action'] else "🔴" if "VENTE" in signal['action'] else "🟡"
        
        msg = (
            f"{emoji} **CONSEIL : {signal['action']}**\n\n"
            f"💵 Prix : `{current_price:,} $`\n"
            f"🧠 Confiance : `{signal['conf']}%`\n"
            f"💡 *{signal['raison']}*"
        )
        bot.send_message(target_id, msg, parse_mode="Markdown")
            
    except Exception:
        if manual_trigger: 
            bot.send_message(target_id, f"Analyse : {raw_res}")

# --- LANCEMENT ---

@app.route('/')
def home(): return "Bot en ligne et synchronisé."

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

def run_auto_loop():
    while True:
        try:
            analyze_market()
            time.sleep(600)
        except: time.sleep(60)

def run_bot_safe():
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(timeout=20)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_auto_loop, daemon=True).start()
    threading.Thread(target=run_bot_safe, daemon=True).start()
    run_flask()
