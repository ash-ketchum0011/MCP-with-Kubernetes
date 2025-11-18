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
async def get_pods(namespace: str = "default", **kwargs):
    """List all pods in a namespace with their status.
    
    Args:
        namespace: The namespace to list pods from (default: "default")
    """
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
async def get_pod_logs(pod_name: str = None, namespace: str = "default", tail_lines: int = 200, pod: str = None, **kwargs):
    """Get and sanitize recent logs for a pod.
    
    Args:
        pod_name: Name of the pod to get logs from (alias: pod)
        namespace: The namespace of the pod (default: "default")
        tail_lines: Number of lines to retrieve (default: 200)
    """
    # Handle both parameter names for flexibility
    actual_pod_name = pod_name or pod
    if not actual_pod_name:
        return {"error": "pod_name or pod parameter is required"}
    
    try:
        raw = v1.read_namespaced_pod_log(name=actual_pod_name, namespace=namespace, tail_lines=tail_lines)
    except Exception as e:
        return {"error": f"failed to fetch logs: {e}"}
    
    sanitized = re.sub(r"[A-Fa-f0-9]{30,}", "[REDACTED_TOKEN]", raw)
    sanitized = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "[REDACTED_IP]", sanitized)
    sanitized = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w{2,}\b", "[REDACTED_EMAIL]", sanitized)
    
    if len(sanitized) > 50_000:
        sanitized = sanitized[-50_000:]
    
    return {"pod": actual_pod_name, "namespace": namespace, "logs": sanitized}


@tool()
async def get_pod_metrics(pod_name: str = None, namespace: str = "default", pod: str = None, **kwargs):
    """Fetch current CPU/memory via metrics.k8s.io (metrics-server) if available.
    
    Args:
        pod_name: Name of the pod to get metrics for (alias: pod)
        namespace: The namespace of the pod (default: "default")
    """
    # Handle both parameter names for flexibility
    actual_pod_name = pod_name or pod
    if not actual_pod_name:
        return {"error": "pod_name or pod parameter is required"}
    
    try:
        resp = custom.get_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
            name=actual_pod_name
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
        
        return {"pod": actual_pod_name, "namespace": namespace, "memory_bytes": mem_bytes, "cpu_milli": cpu_millis}
    except Exception as e:
        return {"error": "metrics API not available (metrics-server missing?)", "details": str(e)}


@tool()
async def get_cluster_events(namespace: str = "default", limit: int = 50, **kwargs):
    """Return recent cluster events for the namespace.
    
    Args:
        namespace: The namespace to get events from (default: "default")
        limit: Maximum number of events to return (default: 50)
    """
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
async def get_deployments(namespace: str = "default", **kwargs):
    """List all deployments in a namespace.
    
    Args:
        namespace: The namespace to list deployments from (default: "default")
    """
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
async def get_services(namespace: str = "default", **kwargs):
    """List all services in a namespace.
    
    Args:
        namespace: The namespace to list services from (default: "default")
    """
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


@tool()
async def get_pod_details(pod_name: str = None, namespace: str = "default", pod: str = None, **kwargs):
    """Get detailed information about a specific pod including status, conditions, and container states.
    
    Args:
        pod_name: Name of the pod to get details for (alias: pod)
        namespace: The namespace of the pod (default: "default")
    """
    # Handle both 'pod_name' and 'pod' parameter names
    actual_pod_name = pod_name or pod
    if not actual_pod_name:
        return {"error": "pod_name or pod parameter is required"}
    
    try:
        pod_obj = v1.read_namespaced_pod(name=actual_pod_name, namespace=namespace)
    except Exception as e:
        return {"error": f"failed to get pod details: {e}"}
    
    # Container statuses
    container_states = []
    if pod_obj.status.container_statuses:
        for cs in pod_obj.status.container_statuses:
            state_info = {}
            if cs.state.waiting:
                state_info = {
                    "state": "waiting",
                    "reason": cs.state.waiting.reason or "Unknown",
                    "message": cs.state.waiting.message or ""
                }
            elif cs.state.running:
                state_info = {
                    "state": "running",
                    "started_at": _ts_to_iso(cs.state.running.started_at)
                }
            elif cs.state.terminated:
                state_info = {
                    "state": "terminated",
                    "reason": cs.state.terminated.reason or "Unknown",
                    "message": cs.state.terminated.message or "",
                    "exit_code": cs.state.terminated.exit_code
                }
            
            container_states.append({
                "name": cs.name,
                "ready": cs.ready,
                "restart_count": cs.restart_count,
                "image": cs.image,
                **state_info
            })
    
    # Pod conditions
    conditions = []
    if pod_obj.status.conditions:
        for cond in pod_obj.status.conditions:
            conditions.append({
                "type": cond.type,
                "status": cond.status,
                "reason": cond.reason or "",
                "message": cond.message or "",
                "last_transition_time": _ts_to_iso(cond.last_transition_time)
            })
    
    return {
        "pod": actual_pod_name,
        "namespace": namespace,
        "phase": pod_obj.status.phase,
        "node": pod_obj.spec.node_name or "Not assigned",
        "host_ip": pod_obj.status.host_ip or "N/A",
        "pod_ip": pod_obj.status.pod_ip or "N/A",
        "containers": container_states,
        "conditions": conditions,
        "created": _ts_to_iso(pod_obj.metadata.creation_timestamp)
    }


