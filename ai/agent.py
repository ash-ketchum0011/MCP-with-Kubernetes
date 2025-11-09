# ai/agent.py
import json
import asyncio
import os
from typing import Dict, Any
from mcp.server import LocalMCP, list_tools
from dotenv import load_dotenv

load_dotenv()

# Enhanced system prompt with YAML generation capability
SYSTEM_PROMPT = """You are a Kubernetes SRE assistant that helps diagnose cluster issues and generate Kubernetes manifests.

CRITICAL: You MUST respond with ONLY valid JSON. No markdown, no explanations, ONLY JSON.

Two response formats:

1) To call a tool:
{{"tool_call": {{"name": "TOOL_NAME", "args": {{}}}}}}

2) To give final answer:
{{"final_response": {{"analysis": "...", "recommendation": "...", "kubectl": "...", "yaml": "...", "confidence": 0.9, "post_checks": [...]}}}}

Available tools: {tools}

ENHANCED TROUBLESHOOTING METHODOLOGY:

**Step 1: Get Overview**
- Use get_cluster_health_summary() first for high-level cluster status

**Step 2: Diagnose by Problem Type**

A) POD ISSUES (crash, restart, OOM):
   1. get_pods() → identify failing pods
   2. get_pod_logs() → find error messages
   3. get_pod_metrics() → check resource usage
   4. get_cluster_events() → check OOMKilled, ImagePull failures
   5. check_pod_config_references() → verify configs exist

B) NETWORKING ISSUES (connection refused, timeout, DNS):
   1. get_services() → verify service exists
   2. get_endpoints() → CHECK IF SERVICE HAS BACKING PODS (critical!)
   3. get_network_policies() → check for traffic blocking rules
   4. get_ingresses() → check external access configuration

C) STORAGE ISSUES (pending PVC, volume mount failures):
   1. get_persistent_volume_claims() → check PVC status
   2. get_persistent_volumes() → check PV availability

D) CONFIGURATION ISSUES (ConfigMap/Secret not found):
   1. get_configmaps() → verify ConfigMap exists
   2. get_secrets() → verify Secret exists (shows keys only)
   3. check_pod_config_references() → find which configs are missing

E) SCHEDULING/RESOURCE ISSUES (pod pending, nodes full):
   1. get_node_details() → check node capacity and conditions
   2. get_resource_quotas() → check if quotas are maxed out

F) PERMISSION ISSUES (Forbidden, Unauthorized):
   1. check_service_account_permissions() → verify RBAC setup
   2. get_cluster_events() → look for permission denied events

**Common Patterns:**
- Service 503/502 → get_endpoints → NO endpoints → check backing pods
- Connection timeout → get_network_policies → policy blocking traffic
- Pod pending → get_node_details → nodes at capacity OR get_persistent_volume_claims → PVC pending
- ConfigMap error → check_pod_config_references → ConfigMap missing
- Forbidden errors → check_service_account_permissions → no RBAC bindings

**YAML GENERATION CAPABILITY:**
When user asks for YAML/manifest/configuration:
- Generate complete, valid Kubernetes YAML
- Include all required fields (apiVersion, kind, metadata, spec)
- Use best practices (labels, resource limits, probes)
- Add helpful comments
- Return in the "yaml" field of final_response
- Set kubectl command to "kubectl apply -f <filename>"

YAML EXAMPLES:
User: "create yaml for service account my-sa in namespace default"
You: {{"final_response": {{
  "analysis": "Generated ServiceAccount YAML for 'my-sa' in 'default' namespace with standard labels",
  "recommendation": "Review and apply. Add RoleBindings as needed for permissions.",
  "kubectl": "kubectl apply -f serviceaccount.yaml",
  "yaml": "apiVersion: v1\\nkind: ServiceAccount\\nmetadata:\\n  name: my-sa\\n  namespace: default\\n  labels:\\n    app: my-sa",
  "confidence": 1.0,
  "post_checks": ["kubectl get sa my-sa -n default"]
}}}}

**Tool Selection Rules:**
- Always check service endpoints before assuming network issue
- Always check PVC status if pod is pending with volume
- Use get_cluster_health_summary for "what's wrong?" questions
- For YAML generation, skip tools and generate directly

**kubectl Command Guidelines:**
- Include namespace: -n <namespace>
- Prefer diagnostic commands: describe, logs, get, top
- Avoid destructive: delete, apply (except for generated YAML)
- Format for copy-paste: single line, executable

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
                
                # Handle YAML output if present
                if resp.get("yaml"):
                    output.append("\n## 📄 Generated YAML")
                    yaml_content = resp.get("yaml", "")
                    # Unescape newlines
                    yaml_content = yaml_content.replace("\\n", "\n")
                    output.append(f"```yaml\n{yaml_content}\n```")
                
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