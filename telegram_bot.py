import os
import requests
from flask import Flask, request

# --- CONFIGURAZIONE ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 5000))
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

API_URL = "https://nlpgroup.unior.it/api/marianna_head/get_marianna_context"
API_AUTH_USER = "utenteuniornlp"
API_AUTH_PASS = "prova_asr_unior"

app = Flask(__name__)

# --- FUNZIONI HELPER ---

def send_message(chat_id, text, parse_mode="Markdown"):
    """Invia messaggio via API Telegram"""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")

def send_typing_action(chat_id):
    """Mostra 'sta scrivendo...' """
    url = f"{TELEGRAM_API}/sendChatAction"
    requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)

def get_context_from_api(text):
    """Chiama l'API Marianna"""
    try:
        payload = {
            "text": text,
            "top_k": 3,
            "use_stopwords": True
        }
        
        response = requests.post(
            API_URL,
            auth=(API_AUTH_USER, API_AUTH_PASS),
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        
        response.raise_for_status()
        data = response.json()
        
        print(f"API Response: {data}")  # Debug
        
        if 'context' in data and data['context']:
            return f"📚 *Contesto trovato:*\n\n{data['context']}"
        else:
            return "🔍 L'API ha risposto, ma non è stato trovato un contesto specifico."
            
    except requests.exceptions.Timeout:
        return "⏱️ Timeout: L'API ha impiegato troppo tempo a rispondere."
    except requests.exceptions.RequestException as e:
        return f"❌ Errore di connessione all'API:\n`{str(e)}`"
    except Exception as e:
        return f"❌ Errore inatteso:\n`{str(e)}`"

# --- ENDPOINTS ---

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot Marianna attivo!", 200

@app.route("/health", methods=["GET"])
def health():
    return {"status": "healthy", "bot": "marianna"}, 200

@app.route("/" + TELEGRAM_BOT_TOKEN, methods=["POST"])
def webhook():
    """Riceve gli update da Telegram"""
    try:
        data = request.get_json(force=True)
        print(f"Update ricevuto: {data}")  # Debug
        
        # Gestisci solo messaggi di testo
        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"]["text"]
            user_name = data["message"]["from"].get("first_name", "Utente")
            
            # Comando /start
            if text.startswith("/start"):
                reply = (
                    f"👋 Ciao {user_name}!\n\n"
                    "Sono il bot di Marianna. Inviami una frase o una domanda "
                    "e cercherò il contesto per te.\n\n"
                    "Esempio: _Parlami di Pulcinella_"
                )
                send_message(chat_id, reply)
            
            # Comando /help
            elif text.startswith("/help"):
                reply = (
                    "ℹ️ *Come usare questo bot:*\n\n"
                    "Scrivi semplicemente una frase o una domanda.\n"
                    "Il bot cercherà informazioni nel database di Marianna.\n\n"
                    "*Esempi:*\n"
                    "• Parlami di Pulcinella\n"
                    "• Chi era Totò?\n"
                    "• Storia di Napoli"
                )
                send_message(chat_id, reply)
            
            # Ignora altri comandi
            elif text.startswith("/"):
                send_message(chat_id, "⚠️ Comando non riconosciuto. Usa /help per assistenza.")
            
            # Messaggi normali -> chiama API
            else:
                # Mostra "sta scrivendo..."
                send_typing_action(chat_id)
                
                # Chiama l'API e rispondi
                reply = get_context_from_api(text)
                send_message(chat_id, reply)
        
    except Exception as e:
        print(f"Errore webhook: {e}")
    
    # Rispondi sempre 200 a Telegram
    return "ok", 200

# --- AVVIO ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