@tool()
async def get_namespaces(**kwargs):
    """List all namespaces in the cluster."""
    try:
        namespaces = v1.list_namespace()
    except Exception as e:
        return {"error": f"failed to list namespaces: {e}"}
    
    out = []
    for ns in namespaces.items:
        out.append({
            "name": ns.metadata.name,
            "status": ns.status.phase,
            "age": _ts_to_iso(ns.metadata.creation_timestamp)
        })
    return {"namespaces": out}


@tool()
async def get_nodes(**kwargs):
    """List all nodes in the cluster with their status and resources."""
    try:
        nodes = v1.list_node()
    except Exception as e:
        return {"error": f"failed to list nodes: {e}"}
    
    out = []
    for node in nodes.items:
        # Node conditions
        ready = "Unknown"
        if node.status.conditions:
            for cond in node.status.conditions:
                if cond.type == "Ready":
                    ready = cond.status
                    break
        
        # Resource capacity
        capacity = {}
        if node.status.capacity:
            capacity = {
                "cpu": node.status.capacity.get("cpu", "N/A"),
                "memory": node.status.capacity.get("memory", "N/A"),
                "pods": node.status.capacity.get("pods", "N/A")
            }
        
        # Resource allocatable
        allocatable = {}
        if node.status.allocatable:
            allocatable = {
                "cpu": node.status.allocatable.get("cpu", "N/A"),
                "memory": node.status.allocatable.get("memory", "N/A"),
                "pods": node.status.allocatable.get("pods", "N/A")
            }
        
        out.append({
            "name": node.metadata.name,
            "ready": ready,
            "capacity": capacity,
            "allocatable": allocatable,
            "age": _ts_to_iso(node.metadata.creation_timestamp),
            "version": node.status.node_info.kubelet_version if node.status.node_info else "Unknown"
        })
    return {"nodes": out}


@tool()
async def get_resource_quotas(namespace: str = "default", **kwargs):
    """Get resource quotas for a namespace.
    
    Args:
        namespace: The namespace to get quotas from (default: "default")
    """
    try:
        quotas = v1.list_namespaced_resource_quota(namespace)
    except Exception as e:
        return {"error": f"failed to list resource quotas: {e}"}
    
    out = []
    for quota in quotas.items:
        hard = {}
        used = {}
        
        if quota.status.hard:
            hard = dict(quota.status.hard)
        if quota.status.used:
            used = dict(quota.status.used)
        
        out.append({
            "name": quota.metadata.name,
            "namespace": namespace,
            "hard": hard,
            "used": used
        })
    return {"resource_quotas": out}


@tool()
async def get_persistent_volumes(**kwargs):
    """List all persistent volumes in the cluster."""
    try:
        pvs = v1.list_persistent_volume()
    except Exception as e:
        return {"error": f"failed to list persistent volumes: {e}"}
    
    out = []
    for pv in pvs.items:
        out.append({
            "name": pv.metadata.name,
            "capacity": pv.spec.capacity.get("storage", "N/A") if pv.spec.capacity else "N/A",
            "access_modes": pv.spec.access_modes or [],
            "status": pv.status.phase,
            "claim": f"{pv.spec.claim_ref.namespace}/{pv.spec.claim_ref.name}" if pv.spec.claim_ref else "Unbound",
            "storage_class": pv.spec.storage_class_name or "N/A"
        })
    return {"persistent_volumes": out}


@tool()
async def get_persistent_volume_claims(namespace: str = "default", **kwargs):
    """List all persistent volume claims in a namespace.
    
    Args:
        namespace: The namespace to list PVCs from (default: "default")
    """
    try:
        pvcs = v1.list_namespaced_persistent_volume_claim(namespace)
    except Exception as e:
        return {"error": f"failed to list persistent volume claims: {e}"}
    
    out = []
    for pvc in pvcs.items:
        out.append({
            "name": pvc.metadata.name,
            "namespace": namespace,
            "status": pvc.status.phase,
            "volume": pvc.spec.volume_name or "N/A",
            "capacity": pvc.status.capacity.get("storage", "N/A") if pvc.status.capacity else "N/A",
            "access_modes": pvc.spec.access_modes or [],
            "storage_class": pvc.spec.storage_class_name or "N/A"
        })
    return {"persistent_volume_claims": out}