import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request
import requests
from config.settings import Config
from src.message_handler import MessageHandler

app = Flask(__name__)
handler = MessageHandler()

# URL del bot de Studio 28 y token interno compartido
STUDIO28_URL = "https://studio28-bot.onrender.com/webhook-interno"
STUDIO28_TOKEN = "studio28_interno_secreto_123"

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Verificación del webhook por Meta."""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode and token:
        if mode == 'subscribe' and token == Config.WHATSAPP_VERIFY_TOKEN:
            print("Webhook verificado exitosamente!")
            return challenge, 200
        else:
            return 'Forbidden', 403
    
    return 'Bad Request', 400

@app.route('/webhook', methods=['POST'])
def webhook():
    """Recibe mensajes de WhatsApp."""
    data = request.json
    
    if data.get('object') == 'whatsapp_business_account':
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                messages = value.get('messages', [])
                
                for message in messages:
                    if message.get('type') == 'text':
                        from_phone = message.get('from')
                        text = message.get('text', {}).get('body', '')
                        print(f"DEBUG: Mensaje de {from_phone}: {text}")
                        
                        # Verificar si es mensaje de Studio 28
                        if text.strip().lower().startswith('studio 28'):
                            print("Reenviando a Studio 28...")
                            reenviar_a_studio28(from_phone, text)
                        else:
                            # Procesar normalmente en finanzas
                            handler.process_message(from_phone, text)
    
    return 'ok', 200

def reenviar_a_studio28(from_phone, text):
    """Reenvía el mensaje al bot de Studio 28."""
    try:
        payload = {
            "from_phone": from_phone,
            "text": text
        }
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Token": STUDIO28_TOKEN
        }
        response = requests.post(STUDIO28_URL, json=payload, headers=headers)
        print(f"Reenvío a Studio 28: Status {response.status_code}")
    except Exception as e:
        print(f"Error reenviando a Studio 28: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
