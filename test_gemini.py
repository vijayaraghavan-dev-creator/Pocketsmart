import os
from dotenv import load_dotenv
from google import genai
load_dotenv()
c = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
print(c.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
      contents="Suggest 3 living-room lights under ₹5000.").text)
