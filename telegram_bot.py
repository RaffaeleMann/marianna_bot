import os
import requests
import json
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, Filters

# --- CONFIGURAZIONE ---
# variabile d'ambiente
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "TOKEN_DI_DEFAULT_PER_TEST")
# 2. Render 
PORT = int(os.environ.get("PORT", 5000)) 
# 3. La BASE_URL sarà l'indirizzo pubblico fornito da Render (es. https://tuo-bot.onrender.com)
#    
API_URL = "https://nlpgroup.unior.it/api/marianna_head/get_marianna_context"
API_AUTH_USER = "utenteuniornlp"
API_AUTH_PASS = "prova_asr_unior"
# ----------------------

# Inizializzazione di Flask e del Bot Telegram
app = Flask(__name__)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)


# --- FUNZIONI DI ELABORAZIONE ---

def start(update, context):
    update.message.reply_text('Ciao! Inviami una frase o una domanda e cercherò il contesto per te.')

def handle_message(update, context):
    # La logica del tuo bot rimane la stessa
    user_text = update.message.text

    try:
        payload = {
            "text": user_text,
            "top_k": 3,
            "use_stopwords": True
        }

        response = requests.post(
            API_URL,
            auth=(API_AUTH_USER, API_AUTH_PASS),
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        if 'context' in data and data['context']:
            reply_text = f"**Risposta dall'API:**\n\n{data['context']}"
        else:
            reply_text = "L'API ha risposto, ma non è stato trovato un contesto specifico."

    except requests.exceptions.RequestException as e:
        reply_text = f"❌ Errore API: {e}"
    except Exception as e:
        reply_text = f"❌ Errore inatteso: {e}"

    update.message.reply_markdown(reply_text)

# --- CONFIGURAZIONE DEL DISPATCHER ---
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))


# --- ENDPOINT DEL WEBHOOK (Funzione chiave per Render) ---

@app.route("/", methods=["GET"])
def index():
    # Endpoint per verificare che il server sia attivo
    return "Bot Telegram in ascolto!", 200

@app.route("/" + TELEGRAM_BOT_TOKEN, methods=["POST"])
def webhook():
    if request.method == "POST":
        # Crea l'oggetto Update
        update = Update.de_json(request.get_json(force=True), application.bot)
        
        # Metti l'aggiornamento nella coda dell'application
        application.update_queue.put(update)
        
        return "ok", 200
        
# --- FUNZIONE PRINCIPALE PER L'AVVIO ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
