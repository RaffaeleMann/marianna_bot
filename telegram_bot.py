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
            # Telegram typing dura ~5 sec, reinviamo ogni 4
            for _ in range(8):  # 8 x 0.5 = 4 secondi (per stop più reattivo)
                if not self.running:
                    break
                time.sleep(0.5)
    
    def start(self):
        """Avvia l'indicatore"""
        self.running = True
        self._send_typing()  # Invia subito
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
        
        context = data.get('context', '')

        # --- LIMITE DI SICUREZZA: MAX 5000 TOKEN ---
        def truncate_tokens(txt, max_tokens=5000):
            tokens = txt.split()
            if len(tokens) > max_tokens:
                print(f"⚠️ Contesto troppo lungo ({len(tokens)} token). Taglio a {max_tokens}.")
                return " ".join(tokens[:max_tokens])
            return txt

        context = truncate_tokens(context)

        return context
            
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
            timeout=120  # Timeout lungo per LLM
        )
        
        response.raise_for_status()
        data = response.json()
        
        print(f"Chat API Response: {data}")
        
        return data.get('response', '')
            
    except Exception as e:
        print(f"Errore chat: {e}")
        return None


def trim_context(context, max_tokens=5000):
    """Taglia il contesto se supera max_tokens token (approssimati)."""
    if not context:
        return context
    
    tokens = context.split()
    if len(tokens) <= max_tokens:
        return context
    
    trimmed = " ".join(tokens[:max_tokens])
    print(f"[Context trimmed] {len(tokens)} → {max_tokens} tokens")
    return trimmed

def fit_context_for_model(message, context, max_tokens=5800):
    """
    Taglia il context in modo che message + context non superino max_tokens.
    Tokenizzazione approssimata via split(), sufficiente per LLAMA/gguf.
    """
    msg_tokens = len(message.split())
    ctx_tokens = len(context.split())

    if msg_tokens + ctx_tokens <= max_tokens:
        return context  # tutto ok

    # quanto spazio rimane per il context?
    allowed_ctx = max_tokens - msg_tokens

    if allowed_ctx < 0:
        allowed_ctx = 0

    print(f"[Context fitting] msg={msg_tokens}, ctx={ctx_tokens}, allowed_ctx={allowed_ctx}")

    trimmed_ctx = " ".join(context.split()[:allowed_ctx])

    print(f"[Context trimmed for model] {ctx_tokens} → {allowed_ctx} tokens")

    return trimmed_ctx


def process_user_message(chat_id, user_text):
    typing = TypingIndicator(chat_id)
    typing.start()

    try:
        # 1️⃣ Ottieni contesto
        context = get_context_from_api(user_text)

        if context is None:
            typing.stop()
            send_message(chat_id, "❌ Errore nel recupero del contesto. Riprova più tardi.")
            return

        if not context:
            typing.stop()
            send_message(chat_id, "🔍 Non ho trovato informazioni su questo argomento.")
            return

        # 🔥 2️⃣ TAGLIO CONTEX PREVENTIVO (max 5000 tokens)
        print(f"[Context original token count] {len(context.split())}")
        context = trim_context(context, max_tokens=5800)
        print(f"[Context used token count] {len(context.split())}")

        context = fit_context_for_model(user_text, context, max_tokens=5800)
        
        # 3️⃣ Richiesta alla /chat
        response = get_chat_response(user_text, context)

        typing.stop()

        if not response:
            send_message(chat_id, f"📚 *Contesto trovato (parziale):*\n\n{context[:3000]}")
            return

        send_message(chat_id, f"🤖 *Marianna:*\n\n{response}")

    except Exception as e:
        typing.stop()
        print(f"Errore process_user_message: {e}")
        send_message(chat_id, "❌ Si è verificato un errore. Riprova più tardi.")



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


@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    """Riceve gli update da Telegram e gestisce messaggi e comandi."""
    try:
        data = request.get_json(force=True)
        print(f"[WEBHOOK] Update ricevuto: {data}")

        message = data.get("message")
        if not message:
            return "no message", 200

        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        user_name = message.get("from", {}).get("first_name", "Utente")

        # ---------------------- #
        #      COMANDI /        #
        # ---------------------- #

        if text.startswith("/start"):
            reply = (
                f"👋 Ciao {user_name}!\n\n"
                "Sono *Marianna*, un'assistente virtuale esperta "
                "del patrimonio culturale di Napoli.\n"
                "Inviami una domanda e ti risponderò con piacere!\n\n"
                "📝 _Esempio: Parlami di Pulcinella_"
            )
            send_message(chat_id, reply)
            return "ok", 200

        if text.startswith("/help"):
            reply = (
                "ℹ️ *Come usare Marianna*\n\n"
                "Scrivi semplicemente una domanda.\n"
                "Marianna cercherà informazioni e ti risponderà.\n\n"
                "*Esempi:*\n"
                "• Parlami di Pulcinella\n"
                "• Chi era Totò?\n"
                "• Storia di Napoli"
            )
            send_message(chat_id, reply)
            return "ok", 200

        if text.startswith("/info"):
            reply = (
                "🤖 *Bot Marianna*\n\n"
                "Versione: 2.0\n"
                "Sviluppato per UniOr NLP Group da Dahlia.\n\n"
                f"API: `{API_BASE_URL}`"
            )
            send_message(chat_id, reply)
            return "ok", 200

        if text.startswith("/"):
            send_message(chat_id, "⚠️ Comando non riconosciuto. Usa /help")
            return "ok", 200

        # ---------------------- #
        #   MESSAGGI NORMALI     #
        # ---------------------- #
        process_user_message(chat_id, text)

    except Exception as e:
        print(f"[WEBHOOK] Errore: {e}")

    return "ok", 200


# --- AVVIO LOCALE ---
if __name__ == "__main__":
    print(f"🚀 Bot avviato!")
    print(f"📡 API URL: {API_BASE_URL}")
    print(f"🔐 Auth configurata: {bool(API_AUTH_USER and API_AUTH_PASS)}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
