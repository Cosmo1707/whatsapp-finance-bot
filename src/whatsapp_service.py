import requests
import sys
import os

# Agregar la carpeta raíz al path para importar config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import Config

class WhatsAppService:
    def __init__(self):
        self.api_url = Config.WHATSAPP_API_URL
        self.access_token = Config.WHATSAPP_ACCESS_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def send_message(self, to_phone, message):
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message}
        }
        response = requests.post(self.api_url, headers=self.headers, json=payload)
        return response.json()
