# SmartVenue AI — Skills Catalog
> Framework: **RICE** (Role · Intent · Context · Execution)
> Version: 1.1 | Open Source & Doable Tasks Focus

Each skill is a self-contained, accessible capability module designed to be implemented using free, open-source software (FOSS) and simple heuristics. Heavy machine learning and complex pipelines have been replaced with achievable, high-value systems easily built within a hackathon or by a small team.

---

## Skill Index

| ID | Skill Name | Layer | Trigger |
|---|---|---|---|
| `SK-01` | Simple Crowd Density Estimator | Sensing | Every 30s tick |
| `SK-02` | Heuristic Queue Predictor | Logic | Every 60s tick |
| `SK-03` | Basic Indoor Routing | Routing | On attendee request |
| `SK-04` | Notification Bounty Push | Decision | Queue wait > 10 min |
| `SK-05` | Moving-Average Anomaly Detector | Sensing | Every 30s tick |
| `SK-06` | Scheduled Egress Announcer | Coordination | T-10 min to end |
| `SK-07` | FOSS Alert Dispatcher | Coordination | Alert rule triggered |
| `SK-08` | Accessibility Filter | Routing | Accessibility mode ON |
| `SK-09` | Event State Machine | Orchestration | Time/manual trigger |
| `SK-10` | Markdown Post-Event Reporter | Analytics | End of Event |

---

## SK-01 · Simple Crowd Density Estimator

### R — Role
Translate raw Wi-Fi probe requests (e.g., via ESP32 sniffers) and basic camera headcount into a simple occupancy percentage (0.0-1.0) for a zone.

### I — Intent
Provide a "good enough" density estimate without complex sensor fusion. Use lightweight open-source models like YOLOv8n (nano) for cameras or basic MAC address counting via scapy/airodump-ng for Wi-Fi. Fast, simple, and runs locally.

### C — Context
```yaml
Flexible Live Event Inputs:
  - Web App Manual Poll: Staff update counts via their phones using our React dashboard.
  - Camera Feed (Optional): Local CCTV feed piped loosely into OpenCV/YOLO.
  - Webhooks/Barcodes (Optional): Ticket scanner apps emitting JSON counts.

Zone config (SQLite/JSON):
  - max_capacity: int
```

### E — Execution
```python
# Runs every 30 seconds

def estimate_density(zone_id: str):
    # 1. Simple Wi-Fi Unique MACs (5 min window)
    wifi_count = count_recent_unique_macs(zone_id, minutes=5)
    
    # 2. Open-source YOLO camera headcount (if available)
    camera_count = get_yolov8_headcount(zone_id) 
    
    # Simple heuristic: prioritize camera, fallback to Wi-Fi estimate
    estimated_people = camera_count if camera_count is not None else (wifi_count * 1.5)
    
    density = min(estimated_people / get_zone_capacity(zone_id), 1.0)
    
    mqtt_publish(f"venue/crowd/density/{zone_id}", {
        "density": round(density, 2),
        "timestamp": now()
    })
    return density
```

---

## SK-02 · Heuristic Queue Predictor

### R — Role
Predict wait times at points of interest (restrooms, food stands) using simple arithmetic instead of heavy ML models.

### I — Intent
Use Little's Law heuristics: `wait_time = number_in_queue * average_service_time`. This is easy to calculate, transparent to debug, and requires minimal data.

### C — Context
```yaml
Params:
  - queue_length: int (from SK-01 camera feed or manual staff input)
  - avg_service_time_seconds: int (e.g., 45 sec per food order, 20 sec per restroom)
```

### E — Execution
```python
def predict_queue_wait(point_id: str):
    queue_length = get_current_headcount(point_id)
    service_time = get_config(point_id).get('service_time_sec', 30)
    
    wait_minutes = (queue_length * service_time) / 60.0
    
    mqtt_publish(f"venue/queue/{point_id}", {
        "wait_minutes": round(wait_minutes, 1)
    })
    
    if wait_minutes > 10:
        trigger_event("queue_overload", point_id)
        
    return wait_minutes
```

---

## SK-03 · Basic Indoor Routing

### R — Role
Provide static pathfinding using a simplified Python node graph of the venue zones.

### I — Intent
Instead of a heavy GIS stack, use the `networkx` Python library. Represent zones as nodes and distances as edge weights. Temporarily remove highly congested edges to reroute crowds.

### C — Context
```yaml
Graph: Python NetworkX graph loaded from a local JSON mapping.
Nodes: Zones or junctions.
Edges: Connections between zones, with distance as weight.
```

### E — Execution
```python
import networkx as nx

def compute_route(start_node: str, end_node: str):
    graph = load_venue_graph() 
    
    # Temporarily remove congested edges to automatically divert crowd
    for edge in list(graph.edges):
        if get_zone_density(edge[0]) > 0.8 or get_zone_density(edge[1]) > 0.8:
            graph.remove_edge(*edge)
            
    try:
        path = nx.shortest_path(graph, source=start_node, target=end_node, weight='distance')
        return format_path_to_instructions(path)
    except nx.NetworkXNoPath:
        return "No clear route available. Follow staff directions."
```

---

## SK-04 · Notification Bounty Push

### R — Role
When a queue gets too long, trigger a webhook to broadcast an open-source push notification offering an alternative spot.

### I — Intent
Use straightforward tools like `ntfy.sh` (self-hosted push notifications) to communicate. "Food Stand A is busy, go to Food Stand B for shorter wait!"

### C — Context
```yaml
Trigger: SK-02 "queue_overload" event
Action: Send HTTP POST to a free ntfy.sh topic.
```

