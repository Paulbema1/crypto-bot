import os
import time
import threading
import requests
import json
import telebot
from flask import Flask

# --- CONFIGURATION ---
OPENAI_KEY = os.environ.get('OPENAI_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- 1. FONCTIONS UTILES (Réutilisables) ---
def get_btc_data():
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        resp = requests.get(url).json()
        closes = [float(c[4]) for c in resp]
        return closes
    except:
        return None

def ask_gpt(prompt):
    try:
        resp = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {OPENAI_KEY}'},
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }
        )
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Erreur IA: {e}"

# --- 2. COMMANDES TELEGRAM (INTERACTION) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Salut ! Je suis ton Bot Crypto.\n\nCommandes dispo:\n/prix - Prix BTC actuel\n/analyse - Lancer l'IA maintenant\nOu pose-moi une question directement !")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        price = data[-1]
        bot.reply_to(message, f"💰 BTC/USD : {price} $")
    else:
        bot.reply_to(message, "❌ Erreur Binance")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.reply_to(message, "🔍 Je lance l'analyse, patiente quelques secondes...")
    # On appelle la fonction d'analyse (définie plus bas)
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

# Répondre aux questions libres (Chat avec GPT)
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    user_msg = message.text
    # Petit message d'attente
    wait_msg = bot.reply_to(message, "🤔 Je réfléchis...")
    
    # Demander à GPT
    ai_reply = ask_gpt(f"Tu es un expert crypto. Réponds court : {user_msg}")
    
    # Modifier le message d'attente avec la réponse
    bot.edit_message_text(chat_id=message.chat.id, message_id=wait_msg.message_id, text=ai_reply)

# --- 3. ANALYSE AUTOMATIQUE ---
def analyze_market(manual_trigger=False, chat_target=None):
    # Si c'est manuel, on envoie la réponse à celui qui a demandé
    # Si c'est auto, on envoie au canal par défaut
    target_id = chat_target if manual_trigger else TG_CHAT_ID
    
    closes = get_btc_data()
    if not closes: return

    current_price = closes[-1]
    
    # Prompt IA pour analyse technique
    prompt = f"""
    Analyse technique BTC (15m). Clôtures: {closes[-5:]}.
    Prix: {current_price}.
    JSON strict : {{"action": "ACHAT/VENTE/ATTENTE", "conf": %, "raison": "courte"}}
    """
    
    raw_res = ask_gpt(prompt)
    
    try:
        signal = json.loads(raw_res)
        
        # Envoi du résultat
        if manual_trigger:
            # En manuel, on envoie TOUJOURS le résultat
            bot.send_message(target_id, f"🤖 *Analyse Manuelle*\nAction: {signal['action']}\nConfiance: {signal['conf']}%\nRaison: {signal['raison']}", parse_mode="Markdown")
        
        elif signal['action'] != "ATTENTE" and signal['conf'] > 75:
            # En auto, seulement si signal fort
            emoji = "🟢" if "ACHAT" in signal['action'] else "🔴"
            bot.send_message(target_id, f"{emoji} *ALERTE {signal['action']}*\nPrix: {current_price}\nConf: {signal['conf']}%\n{signal['raison']}", parse_mode="Markdown")
        else:
            print("Auto: Pas de signal fort.")
            
    except:
        if manual_trigger:
            bot.send_message(target_id, f"Brut: {raw_res}")

# --- 4. SERVER & THREADS ---
@app.route('/')
def home():
    return "🤖 Bot Interactif En Ligne"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def run_auto_loop():
    while True:
        print("⏰ Scan auto...")
        analyze_market() # Appel automatique
        time.sleep(600)

def run_telegram_bot():
    # Enlève les anciens webhooks pour éviter les conflits
    bot.remove_webhook()
    # Lance l'écoute
    bot.infinity_polling()

if __name__ == "__main__":
    # Thread 1: Analyse Auto
    threading.Thread(target=run_auto_loop).start()
    
    # Thread 2: Écoute Telegram (Interaction)
    threading.Thread(target=run_telegram_bot).start()
    
    # Main: Serveur Web (Pour Render)
    run_flask()
