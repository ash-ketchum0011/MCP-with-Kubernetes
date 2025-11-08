# cli/chat.py
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from ai.agent import AIAgent
from ai.adapters import OpenAIAdapter, OpenRouterAdapter, LocalAdapter
import os

console = Console()

def terminal_chat():
    console.print(Panel.fit("🤖 KubeSensei - Kubernetes AI Assistant\nType 'exit' to quit", style="bold blue"))

    # Choose adapter based on env var
    provider = os.getenv("LLM_PROVIDER", "local").lower()
    
    if provider == "openai":
        adapter = OpenAIAdapter()
    elif provider == "openrouter":
        # Get model from env or use default free model
        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-3.5-turbo")
        adapter = OpenRouterAdapter(model=model)
    else:
        adapter = LocalAdapter()
    
    agent = AIAgent(adapter)

    while True:
        user_input = console.input("\n[bold green]You:[/] ")
        if user_input.lower() == "exit":
            break

        with console.status("[bold yellow]AI is analyzing your cluster..."):
            response = agent.process_input(user_input)

        console.print("\n[bold blue]AI:[/]")
        console.print(Markdown(response))


if __name__ == "__main__":
    terminal_chat()