"""Chat with the assistant in the terminal.  Run:  uv run chat.py"""
import sys

import config
import store
from agent import FrontDesk


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # so Hindi text prints correctly
    except Exception:                              # noqa: BLE001
        pass
    if not config.GEMINI_API_KEY:
        sys.exit("Missing GEMINI_API_KEY in .env")

    store.purge_old_messages()
    bot = FrontDesk()
    print(f"--- Test chat for: {bot.name}  (type 'quit' to stop) ---\n")
    print(f"Bot: {bot.greeting()}\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quit", "exit"):
            break
        if text:
            print(f"\nBot: {bot.reply(text)}\n")


if __name__ == "__main__":
    main()
