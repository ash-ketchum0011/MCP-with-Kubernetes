# cli/chat.py - Complete working version
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from ai.agent import AIAgent
from ai.adapters import OpenAIAdapter, OpenRouterAdapter, LocalAdapter
from dotenv import load_dotenv
import os

console = Console()
load_dotenv()

def terminal_chat():
    console.print(Panel.fit("🤖 KubeSensei - Kubernetes AI Assistant\nType 'exit' to quit", style="bold blue"))

    # Choose adapter based on env var
    provider = os.getenv("LLM_PROVIDER", "local").lower()
    
    # Debug output
    print(f"🔧 Using provider: {provider}")
    
    if provider == "openai":
        adapter = OpenAIAdapter()
    elif provider == "openrouter":
        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-3.5-turbo")
        print(f"🌐 OpenRouter model: {model}")
        adapter = OpenRouterAdapter(model=model)
    else:
        print("📌 Using Local Adapter (no API calls)")
        adapter = LocalAdapter()
    
    agent = AIAgent(adapter)

    while True:
        user_input = console.input("\n[bold green]You:[/] ")
        if user_input.lower() in ["exit", "quit"]:
            console.print("👋 Goodbye!")
            break

        with console.status("[bold yellow]AI is analyzing your cluster..."):
            response = agent.process_input(user_input)

        console.print("\n[bold blue]AI:[/]")
        console.print(Markdown(response))


if __name__ == "__main__":
    terminal_chat()