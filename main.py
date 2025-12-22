import os
import time
import threading
import requests
import json
import telebot
import google.generativeai as genai
from flask import Flask

# --- 1. CONFIGURATION ET VARIABLES ---
GEMINI_KEY = os.environ.get('GEMINI_KEY')
TG_TOKEN = os.environ.get('TG_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Configuration IA Google
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

app = Flask(__name__)
bot = telebot.TeleBot(TG_TOKEN)

# --- 2. FONCTIONS DE DONNÉES ET IA ---

def get_btc_data():
    """Récupère les 10 dernières bougies 15m de Binance"""
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        resp = requests.get(url, timeout=10).json()
        # On ne garde que le prix de fermeture (index 4)
        closes = [float(c[4]) for c in resp]
        return closes
    except Exception as e:
        print(f"Erreur Binance: {e}")
        return None

def ask_gemini(prompt):
    """Interroge l'IA Gratuite"""
    try:
        if not GEMINI_KEY:
            return "❌ Erreur: Clé GEMINI_KEY manquante sur Render."
            
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erreur Gemini: {e}"

# --- 3. COMMANDES TELEGRAM (INTERACTIF) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Salut ! Je suis ton Bot Crypto 100% Gratuit.\n\nCommandes :\n/prix - Voir le BTC actuel\n/analyse - Lancer une analyse technique")

@bot.message_handler(commands=['prix'])
def send_price(message):
    data = get_btc_data()
    if data:
        bot.reply_to(message, f"💰 BTC/USD : {data[-1]} $")
    else:
        bot.reply_to(message, "❌ Impossible de joindre Binance.")

@bot.message_handler(commands=['analyse'])
def force_analyze(message):
    bot.reply_to(message, "🧠 Analyse Google Gemini en cours...")
    # On lance l'analyse manuelle ciblée vers cet utilisateur
    analyze_market(manual_trigger=True, chat_target=message.chat.id)

# Chat libre avec l'IA
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    user_msg = message.text
    # Affiche "écrit..." en haut du chat
    bot.send_chat_action(message.chat.id, 'typing')
    
    prompt = f"Tu es un expert en trading crypto. Réponds de façon concise à cette question : {user_msg}"
    reply = ask_gemini(prompt)
    bot.reply_to(message, reply)

# --- 4. CŒUR DU SYSTÈME (ANALYSE) ---

def analyze_market(manual_trigger=False, chat_target=None):
    # Si manuel, on répond à la personne qui a demandé. Sinon, au canal par défaut.
    target_id = chat_target if manual_trigger else TG_CHAT_ID
    
    closes = get_btc_data()
    if not closes:
        if manual_trigger: bot.send_message(target_id, "Erreur données Binance")
        return

    current_price = closes[-1]
    
    # Prompt stricte pour obtenir du JSON
    prompt = f"""
    Agis comme un trader professionnel. Analyse ces 5 dernières clôtures BTC (15m): {closes[-5:]}.
    Prix actuel: {current_price}.
    
    Retourne UNIQUEMENT ce JSON (sans balises markdown):
    {{
        "action": "ACHAT" ou "VENTE" ou "ATTENTE",
        "conf": 85,
        "raison": "Explication ultra courte en français"
    }}
    """
    
    raw_res = ask_gemini(prompt)
    
    # Nettoyage bourrin du résultat (enlève ```json et ```)
    clean_res = raw_res.replace('```json', '').replace('```', '').strip()

    try:
        signal = json.loads(clean_res)
        
        # LOGIQUE D'ENVOI
        # 1. Si c'est manuel, on envoie TOUT LE TEMPS
        if manual_trigger:
            msg = f"🤖 *Analyse Manuelle*\nAction: {signal['action']}\nConfiance: {signal['conf']}%\nRaison: {signal['raison']}"
            bot.send_message(target_id, msg, parse_mode="Markdown")
        
        # 2. Si c'est automatique, on envoie SEULEMENT si signal fort
        elif signal['action'] != "ATTENTE" and signal['conf'] > 80:
            emoji = "🟢" if "ACHAT" in signal['action'] else "🔴"
            msg = f"{emoji} *ALERTE {signal['action']}*\nPrix: {current_price}\nConf: {signal['conf']}%\n{signal['raison']}"
            bot.send_message(target_id, msg, parse_mode="Markdown")
        else:
            print("Auto: Pas de signal fort.")
            
    except Exception as e:
        if manual_trigger:
            bot.send_message(target_id, f"Erreur lecture JSON: {clean_res}")

# --- 5. GESTION DU SERVEUR ET DES THREADS ---

@app.route('/')
def home():
    return "🤖 Bot Actif - Ne pas fermer cet onglet"

def run_flask():
    # Render donne le PORT via une variable d'environnement
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def run_auto_loop():
    """Boucle infinie qui analyse toutes les 10 minutes"""
    while True:
        print("⏰ Scan auto...")
        analyze_market() 
        time.sleep(600) # 600 secondes

def run_bot_safe():
    """Lance Telegram avec reconnexion auto en cas de crash 409"""
    print("🔗 Démarrage Telegram...")
    
    # Force la suppression des anciens webhooks pour éviter l'erreur 409
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass

    while True:
        try:
            # infinity_polling gère mieux les coupures que polling simple
            bot.infinity_polling(timeout=20, long_polling_timeout=5)
        except Exception as e:
            print(f"⚠️ Erreur Telegram: {e}")
            print("♻️ Redémarrage du bot dans 5 secondes...")
            time.sleep(5)

if __name__ == "__main__":
    # Lancer l'analyse auto en fond
    t1 = threading.Thread(target=run_auto_loop)
    t1.start()
    
    # Lancer Telegram en fond
    t2 = threading.Thread(target=run_bot_safe)
    t2.start()
    
    # Lancer le serveur Web (Bloquant)
    run_flask()
