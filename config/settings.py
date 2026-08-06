import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
    WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN')
    WHATSAPP_API_VERSION = os.getenv('WHATSAPP_API_VERSION', 'v17.0')
    WHATSAPP_API_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
    GOOGLE_CREDENTIALS = 'config/google-credentials.json'
