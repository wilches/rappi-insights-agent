"""
Minimal sanity check that Gemini API works with the key allocated on .env file.
"""

import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in environment. Check your .env file.")
        return

    print(f"API key loaded: {api_key[:8]}...{api_key[-4:]}")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents="Say 'Hola from Gemini' in one short sentence. Nothing else.",
    )

    print(f"\nResponse: {response.text}")
    print("\n✓ Gemini connection works.")


if __name__ == "__main__":
    main()
