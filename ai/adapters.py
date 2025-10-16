# ai/adapters.py
import os
from openai import OpenAI

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")  # "openai", "openrouter", or "local"


class OpenAIAdapter:
    """Adapter for OpenAI API"""
    def __init__(self):
        if not OPENAI_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=OPENAI_KEY)
        self.model = "gpt-4o-mini"
    
    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.0):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        return response.choices[0].message.content


class OpenRouterAdapter:
    """Adapter for OpenRouter API (supports free models)"""
    def __init__(self, model: str = "openai/gpt-3.5-turbo"):
        if not OPENROUTER_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set. Get one free at https://openrouter.ai/keys")
        
        # OpenRouter uses OpenAI-compatible API
        self.client = OpenAI(
            api_key=OPENROUTER_KEY,
            base_url="https://openrouter.ai/api/v1"
        )
        self.model = model
        print(f"🌐 Using OpenRouter with model: {model}")
    
    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.0):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_headers={
                    "HTTP-Referer": "https://github.com/your-repo",  # Optional: for rankings
                    "X-Title": "K8s AI Assistant"  # Optional: show in rankings
                }
            )
            return response.choices[0].message.content
        except Exception as e:
            return f'{{"error": "OpenRouter API error: {str(e)}"}}'


class LocalAdapter:
    """Local adapter for offline testing"""
    def __init__(self):
        self.call_count = 0
        print("🔌 Using Local Adapter (no API calls)")
    
    def chat(self, system: str, user: str, **kwargs):
        """Simple deterministic behavior for testing"""
        self.call_count += 1
        
        # First call: request pods
        if self.call_count == 1:
            return '{"tool_call": {"name": "get_pods", "args": {"namespace": "default"}}}'
        
        # Second call: return final response
        return '''{
            "final_response": {
                "analysis": "Cluster analysis complete. Found pods in default namespace.",
                "recommendation": "All systems appear operational.",
                "kubectl": "kubectl get pods -n default",
                "confidence": 0.85,
                "post_checks": ["Monitor pod restarts", "Check resource usage"]
            }
        }'''