### E — Execution
```python
import requests

def send_bounty_push(overloaded_point: str):
    alternative = find_shortest_queue_category(get_category(overloaded_point))
    
    if alternative:
        message = f"Queue at {overloaded_point} is long! Try {alternative} instead for a faster wait."
        
        # Using ntfy.sh (open source free push notifications)
        requests.post(
            "https://ntfy.sh/smartvenue_alerts",
            data=message.encode('utf-8'),
            headers={
                "Title": "Queue Alert & Fast Track Offer",
                "Tags": "fast_forward,ticket"
            }
        )
```

---

## SK-05 · Moving-Average Anomaly Detector

### R — Role
Monitor density using a statistical rolling average. Detect sudden surges instantly.

### I — Intent
Compare the current density against the average density of the last 10 minutes. If it spikes by more than 30% suddenly, trigger an alert. Simple math, completely deterministic.

### C — Context
```yaml
Data source: Short-term rolling buffer (in memory or local SQLite).
Threshold spike: > 0.30 increase compared to rolling average.
```

### E — Execution
```python
def check_anomaly(zone_id: str, new_density: float):
    recent_densities = get_recent_readings(zone_id, minutes=10)
    
    if len(recent_densities) > 5:
        avg_density = sum(recent_densities) / len(recent_densities)
        
        if (new_density - avg_density) > 0.3:
            dispatch_alert(
                severity="critical", 
                message=f"Sudden crowd surge in {zone_id}! (Avg: {avg_density:.2f}, Now: {new_density:.2f})"
            )
            return True
            
    return False
```

---

## SK-06 · Scheduled Egress Announcer

### R — Role
Coordinate crowd exiting by playing predetermined Text-To-Speech audio based on zone densities.

### I — Intent
Forget perfectly predicting egress via ML. Just use a basic script: if Gate A is busy but Gate B is empty, broadcast a message urging attendees to use Gate B.

### C — Context
```yaml
Audio: Play pre-generated `.wav` files via standard terminal audio commands.
```

### E — Execution
```python
import os
import requests

def run_egress_announcements():
    best_gate = get_least_crowded_gate()
    
    if get_zone_density(best_gate) < 0.5:
        # Play a local audio file over connected speakers
        os.system(f"aplay /assets/audio/use_gate_{best_gate}.wav")
        
        # Push mobile notification using ntfy
        requests.post(
            "https://ntfy.sh/smartvenue_egress", 
            data=f"To exit quickly, please proceed towards Gate {best_gate}."
        )
```

---

## SK-07 · FOSS Alert Dispatcher

### R — Role
Take any system alert and route it to human staff instantly.

### I — Intent
Use the `Apprise` open-source library to send alerts to Discord, Slack, Matrix, or email using one line of code.

### C — Context
```yaml
Tool: Python Apprise package (https://github.com/caronc/apprise)
```

### E — Execution
```python
import apprise

def dispatch_alert(severity: str, message: str):
    apobj = apprise.Apprise()
    
    # E.g., configuring a free Discord or Slack webhook for staff
    apobj.add('discord://webhook_id/webhook_token')
    
    if severity == "critical":
        apobj.notify(
            body=message,
            title="CRITICAL: SmartVenue Alert",
        )
    else:
        log_to_file(severity, message)
```

---

## SK-08 · Accessibility Filter

### R — Role
Provide accessible routes for users with mobility aids.

### I — Intent
A direct extension to SK-03's NetworkX graph. Drop edges from the pathfinding graph that are artificially marked with `has_stairs`. Overwhelmingly simple but effective.

### C — Context
```yaml
Graph: NetworkX JSON where edges have an attribute {"has_stairs": true/false}
```

### E — Execution
```python
def compute_accessible_route(start_node: str, end_node: str):
    graph = load_venue_graph() 
    
    # Permanently ignore inaccessible routes
    for edge_id, edge_data in list(graph.edges(data=True)):
        if edge_data.get('has_stairs', False):
            graph.remove_edge(*edge_id)
            
    try:
        path = nx.shortest_path(graph, source=start_node, target=end_node)
        return format_path_to_instructions(path)
    except nx.NetworkXNoPath:
        return "No accessible path found automatically. Please see nearby staff."
```

---

## SK-09 · Event State Machine

### R — Role
Track the current logic mode of the event (Pre_Event, Live, Egress). 

### I — Intent
A lightweight Python dictionary-backed state machine prevents logic from misfiring at inappropriate times.

### E — Execution
```python
current_state = "PRE_EVENT"
valid_transitions = {
    "PRE_EVENT": ["LIVE"],
    "LIVE": ["EGRESS"],
    "EGRESS": ["POST_EVENT"],
    "POST_EVENT": ["PRE_EVENT"]
}

def transition_state(new_state: str):
    global current_state
    if new_state in valid_transitions[current_state]:
        current_state = new_state
        print(f"System transitioned to {current_state}")
    else:
        print(f"Error: Invalid transition from {current_state} to {new_state}")
```

---

## SK-10 · Markdown Post-Event Reporter

### R — Role
Generate an end-of-event summary.

### I — Intent
Query a local SQLite database and format a neat Markdown file outlining maximum crowds and events, requiring no cloud resources or reporting engines.

### E — Execution
```python
def generate_end_of_day_report():
    sqlite_db = connect("venue_logs.db")
    
    max_density = sqlite_db.execute("SELECT max(density) FROM sensor_logs").fetchone()[0]
    total_alerts = sqlite_db.execute("SELECT count(*) FROM alerts").fetchone()[0]
    
    report_md = f"""
# Event Post-Mortem Report

- **Max Recorded Density**: {max_density}%
- **Total Alerts Issued**: {total_alerts}

*Generated locally via SQLite.*
    """
    
    with open(f"reports/report_{now().date()}.md", "w") as file:
        file.write(report_md)
```