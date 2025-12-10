import os
import requests
import threading
import time
from flask import Flask, request

# --- CONFIGURAZIONE ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 5000))
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

API_BASE_URL = os.environ.get("API_BASE_URL", "https://nlpgroup.unior.it/api/marianna_head")
API_AUTH_USER = os.environ.get("API_AUTH_USER")
API_AUTH_PASS = os.environ.get("API_AUTH_PASS")

app = Flask(__name__)

#  Set per tracciare messaggi in elaborazione (evita duplicati)
processing_messages = set()
processing_lock = threading.Lock()


# --- CLASSE PER TYPING CONTINUO ---

class TypingIndicator:
    """Mantiene l'indicatore 'sta scrivendo...' attivo continuamente"""
    
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.running = False
        self.thread = None
    
    def _send_typing(self):
        """Invia l'azione typing"""
        url = f"{TELEGRAM_API}/sendChatAction"
        try:
            requests.post(url, json={"chat_id": self.chat_id, "action": "typing"}, timeout=5)
        except:
            pass
    
    def _keep_typing(self):
        """Loop che invia typing ogni 4 secondi"""
        while self.running:
            self._send_typing()
            for _ in range(8):  # 8 x 0.5 = 4 secondi
                if not self.running:
                    break
                time.sleep(0.5)
    
    def start(self):
        """Avvia l'indicatore"""
        self.running = True
        self._send_typing()
        self.thread = threading.Thread(target=self._keep_typing, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Ferma l'indicatore"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)


# --- FUNZIONI TELEGRAM ---

def send_message(chat_id, text, parse_mode="Markdown"):
    """Invia messaggio via API Telegram"""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Telegram response: {response.status_code}")
    except Exception as e:
        print(f"Errore invio messaggio: {e}")


# --- FUNZIONI API MARIANNA ---

def get_context_from_api(text):
    """Step 1: Chiama /get_marianna_context per ottenere il contesto"""
    try:
        url = f"{API_BASE_URL}/get_marianna_context"
        payload = {
            "text": text,
            "top_k": 2,
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
            timeout=120
        )
        
        response.raise_for_status()
        data = response.json()
        
        print(f"Chat API Response: {data}")
        
        return data.get('response', '')
            
    except Exception as e:
        print(f"Errore chat: {e}")
        return None


def trim_context(context, max_tokens=5000):
    """Taglia il contesto se supera max_tokens"""
    if not context:
        return context
    
    tokens = context.split()
    if len(tokens) <= max_tokens:
        return context
    
    trimmed = " ".join(tokens[:max_tokens])
    print(f" Context trimmed: {len(tokens)} → {max_tokens} tokens")
    return trimmed


def fit_context_for_model(message, context, max_tokens=5800):
    """Taglia context in base a messaggio + contesto totale"""
    msg_tokens = len(message.split())
    ctx_tokens = len(context.split())
    
    if msg_tokens + ctx_tokens <= max_tokens:
        return context
    
    allowed_ctx = max(0, max_tokens - msg_tokens)
    
    print(f" Context fitting: msg={msg_tokens}, ctx={ctx_tokens}, allowed={allowed_ctx}")
    
    return " ".join(context.split()[:allowed_ctx])


def process_user_message_background(message_id, chat_id, user_text):
    """
    Processa il messaggio in background.
    Rimuove il message_id dal set quando finisce.
    """
    typing = TypingIndicator(chat_id)
    typing.start()
    
    try:
        print(f" Processing message_id={message_id}")
        
        #  Ottieni contesto
        context = get_context_from_api(user_text)
        
        if context is None:
            typing.stop()
            send_message(chat_id, "❌ Errore nel recupero del contesto. Riprova più tardi.")
            return
        
        if not context:
            typing.stop()
            send_message(chat_id, "🔍 Non ho trovato informazioni su questo argomento.")
            return
        
        #  Taglio contesto
        print(f" Context original: {len(context.split())} tokens")
        context = trim_context(context, max_tokens=5000)
        context = fit_context_for_model(user_text, context, max_tokens=5800)
        print(f" Context trimmed: {len(context.split())} tokens")
        
        #  Genera risposta
        response = get_chat_response(user_text, context)
        
        typing.stop()
        
        if not response:
            send_message(chat_id, f"📚 *Contesto trovato:*\n\n{context[:3000]}")
            return
        
        #  Invia risposta
        send_message(chat_id, f"🤖 *Marianna:*\n\n{response}")
        
        print(f" Completed message_id={message_id}")
        
    except Exception as e:
        typing.stop()
        print(f" Errore process_user_message: {e}")
        send_message(chat_id, "  Si è verificato un errore. Riprova più tardi.")
    
    finally:
        #  Rimuovi dal set di elaborazione
        with processing_lock:
            processing_messages.discard(message_id)
            print(f" Released message_id={message_id}. Processing queue: {len(processing_messages)}")


# --- ENDPOINTS ---

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot Marianna attivo!", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "healthy",
        "bot": "marianna",
        "api_configured": bool(API_AUTH_USER and API_AUTH_PASS),
        "processing_queue": len(processing_messages)
    }, 200


