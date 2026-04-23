"""
Terminal CLI for testing the chat agent end-to-end.
Run: python -m scripts.chat_cli

Type questions in Spanish or English. Type 'exit' or Ctrl+C to quit.
Type 'reset' to clear conversation history.
"""

from pathlib import Path
import logging

from core.data_loader import load_unified_data
from agent.chat_agent import ChatAgent


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    print("\nLoading data...")
    df = load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )

    print("Starting agent. Type 'exit' to quit, 'reset' to clear history.\n")
    agent = ChatAgent(df)

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "salir"}:
            print("Goodbye.")
            break
        if user_input.lower() == "reset":
            agent.reset()
            print("(History cleared.)\n")
            continue

        try:
            response = agent.chat(user_input)
        except Exception as e:
            print(f"\n[Error] {type(e).__name__}: {e}\n")
            continue

        # Show tool calls for transparency (helpful during dev)
        if response.tool_calls:
            print("\n[Tool calls]")
            for tc in response.tool_calls:
                print(f"  - {tc['tool']}({tc['args']}) -> {tc['result_summary']}")

        print(f"\nAgent: {response.text}\n")


if __name__ == "__main__":
    main()
