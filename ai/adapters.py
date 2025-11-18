# ai/adapters.py
import os
import logging
from openai import OpenAI

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")  # "openai", "openrouter", or "local"

# Configuration
HTTP_REFERER = os.getenv("HTTP_REFERER", "https://github.com/k8s-ai-assistant")
APP_TITLE = os.getenv("APP_TITLE", "K8s AI Assistant")


class OpenAIAdapter:
    """Adapter for OpenAI API"""
    def __init__(self):
        if not OPENAI_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=OPENAI_KEY)
        self.model = "gpt-4o-mini"
        logger.info(f"🤖 Using OpenAI with model: {self.model}")
    
    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.0):
        try:
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
            
            # Check if we got a valid response
            if not response.choices or len(response.choices) == 0:
                raise RuntimeError("OpenAI returned empty choices")
            
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("OpenAI returned None content")
            
            return content
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise RuntimeError(f"OpenAI API error: {str(e)}") from e


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
        logger.info(f"🌐 Using OpenRouter with model: {model}")
    
    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.0):
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_headers={
                    "HTTP-Referer": HTTP_REFERER,  # Now using env var
                    "X-Title": APP_TITLE  # Now using env var
                }
            )
            
            # Validate response structure
            if not response.choices or len(response.choices) == 0:
                raise RuntimeError("OpenRouter returned empty choices array")
            
            if not hasattr(response.choices[0], 'message'):
                raise RuntimeError("OpenRouter response missing message")
            
            content = response.choices[0].message.content
            
            # Check for None content
            if content is None:
                raise RuntimeError("OpenRouter returned None content. This may indicate rate limiting, insufficient credits, or model unavailability.")
            
            return content
            
        except Exception as e:
            logger.error(f"OpenRouter API error: {str(e)}")
            # Re-raise the exception so the agent can handle it properly
            raise RuntimeError(f"OpenRouter API error: {str(e)}") from e


class LocalAdapter:
    """Local adapter for offline testing"""
    def __init__(self):
        self.call_count = 0
        logger.info("🔌 Using Local Adapter (no API calls)")
    
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