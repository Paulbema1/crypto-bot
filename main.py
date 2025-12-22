import os
import time
import threading
import requests
from flask import Flask

# --- CONFIGURATION FLASK (POUR RENDER) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot en ligne 24/7"

def run_web_server():
    # Render donne un port spécifique via la variable d'environnement PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- LE CERVEAU DU BOT ---
def bot_logic():
    print("🤖 Démarrage du Bot...")
    
    # Vérification des clés
    openai_key = os.environ.get('OPENAI_KEY')
    tg_token = os.environ.get('TG_TOKEN')
    tg_chat_id = os.environ.get('TG_CHAT_ID')

    if not all([openai_key, tg_token, tg_chat_id]):
        print("❌ ERREUR : Il manque des clés (Variables d'environnement)")
        return

    while True:
        try:
            print("🔍 Analyse du marché...")
            
            # 1. Récupérer prix BTC
            url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=5"
            resp = requests.get(url).json()
            last_close = float(resp[-1][4])
            
            # 2. Demander à GPT (Simulation pour l'exemple, remplace par ton code complet)
            # Pour économiser tes crédits OpenAI pendant les tests, je mets une logique simple ici
            # Mais tu remettras ton appel OpenAI ici
            
            print(f"Prix actuel: {last_close}$")
            
            # Ici, tu insères ton appel OpenAI requests.post(...)
            # Si signal détecté -> send_telegram(...)
            
        except Exception as e:
            print(f"Erreur : {e}")
        
        # Pause de 10 minutes
        print("💤 Pause de 10 minutes...")
        time.sleep(600)

# --- LANCEMENT ---
if __name__ == "__main__":
    # Lancer le bot dans un fil séparé (background)
    t = threading.Thread(target=bot_logic)
    t.start()
    
    # Lancer le serveur web (bloquant, pour que Render soit content)
    run_web_server()
