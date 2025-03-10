from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
import httpx
import os
from openai import OpenAI
import asyncio

# Load environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")

# Initialize FastAPI
app = FastAPI(title="System Status Dashboard")
client = OpenAI(api_key=openai_api_key)

# Prometheus URL
PROMETHEUS_URL = (
    "http://prometheus-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090"
)


async def fetch_prometheus_metrics():
    """Fetch key metrics from Prometheus"""
    async with httpx.AsyncClient() as client:
        metrics = {}

        # RPS (requests per second)
        rps_query = (
            "sum(rate(nginx_ingress_controller_nginx_process_requests_total[1m]))"
        )
        response = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": rps_query}
        )
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "success" and data["data"]["result"]:
                metrics["rps"] = float(data["data"]["result"][0]["value"][1])
            else:
                metrics["rps"] = 0

        # CPU Usage
        cpu_query = (
            'sum(rate(container_cpu_usage_seconds_total{pod=~"proxy-node.*"}[1m]))'
        )
        response = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": cpu_query}
        )
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "success" and data["data"]["result"]:
                metrics["cpu"] = float(data["data"]["result"][0]["value"][1])
            else:
                metrics["cpu"] = 0

        # Active Nodes
        nodes_query = 'count(kube_pod_info{pod=~"proxy-node.*"})'
        response = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": nodes_query}
        )
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "success" and data["data"]["result"]:
                metrics["active_nodes"] = int(
                    float(data["data"]["result"][0]["value"][1])
                )
            else:
                metrics["active_nodes"] = 0

        # Latency (95th percentile)
        latency_query = "histogram_quantile(0.95, sum(rate(nginx_ingress_controller_request_duration_seconds_bucket[1m])) by (le))"
        response = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": latency_query}
        )
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "success" and data["data"]["result"]:
                metrics["latency_p95"] = float(data["data"]["result"][0]["value"][1])
            else:
                metrics["latency_p95"] = 0

        return metrics


def generate_status_overview(metrics):
    """Generate a system status overview using ChatGPT"""
    prompt = f"""
    Current system metrics:
    - Requests per second: {metrics.get('rps', 'N/A')} RPS
    - CPU usage: {metrics.get('cpu', 'N/A')} cores
    - Active proxy nodes: {metrics.get('active_nodes', 'N/A')}
    - 95th percentile latency: {metrics.get('latency_p95', 'N/A')*1000:.1f} ms
    """

    system_prompt = """
    You are a system monitoring expert. Generate a concise HTML summary of the system status based on the metrics provided.
    Include:
    1. An overall health assessment (Good, Warning, Critical)
    2. Key observations about the metrics
    3. Any potential issues or bottlenecks
    4. Brief recommendations if needed
    
    Keep your response under 300 words, formatted as clean HTML with minimal styling.
    Use <div>, <h3>, <p>, and <ul> tags for structure.
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=500,
    )

    return response.choices[0].message.content


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    """Status endpoint serving HTML overview"""
    try:
        metrics = await fetch_prometheus_metrics()
        overview_html = generate_status_overview(metrics)

        # Wrap in a basic HTML structure
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>System Status Dashboard</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                .good {{ color: green; }}
                .warning {{ color: orange; }}
                .critical {{ color: red; }}
                .metrics {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>System Status Overview</h1>
                <div class="metrics">
                    <h3>Current Metrics</h3>
                    <ul>
                        <li>Requests per second: {metrics.get('rps', 'N/A')} RPS</li>
                        <li>CPU usage: {metrics.get('cpu', 'N/A')} cores</li>
                        <li>Active proxy nodes: {metrics.get('active_nodes', 'N/A')}</li>
                        <li>95th percentile latency: {metrics.get('latency_p95', 'N/A')*1000:.1f} ms</li>
                    </ul>
                </div>
                <div class="analysis">
                    {overview_html}
                </div>
                <p><small>Last updated: {asyncio.get_event_loop().time()}</small></p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=full_html)
    except Exception as e:
        return HTMLResponse(
            content=f"""
        <html>
            <body>
                <h1>Error</h1>
                <p>Could not generate system status: {str(e)}</p>
            </body>
        </html>
        """
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
