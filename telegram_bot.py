import os
import requests
import time
from flask import Flask, request

# --- CONFIGURAZIONE (Variabili d'ambiente su Render) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 5000))
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# 🔐 Credenziali API nascoste in variabili d'ambiente
API_BASE_URL = os.environ.get("API_BASE_URL", "https://nlpgroup.unior.it/api/marianna_head")
API_AUTH_USER = os.environ.get("API_AUTH_USER")
API_AUTH_PASS = os.environ.get("API_AUTH_PASS")

app = Flask(__name__)

# --- FUNZIONI TELEGRAM ---

def send_message(chat_id, text, parse_mode="Markdown"):
    """Invia messaggio via API Telegram e ritorna message_id"""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        if data.get("ok"):
            return data["result"]["message_id"]
    except Exception as e:
        print(f"Errore invio messaggio: {e}")
    return None


def edit_message(chat_id, message_id, text, parse_mode="Markdown"):
    """Modifica un messaggio esistente (per effetto streaming)"""
    url = f"{TELEGRAM_API}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Errore edit messaggio: {e}")


def send_typing_action(chat_id):
    """Mostra 'sta scrivendo...'"""
    url = f"{TELEGRAM_API}/sendChatAction"
    try:
        requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except:
        pass


# --- FUNZIONI API MARIANNA ---

def get_context_from_api(text):
    """Step 1: Chiama /get_marianna_context per ottenere il contesto"""
    try:
        url = f"{API_BASE_URL}/get_marianna_context"
        payload = {
            "text": text,
            "top_k": 3,
            "use_stopwords": True
        }
        
        response = requests.post(
            url,
            auth=(API_AUTH_USER, API_AUTH_PASS),
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        
        response.raise_for_status()
        data = response.json()
        
        print(f"Context API Response: {data}")
        
        return data.get('context', '')
            
    except Exception as e:
        print(f"Errore get_context: {e}")
        return None


def get_chat_response(message, context):
    """Step 2: Chiama /chat per generare la risposta finale"""
    try:
        url = f"{API_BASE_URL}/chat"
        payload = {
            "message": message,
            "context": context
        }
        
        response = requests.post(
            url,
            auth=(API_AUTH_USER, API_AUTH_PASS),
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        response.raise_for_status()
        data = response.json()
        
        print(f"Chat API Response: {data}")
        
        return data.get('response', '')
            
    except Exception as e:
        print(f"Errore chat: {e}")
        return None


def stream_response_to_telegram(chat_id, message_id, full_text, chunk_size=20):
    """
    Simula effetto streaming aggiornando il messaggio progressivamente
    chunk_size = numero di caratteri per aggiornamento
    """
    displayed_text = ""
    
    for i in range(0, len(full_text), chunk_size):
        displayed_text = full_text[:i + chunk_size]
        
        # Aggiungi cursore lampeggiante durante lo streaming
        cursor = "▌" if i + chunk_size < len(full_text) else ""
        
        edit_message(chat_id, message_id, f"🤖 *Marianna:*\n\n{displayed_text}{cursor}")
        
        # Pausa per effetto typewriter (evita rate limiting Telegram)
        time.sleep(0.3)
    
    # Messaggio finale senza cursore
    edit_message(chat_id, message_id, f"🤖 *Marianna:*\n\n{full_text}")


def process_user_message(chat_id, user_text):
    """Processa il messaggio: context → chat → streaming response"""
    
    # 1️⃣ Invia messaggio iniziale
    send_typing_action(chat_id)
    msg_id = send_message(chat_id, "⏳ _Recupero il contesto..._")
    
    if not msg_id:
        send_message(chat_id, "❌ Errore nell'invio del messaggio.")
        return
    
    # 2️⃣ Ottieni contesto
    context = get_context_from_api(user_text)
    
    if context is None:
        edit_message(chat_id, msg_id, "❌ Errore nel recupero del contesto.")
        return
    
    if not context:
        edit_message(chat_id, msg_id, "🔍 Nessun contesto trovato per questa domanda.")
        return
    
    # 3️⃣ Aggiorna stato
    edit_message(chat_id, msg_id, "📚 _Contesto trovato! Genero risposta..._")
    send_typing_action(chat_id)
    
    # 4️⃣ Genera risposta con /chat
    response = get_chat_response(user_text, context)
    
    if not response:
        edit_message(chat_id, msg_id, "❌ Errore nella generazione della risposta.")
        return
    
    # 5️⃣ Streaming della risposta
    stream_response_to_telegram(chat_id, msg_id, response, chunk_size=30)


# --- ENDPOINTS ---

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot Marianna attivo!", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "healthy", 
        "bot": "marianna",
        "api_configured": bool(API_AUTH_USER and API_AUTH_PASS)
    }, 200


@app.route("/" + str(TELEGRAM_BOT_TOKEN), methods=["POST"])
def webhook():
    """Riceve gli update da Telegram"""
    try:
        data = request.get_json(force=True)
        print(f"Update ricevuto: {data}")
        
        # Gestisci solo messaggi di testo
        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"]["text"]
            user_name = data["message"]["from"].get("first_name", "Utente")
            
            # Comando /start
            if text.startswith("/start"):
                reply = (
                    f"👋 Ciao {user_name}!\n\n"
                    "Sono *Marianna*, il tuo assistente virtuale.\n"
                    "Inviami una domanda e cercherò di risponderti!\n\n"
                    "📝 _Esempio: Parlami di Pulcinella_"
                )
                send_message(chat_id, reply)
            
            # Comando /help
            elif text.startswith("/help"):
                reply = (
                    "ℹ️ *Come usare Marianna:*\n\n"
                    "Scrivi semplicemente una domanda.\n"
                    "Marianna cercherà informazioni e ti risponderà.\n\n"
                    "*Esempi:*\n"
                    "• Parlami di Pulcinella\n"
                    "• Chi era Totò?\n"
                    "• Storia di Napoli\n\n"
                    "🔄 La risposta apparirà con effetto streaming!"
                )
                send_message(chat_id, reply)
            
            # Comando /info
            elif text.startswith("/info"):
                reply = (
                    "🤖 *Bot Marianna*\n\n"
                    "Versione: 2.0 (Streaming)\n"
                    "Sviluppato per UniOr NLP Group\n\n"
                    f"API: `{API_BASE_URL}`"
                )
                send_message(chat_id, reply)
            
            # Ignora altri comandi
            elif text.startswith("/"):
                send_message(chat_id, "⚠️ Comando non riconosciuto. Usa /help")
            
            # Messaggi normali → processo completo
            else:
                process_user_message(chat_id, text)
        
    except Exception as e:
        print(f"Errore webhook: {e}")
    
    return "ok", 200


# --- AVVIO LOCALE ---
if __name__ == "__main__":
    print(f"🚀 Bot avviato!")
    print(f"📡 API URL: {API_BASE_URL}")
    print(f"🔐 Auth configurata: {bool(API_AUTH_USER and API_AUTH_PASS)}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
