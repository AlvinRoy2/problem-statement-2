import requests
import time
import random
import logging

import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

API_URL = os.getenv("API_URL", "http://localhost:8000/api")

def get_active_zones():
    try:
        res = requests.get(f"{API_URL}/admin/state", timeout=3)
        if res.status_code == 200:
            return list(res.json().get('zones', {}).keys())
    except Exception:
        pass
    return []

def simulate():
    logging.info("Starting FOSS Hardware Simulator (Dynamic Edition)...")
    while True:
        active_zones = get_active_zones()
        
        if not active_zones:
            logging.warning("No zones registered dynamically yet. Waiting...")
            time.sleep(5)
            continue
            
        for zone in active_zones:
            headcount = random.randint(10, 800)
            try:
                # Inject anomaly edge-cases dynamically (10% chance)
                if random.random() > 0.9:
                    headcount += random.randint(100, 300)
                    
                requests.post(f"{API_URL}/admin/simulate_crowd?zone_id={zone}&headcount={headcount}", timeout=2)
                logging.debug(f"Simulated {zone}: {headcount} pax")
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to reach API server. Is Uvicorn running?")
                
        # Simulate traffic every 5 seconds for visual responsiveness
        time.sleep(5)

if __name__ == "__main__":
    simulate()
