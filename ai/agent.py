# ai/agent.py
import json
import asyncio
import os
from typing import Dict, Any
from mcp.server import LocalMCP, list_tools

SYSTEM_PROMPT = """You are a Kubernetes SRE assistant that helps diagnose cluster issues.

CRITICAL: You MUST respond with ONLY valid JSON. No markdown, no explanations, ONLY JSON.

Two response formats:

1) To call a tool:
{{"tool_call": {{"name": "TOOL_NAME", "args": {{}}}}}}

2) To give final answer:
{{"final_response": {{"analysis": "your analysis here", "recommendation": "your recommendation", "kubectl": "kubectl command", "confidence": 0.9, "post_checks": ["check 1", "check 2"]}}}}

Available tools: {tools}

RULES:
- First call get_pods or relevant tool to gather data
- Analyze the tool results
- Then respond with final_response
- ONLY use tools from the list above
- Tools are read-only, never mutate cluster
- Keep responses concise

Example conversation:
User: "list pods"
You: {{"tool_call": {{"name": "get_pods", "args": {{"namespace": "default"}}}}}}
[Tool returns pod data]
You: {{"final_response": {{"analysis": "Found 5 pods, 3 running, 2 pending", "recommendation": "Check pending pods for scheduling issues", "kubectl": "kubectl describe pod <pod-name>", "confidence": 0.95, "post_checks": ["Check node resources", "Review pod events"]}}}}

Remember: ONLY output JSON, nothing else."""

mcp_client = LocalMCP()
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

class AIAgent:
    def __init__(self, adapter):
        self.adapter = adapter
        self.tools = list_tools()
    
    def _get_system_prompt(self):
        tools_str = ", ".join(self.tools.keys())
        return SYSTEM_PROMPT.format(tools=tools_str)
    
    def _invoke_tool_sync(self, name: str, args: Dict[str, Any]):
        """Synchronous wrapper for tool invocation"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(mcp_client.invoke(name, args))
            return result
        finally:
            loop.close()
    
    def process_input(self, user_question: str, max_steps: int = 6):
        """Main dialog loop with the AI agent"""
        conversation_context = []
        user_msg = json.dumps({"user_question": user_question})
        
        for step in range(max_steps):
            if DEBUG:
                print(f"\n[DEBUG] Step {step + 1}/{max_steps}")
                print(f"[DEBUG] Sending to AI: {user_msg[:200]}...")
            
            # Get AI response
            reply = self.adapter.chat(self._get_system_prompt(), user_msg)
            
            if DEBUG:
                print(f"[DEBUG] AI raw response: {reply}")
            
            # Clean up response - remove markdown code blocks if present
            reply = reply.strip()
            if reply.startswith("```json"):
                reply = reply[7:]
            if reply.startswith("```"):
                reply = reply[3:]
            if reply.endswith("```"):
                reply = reply[:-3]
            reply = reply.strip()
            
            if DEBUG:
                print(f"[DEBUG] AI cleaned response: {reply}")
            
            try:
                parsed = json.loads(reply)
            except json.JSONDecodeError as e:
                return f"❌ Error: AI returned invalid JSON:\n{reply}\n\nError: {e}"
            
            # Check if this is a tool call
            if "tool_call" in parsed:
                tool_info = parsed["tool_call"]
                tool_name = tool_info.get("name")
                tool_args = tool_info.get("args", {})
                
                if DEBUG:
                    print(f"[DEBUG] Tool call: {tool_name} with args {tool_args}")
                
                if tool_name not in self.tools:
                    return f"❌ Error: AI requested unknown tool '{tool_name}'. Available: {list(self.tools.keys())}"
                
                # Invoke the tool
                try:
                    result = self._invoke_tool_sync(tool_name, tool_args)
                    if DEBUG:
                        print(f"[DEBUG] Tool result: {str(result)[:200]}...")
                    
                    conversation_context.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": result
                    })
                    
                    # Update user message with tool result
                    user_msg = json.dumps({
                        "user_question": user_question,
                        "conversation": conversation_context
                    })
                    
                except Exception as e:
                    return f"❌ Error invoking tool '{tool_name}': {e}"
            
            # Check if this is a final response
            elif "final_response" in parsed:
                resp = parsed["final_response"]
                
                if DEBUG:
                    print(f"[DEBUG] Final response received")
                
                # Format the response nicely
                output = []
                output.append("## 🔍 Analysis")
                output.append(resp.get("analysis", "N/A"))
                output.append("\n## 💡 Recommendation")
                output.append(resp.get("recommendation", "N/A"))
                
                if resp.get("kubectl"):
                    output.append("\n## 🔧 Suggested Command")
                    output.append(f"```bash\n{resp.get('kubectl')}\n```")
                
                if resp.get("post_checks"):
                    output.append("\n## ✅ Post-Checks")
                    for check in resp["post_checks"]:
                        output.append(f"- {check}")
                
                output.append(f"\n*Confidence: {resp.get('confidence', 0.0):.0%}*")
                
                return "\n".join(output)
            
            else:
                return f"❌ Error: AI returned unexpected format:\n{json.dumps(parsed, indent=2)}"
        
        return f"❌ Error: Reached maximum conversation steps ({max_steps}) without a final response. The AI may be stuck in a loop."