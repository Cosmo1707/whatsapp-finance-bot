import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request
import requests
from config.settings import Config
from src.message_handler import MessageHandler, PROCESSING_LOCK

app = Flask(__name__)
handler = MessageHandler()

# URL del bot de Studio 28 y token interno compartido
STUDIO28_URL = "https://studio28-bot.onrender.com/webhook-interno"
STUDIO28_TOKEN = os.getenv("STUDIO28_TOKEN")

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
    """Recibe mensajes; un fallo de persistencia devuelve 503 para reentrega."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return 'Bad Request', 400
    failed = False
    if data.get('object') == 'whatsapp_business_account':
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                for message in change.get('value', {}).get('messages', []):
                    if message.get('type') != 'text':
                        continue
                    from_phone = message.get('from')
                    text = message.get('text', {}).get('body', '')
                    message_id = message.get('id', '')
                    if not message_id or not from_phone or not isinstance(text, str):
                        failed = True
                        continue
                    try:
                        with PROCESSING_LOCK:
                            normalized = text.strip().lower()
                            if normalized.startswith('studio 28') or normalized in ['si', 'sí', 'no']:
                                # Puente legado: conserva ruteo, payload, token y marcado.
                                if verificar_duplicado(message_id):
                                    continue
                                marcar_procesado(message_id)
                                reenviar_a_studio28(from_phone, text, message_id)
                            else:
                                handler.process_message(from_phone, text, message_id)
                    except Exception:
                        app.logger.exception("Fallo procesando message_id=%s", message_id)
                        failed = True
    return ('Retry', 503) if failed else ('ok', 200)

def reenviar_a_studio28(from_phone, text, message_id):
    """Reenvía el mensaje al bot de Studio 28."""
    try:
        payload = {
            "from_phone": from_phone,
            "text": text,
            "message_id": message_id
        }
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Token": STUDIO28_TOKEN
        }
        response = requests.post(STUDIO28_URL, json=payload, headers=headers)
        print(f"Reenvío a Studio 28: Status {response.status_code}")
    except Exception as e:
        print(f"Error reenviando a Studio 28: {e}")

def verificar_duplicado(message_id):
    """Consulta la hoja Mensajes Procesados para ver si ya existe."""
    try:
        result = handler.sheets.service.spreadsheets().values().get(
            spreadsheetId=Config.SPREADSHEET_ID,
            range='Mensajes Procesados!A:A'
        ).execute()
        values = result.get('values', [])
        for row in values:
            if row and row[0] == message_id:
                return True
        return False
    except Exception as e:
        print(f"Error verificando duplicado: {e}")
        return False

def marcar_procesado(message_id):
    """Agrega el message_id a la hoja Mensajes Procesados."""
    try:
        values = [[message_id]]
        body = {'values': values}
        handler.sheets.service.spreadsheets().values().append(
            spreadsheetId=Config.SPREADSHEET_ID,
            range='Mensajes Procesados!A:A',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
    except Exception as e:
        print(f"Error marcando procesado: {e}")

@app.route('/ping', methods=['GET', 'HEAD'])
def ping():
    return 'pong', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=False,
            use_reloader=False)
