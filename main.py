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
# Permet de changer de modèle sans toucher au code
MODEL_NAME = os.environ.get('MODEL_NAME', 'llama-3.3-70b-versatile')

# Initialisation Groq
client = Groq(api_key=GROQ_API_KEY)

# Initialisation Flask & Telegram
app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- OUTILS DE RÉCUPÉRATION ---

def get_btc_data():
    """Récupère les dernières bougies 15m du Bitcoin sur Binance."""
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        resp = requests.get(url, timeout=10).json()
        closes = [float(c[4]) for c in resp]
        return closes
    except Exception as e:
        print(f"Erreur Binance: {e}", flush=True)
        return None

def ask_ai(prompt):
    """Envoie une requête à Groq avec le modèle choisi."""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
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
        "👋 **Salut ! Je suis ton Assistant Crypto.**\n\n"
        "💰 /prix - Voir le prix actuel du Bitcoin\n"
        "🧠 /analyse - Lancer une analyse technique\n"
        "💬 *Tu peux aussi me poser des questions sur la crypto !*"
    )
    bot.reply_to(message, welcome_msg, parse_mode="Markdown")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        bot.reply_to(message, f"💰 **Bitcoin (BTC)** : `{data[-1]} $`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Impossible de contacter Binance.")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.send_chat_action(message.chat.id, 'typing')
    bot.reply_to(message, f"🧐 Analyse en cours ({MODEL_NAME})...")
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

# --- CHAT LIBRE ---

@bot.message_handler(func=lambda message: True)
def chat_with_ai(message):
    bot.send_chat_action(message.chat.id, 'typing')
    
    system_prompt = (
        "Tu es un expert en trading crypto et un ami sympa. "
        "Réponds de manière concise, directe et en français. "
        f"\nUtilisateur : {message.text}"
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
    Agis comme un analyste pro. Analyse ces clôtures BTC (15m): {closes[-5:]}.
    Prix actuel: {current_price}.
    
    Donne-moi UNIQUEMENT ce JSON strict, sans texte avant ou après :
    {{
        "action": "ACHAT", "VENTE" ou "ATTENTE",
        "conf": 85,
        "raison": "Une phrase courte."
    }}
    """
    
    raw_res = ask_ai(prompt)
    if not raw_res: return

    # Nettoyage de la réponse (pour extraire le JSON)
    clean_res = raw_res.replace('```json', '').replace('```', '').strip()

    try:
        signal = json.loads(clean_res)
        
        # Envoi du message formaté
        emoji = "🟢" if "ACHAT" in signal['action'] else "🔴" if "VENTE" in signal['action'] else "🟡"
        msg = (
            f"{emoji} **RÉSULTAT : {signal['action']}**\n\n"
            f"💵 Prix : `{current_price}$`\n"
            f"🧠 Confiance : `{signal['conf']}%`\n"
            f"💡 *{signal['raison']}*"
        )
        bot.send_message(target_id, msg, parse_mode="Markdown")
            
    except Exception as e:
        print(f"Erreur Parsing JSON: {e}", flush=True)
        if manual_trigger: 
            bot.send_message(target_id, f"Réponse brute de l'IA :\n{raw_res}")

# --- BOUCLES DE LANCEMENT ---

@app.route('/')
def home(): 
    return "Le bot crypto est en ligne !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def run_auto_loop():
    """Analyse automatique toutes les 10 minutes."""
    while True:
        try:
            analyze_market()
            time.sleep(600)
        except Exception as e:
            print(f"Erreur loop: {e}")
            time.sleep(60)

def run_bot_safe():
    """Lancement du bot avec sécurité contre les déconnexions."""
    while True:
        try:
            print("🎧 Bot prêt et à l'écoute...", flush=True)
            bot.remove_webhook()
            bot.infinity_polling(timeout=20, long_polling_timeout=5)
        except Exception as e:
            print(f"Erreur Polling: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Thread 1: Analyse auto
    t1 = threading.Thread(target=run_auto_loop, daemon=True)
    t1.start()
    
    # Thread 2: Bot Telegram
    t2 = threading.Thread(target=run_bot_safe, daemon=True)
    t2.start()
    
    # Principal: Serveur Flask pour Render
    run_flask()

