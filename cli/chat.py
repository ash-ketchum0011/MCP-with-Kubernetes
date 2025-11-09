# cli/chat.py
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from ai.agent import AIAgent
from ai.adapters import OpenAIAdapter, OpenRouterAdapter, LocalAdapter
from dotenv import load_dotenv
import os

console = Console()
load_dotenv()

def terminal_chat():
    console.print(Panel.fit(
        "🤖 KubeSensei - Kubernetes AI Assistant\n"
        "💡 Ask for troubleshooting OR YAML generation\n"
        "Type 'exit' to quit",
        style="bold blue"
    ))

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

    # Show examples
    console.print("\n[dim]Example queries:[/dim]")
    console.print("[dim]  • Why is my nginx pod crashing?[/dim]")
    console.print("[dim]  • Generate YAML for ServiceAccount 'my-sa' in namespace 'default'[/dim]")
    console.print("[dim]  • Create deployment YAML for nginx with 3 replicas[/dim]")
    console.print("[dim]  • Show me YAML for ClusterRole with pod read permissions[/dim]\n")

    while True:
        user_input = console.input("[bold green]You:[/] ").strip()
        
        if user_input.lower() in ["exit", "quit", "q"]:
            console.print("👋 Goodbye!")
            break
        
        if not user_input:
            continue

        with console.status("[bold yellow]AI is thinking..."):
            response = agent.process_input(user_input)

        console.print("\n[bold blue]AI:[/]")
        console.print(Markdown(response))
        console.print()  # Extra line for spacing


if __name__ == "__main__":
    terminal_chat()