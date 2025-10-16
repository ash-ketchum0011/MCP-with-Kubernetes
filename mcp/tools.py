# mcp/tools.py
import re
from datetime import datetime
from kubernetes import client, config
from mcp.server import tool

# Initialize Kubernetes client
try:
    config.load_kube_config()
except:
    # Fallback to in-cluster config if running inside k8s
    try:
        config.load_incluster_config()
    except:
        print("Warning: Could not load Kubernetes config")

v1 = client.CoreV1Api()
custom = client.CustomObjectsApi()
apps_v1 = client.AppsV1Api()


def _ts_to_iso(ts):
    """Convert kubernetes timestamp to ISO string."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


@tool()
async def get_pods(namespace: str = "default"):
    """List all pods in a namespace with their status."""
    try:
        pods = v1.list_namespaced_pod(namespace)
    except Exception as e:
        return {"error": f"failed to list pods: {e}"}
    
    out = []
    for pod in pods.items:
        status = "Unknown"
        if pod.status.phase:
            status = pod.status.phase
        
        containers_ready = 0
        total_containers = len(pod.spec.containers)
        if pod.status.container_statuses:
            containers_ready = sum(1 for c in pod.status.container_statuses if c.ready)
        
        out.append({
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "status": status,
            "ready": f"{containers_ready}/{total_containers}",
            "restarts": sum(c.restart_count for c in (pod.status.container_statuses or [])),
            "age": _ts_to_iso(pod.metadata.creation_timestamp)
        })
    return {"pods": out}


@tool()
async def get_pod_logs(pod_name: str, namespace: str = "default", tail_lines: int = 200):
    """Get and sanitize recent logs for a pod"""
    try:
        raw = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=tail_lines)
    except Exception as e:
        return {"error": f"failed to fetch logs: {e}"}
    
    sanitized = re.sub(r"[A-Fa-f0-9]{30,}", "[REDACTED_TOKEN]", raw)
    sanitized = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "[REDACTED_IP]", sanitized)
    sanitized = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w{2,}\b", "[REDACTED_EMAIL]", sanitized)
    
    if len(sanitized) > 50_000:
        sanitized = sanitized[-50_000:]
    
    return {"pod": pod_name, "namespace": namespace, "logs": sanitized}


@tool()
async def get_pod_metrics(pod_name: str, namespace: str = "default"):
    """Fetch current CPU/memory via metrics.k8s.io (metrics-server) if available."""
    try:
        resp = custom.get_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
            name=pod_name
        )
        mem_bytes = 0
        cpu_millis = 0
        for c in resp.get("containers", []):
            usage = c.get("usage", {})
            mem = usage.get("memory")
            cpu = usage.get("cpu")
            
            if mem:
                if mem.endswith("Ki"):
                    mem_bytes += int(float(mem[:-2]) * 1024)
                elif mem.endswith("Mi"):
                    mem_bytes += int(float(mem[:-2]) * 1024 * 1024)
                elif mem.endswith("Gi"):
                    mem_bytes += int(float(mem[:-2]) * 1024 * 1024 * 1024)
                else:
                    try:
                        mem_bytes += int(mem)
                    except:
                        pass
            
            if cpu:
                if cpu.endswith("m"):
                    cpu_millis += int(cpu[:-1])
                else:
                    cpu_millis += int(float(cpu) * 1000)
        
        return {"pod": pod_name, "namespace": namespace, "memory_bytes": mem_bytes, "cpu_milli": cpu_millis}
    except Exception as e:
        return {"error": "metrics API not available (metrics-server missing?)", "details": str(e)}


@tool()
async def get_cluster_events(namespace: str = "default", limit: int = 50):
    """Return recent cluster events for the namespace"""
    try:
        evs = v1.list_namespaced_event(namespace)
    except Exception as e:
        return {"error": f"failed to list events: {e}"}
    
    out = []
    for e in evs.items[:limit]:
        out.append({
            "type": e.type,
            "reason": e.reason,
            "message": e.message,
            "lastTimestamp": _ts_to_iso(e.last_timestamp)
        })
    return {"events": out}


@tool()
async def get_deployments(namespace: str = "default"):
    """List all deployments in a namespace."""
    try:
        deps = apps_v1.list_namespaced_deployment(namespace)
    except Exception as e:
        return {"error": f"failed to list deployments: {e}"}
    
    out = []
    for dep in deps.items:
        out.append({
            "name": dep.metadata.name,
            "namespace": dep.metadata.namespace,
            "replicas": dep.spec.replicas,
            "ready": dep.status.ready_replicas or 0,
            "available": dep.status.available_replicas or 0,
            "age": _ts_to_iso(dep.metadata.creation_timestamp)
        })
    return {"deployments": out}


@tool()
async def get_services(namespace: str = "default"):
    """List all services in a namespace."""
    try:
        svcs = v1.list_namespaced_service(namespace)
    except Exception as e:
        return {"error": f"failed to list services: {e}"}
    
    out = []
    for svc in svcs.items:
        out.append({
            "name": svc.metadata.name,
            "namespace": svc.metadata.namespace,
            "type": svc.spec.type,
            "cluster_ip": svc.spec.cluster_ip,
            "ports": [{"port": p.port, "protocol": p.protocol} for p in (svc.spec.ports or [])]
        })
    return {"services": out}