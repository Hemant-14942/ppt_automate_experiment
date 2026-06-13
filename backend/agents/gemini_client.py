from google import genai
from config import GEMINI_API_KEY



# one client for the entire application
# created once when this file is first imported
# all agents share this same client
client = genai.Client(api_key=GEMINI_API_KEY)