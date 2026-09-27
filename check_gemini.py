import os
from dotenv import load_dotenv

load_dotenv(override=True)
key = os.getenv("GEMINI_API_KEY", "").strip()
model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
print(f"1. .env read from: {os.getcwd()}")
print(f"2. key loaded: {bool(key)} | starts with: {key[:3]!r} | length: {len(key)}")
if not key:
    raise SystemExit("   -> No key. Put GEMINI_API_KEY=... in a file named exactly .env in this folder.")

from google import genai
print(f"3. google-genai version: {genai.__version__}")
client = genai.Client(api_key=key)
try:
    names = [m.name.removeprefix("models/") for m in client.models.list()
             if "generateContent" in (m.supported_actions or [])]
    flash = [n for n in names if "flash" in n]
    print(f"4. key accepted; {len(names)} models available. Flash models: {', '.join(flash[:12])}")
except Exception as e:
    raise SystemExit(f"4. key REJECTED by Google: {e}")

try:
    reply = client.models.generate_content(model=model, contents="Reply with the word OK.")
    print(f"5. {model} works: {reply.text.strip()}")
except Exception as e:
    print(f"5. {model} FAILED: {e}")
    options = [n for n in flash if n != model and "image" not in n and "tts" not in n]
    print(f"   -> add a line to .env with a model from the list, e.g. GEMINI_MODEL={options[0] if options else '...'}")
