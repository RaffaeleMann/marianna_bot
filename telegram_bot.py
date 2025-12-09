import os
import requests
import json
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler
from telegram.ext import filters

# --- CONFIGURAZIONE ---
# 1. Variabili d'ambiente (Render)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "TOKEN_DI_DEFAULT_PER_TEST")
PORT = int(os.environ.get("PORT", 5000))

# 2. API
API_URL = "https://nlpgroup.unior.it/api/marianna_head/get_marianna_context"
API_AUTH_USER = "utenteuniornlp"
API_AUTH_PASS = "prova_asr_unior"
# ----------------------

# Inizializzazione di Flask
app = Flask(__name__)

# --- FUNZIONI DI ELABORAZIONE ---

def start(update, context):
    """Gestisce il comando /start."""
    update.message.reply_text('Ciao! Inviami una frase o una domanda e cercherò il contesto per te.')

def handle_message(update, context):
    """Gestisce i messaggi di testo e interroga l'API esterna."""
    user_text = update.message.text

    try:
        # Preparazione del payload per l'API Marianna
        payload = {
            "text": user_text,
            "top_k": 3,
            "use_stopwords": True
        }

        # Esecuzione della richiesta POST
        response = requests.post(
            API_URL,
            auth=(API_AUTH_USER, API_AUTH_PASS),
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        # Elaborazione della risposta
        if 'context' in data and data['context']:
            reply_text = f"**Risposta dall'API:**\n\n{data['context']}"
        else:
            reply_text = "L'API ha risposto, ma non è stato trovato un contesto specifico."

    except requests.exceptions.RequestException as e:
        # Gestione errori HTTP o di connessione
        reply_text = f"❌ Errore API: Impossibile connettersi o errore HTTP.\n{e}"
    except Exception as e:
        # Gestione di altri errori
        reply_text = f"❌ Si è verificato un errore inatteso durante l'elaborazione:\n{e}"

    update.message.reply_markdown(reply_text)


# --- CONFIGURAZIONE DELL'APPLICATION (Sostituisce Dispatcher) ---
# Inizializzazione dell'Application che gestisce il bot
application = Application.builder() \
    .token(TELEGRAM_BOT_TOKEN) \
    .http_version('1.1') \
    .get_updates_http_version('1.1') \
    .build()

# Aggiunta degli Handler 
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# --- ENDPOINT DEL WEBHOOK (Funzione chiave per Render) ---

@app.route("/", methods=["GET"])
def index():
    """Endpoint per verificare che il server Flask sia attivo."""
    return "Bot Telegram in ascolto!", 200

@app.route("/" + TELEGRAM_BOT_TOKEN, methods=["POST"])
def webhook():
    """Endpoint che riceve gli aggiornamenti da Telegram."""
    if request.method == "POST":
        # 1. Ottieni i dati JSON
        json_data = request.get_json(force=True)
        
        # 2. Utilizza il metodo application.process_update che gestisce l'asincronicità
        #    in modo non bloccante nel contesto sincrono di Flask.
        try:
            # Crea l'oggetto Update dall'input JSON
            update = Update.de_json(json_data, application.bot)
            
            # Processa l'update. Questo deve essere eseguito su un thread separato
            # o su un loop event-driven. In un contesto serverless/webhook semplice
            # come questo, usiamo un metodo non bloccante per avviare il processo.
            application.process_update(update) 
            
            # Se la riga sopra non funziona direttamente su Render, puoi provare:
            # application.create_task(application.process_update(update))

        except Exception as e:
            print(f"Errore durante l'elaborazione dell'update: {e}")
            # Rispondi comunque 200 a Telegram per evitare reinvii continui
            return "Errore interno", 200

        # Risposta attesa da Telegram per indicare che il messaggio è stato ricevuto
        return "ok", 200
    return "Method Not Allowed", 405
    
# --- FUNZIONE PRINCIPALE PER L'AVVIO ---
if __name__ == "__main__":
    # Render usa la porta 10000 o quella assegnata da env PORT
    # Gunicorn verrà utilizzato per l'avvio in produzione, ma questo è utile per i test locali.
    app.run(host="0.0.0.0", port=PORT)
