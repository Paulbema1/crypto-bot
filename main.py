import os
import time
import threading
import requests
import json
from flask import Flask

# --- 1. CONFIGURATION DU SERVEUR WEB (OBLIGATOIRE POUR RENDER) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Bot Crypto Actif 24/7"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. FONCTIONS DE TRADING ---
def send_telegram(message):
    try:
        token = os.environ.get('TG_TOKEN')
        chat_id = os.environ.get('TG_CHAT_ID')
        if token and chat_id:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
            print("✅ Message Telegram envoyé.")
        else:
            print("❌ Erreur: Clés Telegram manquantes.")
    except Exception as e:
        print(f"❌ Erreur envoi Telegram: {e}")

def analyze_market():
    print("🔍 Analyse du marché en cours...")
    
    # Récupérer les clés
    openai_key = os.environ.get('OPENAI_KEY')
    if not openai_key:
        print("❌ Erreur: Clé OpenAI manquante.")
        return

    try:
        # A. Récupérer données Binance (BTCUSDT)
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=10"
        response = requests.get(url)
        data = response.json()
        
        # On garde les prix de fermeture des 5 dernières bougies
        closes = [float(candle[4]) for candle in data[-5:]]
        current_price = closes[-1]
        
        print(f"💰 Prix BTC: {current_price} $")

        # B. Demander à l'IA
        prompt = f"""
        Agis comme un expert trader. Analyse ces 5 derniers prix de clôture BTC (15m): {closes}.
        Prix actuel: {current_price}.
        Détecte une tendance ou un setup.
        
        RÈGLE STRICTE : Réponds UNIQUEMENT avec ce JSON (pas de texte avant/après):
        {{
            "action": "ACHAT" ou "VENTE" ou "ATTENTE",
            "confidence": un nombre entre 0 et 100,
            "tp": "prix take profit",
            "sl": "prix stop loss",
            "reason": "phrase courte en français"
        }}
        """

        ai_resp = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {openai_key}'},
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5
            }
        )

        if ai_resp.status_code != 200:
            print(f"❌ Erreur OpenAI: {ai_resp.text}")
            return

        result_text = ai_resp.json()['choices'][0]['message']['content']
        signal = json.loads(result_text)
        
        print(f"🤖 IA: {signal['action']} ({signal['confidence']}%)")

        # C. Envoyer alerte si signal intéressant
        if signal['action'] != "ATTENTE" and signal['confidence'] > 75:
            emoji = "🟢" if signal['action'] == "ACHAT" else "🔴"
            msg = f"""
{emoji} *SIGNAL {signal['action']}*
----------------
💵 Prix: {current_price} $
🎯 TP: {signal['tp']}
🛑 SL: {signal['sl']}
📊 Confiance: {signal['confidence']}%
----------------
💡 _{signal['reason']}_
            """
            send_telegram(msg)
        else:
            print("💤 Pas de signal fort pour l'instant.")

    except Exception as e:
        print(f"❌ Erreur Analyse: {e}")

# --- 3. BOUCLE PRINCIPALE ---
def bot_loop():
    while True:
        analyze_market()
        print("⏳ Pause de 10 minutes...")
        time.sleep(600) # 600 secondes = 10 minutes

if __name__ == "__main__":
    # Lancer le bot en arrière-plan
    t = threading.Thread(target=bot_loop)
    t.start()
    
    # Lancer le serveur web pour Render
    run_web_server()