@app.route("/" + str(TELEGRAM_BOT_TOKEN), methods=["POST"])
def webhook():
    """
    Riceve gli update da Telegram.
    Risponde immediatamente 200 OK e processa in background.
    """
    try:
        data = request.get_json(force=True)
        print(f"  Update ricevuto: {data}")
        
        message_data = data.get("message")
        if not message_data or "text" not in message_data:
            return "ok", 200
        
        message_id = message_data["message_id"]
        chat_id = message_data["chat"]["id"]
        text = message_data["text"]
        user_name = message_data["from"].get("first_name", "Utente")
        
        #  Controlla se già in elaborazione
        with processing_lock:
            if message_id in processing_messages:
                print(f" Message {message_id} già in elaborazione. Ignoro duplicato.")
                return "ok", 200
            
            # Aggiungi al set
            processing_messages.add(message_id)
            print(f" Acquired message_id={message_id}. Queue size: {len(processing_messages)}")
        
        # Comandi (risposte immediate)
        if text.startswith("/start"):
            send_message(
                chat_id,
                f"👋 Ciao {user_name}!\n\n"
                "Sono *Marianna*, un'assistente virtuale esperta del patrimonio culturale di Napoli.\n"
                "Inviami una domanda e cercherò di risponderti!\n\n"
                "📝 _Esempio: Parlami di Pulcinella_"
            )
            with processing_lock:
                processing_messages.discard(message_id)
        
        elif text.startswith("/help"):
            send_message(
                chat_id,
                "ℹ️ *Come usare Marianna:*\n\n"
                "Scrivi semplicemente una domanda.\n"
                "Marianna cercherà informazioni e ti risponderà.\n\n"
                "*Esempi:*\n"
                "• Parlami di Pulcinella\n"
                "• Chi era Totò?\n"
                "• Storia di Napoli"
            )
            with processing_lock:
                processing_messages.discard(message_id)
        
        elif text.startswith("/info"):
            send_message(
                chat_id,
                f"🤖 *Bot Marianna*\n\n"
                f"Versione: 2.0\n"
                f"Sviluppato per UniOr NLP Group da Dahlia.\n\n"
                f"API: `{API_BASE_URL}`\n"
                f"In coda: {len(processing_messages)} messaggi"
            )
            with processing_lock:
                processing_messages.discard(message_id)
        
        elif text.startswith("/"):
            send_message(chat_id, " Comando non riconosciuto. Usa /help")
            with processing_lock:
                processing_messages.discard(message_id)
        
        else:
            # 🚀 Messaggi normali → processa in background thread
            thread = threading.Thread(
                target=process_user_message_background,
                args=(message_id, chat_id, text),
                daemon=True
            )
            thread.start()
        
    except Exception as e:
        print(f"❌ Errore webhook: {e}")
    
    #  RISPOSTA IMMEDIATA A TELEGRAM (entro 1-2 secondi)
    return "ok", 200


# --- AVVIO LOCALE ---
if __name__ == "__main__":
    print(f"Bot avviato!")
    print(f"API URL: {API_BASE_URL}")
    print(f"Auth configurata: {bool(API_AUTH_USER and API_AUTH_PASS)}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
