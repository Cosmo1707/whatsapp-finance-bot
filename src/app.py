import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request
from config.settings import Config
from src.message_handler import MessageHandler

app = Flask(__name__)
handler = MessageHandler()

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode and token:
        if mode == 'subscribe' and token == Config.WHATSAPP_VERIFY_TOKEN:
            return challenge, 200
        else:
            return 'Forbidden', 403
    return 'Bad Request', 400

@app.route('/webhook', methods=['POST'])
def webhook():
    print("========== POST RECIBIDO ==========")
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
                        print(f"DEBUG: Telefono recibido = {from_phone}")
                        handler.process_message(from_phone, text)
    
    return 'ok', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
