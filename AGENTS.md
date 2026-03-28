# AGENTS.md

## Project Overview

ESP32-CAM person counting system with real-time video streaming, YOLO-based person detection, pan/tilt servo control, and a web dashboard.

### Architecture

```
ESP32-S3 (MicroPython)  →  MJPEG stream  →  OpenCV Container (YOLO detection)
                                        ↕  MQTT (Mosquitto)
                           Web Container (Flask + SQLite)  →  Browser Dashboard
```

**Components:**
- `main.py`, `boot.py` — ESP32 firmware (MicroPython): camera streaming + servo control
- `opencv/app.py` — YOLO person detection, face tracking, MQTT publisher
- `opencv/counting.py` — Person counter with session statistics
- `opencv/alerts.py` — Alert manager (webhook + email SMTP)
- `web/app.py` — Flask API with SQLite auth, people history, alerts
- `web/static/` — Frontend HTML/CSS/JS with Chart.js dashboard

---

## Build / Run Commands

```bash
# Start all services
docker compose up --build

# Start a single service
docker compose up --build opencv
docker compose up --build web
docker compose up mqtt

# Stop all
docker compose down

# View logs
docker compose logs -f opencv
docker compose logs -f web
```

**ESP32 firmware** (MicroPython, deployed via Thonny or ampy):
```bash
# Upload to ESP32
ampy --port /dev/ttyUSB0 put boot.py
ampy --port /dev/ttyUSB0 put main.py
```

---

## Testing

No formal test framework is configured. Manual testing approach:

```bash
# Test ESP32 stream directly
curl http://<ESP32_IP>:81/stream --output test.jpg

# Test OpenCV stream
curl http://localhost:5001/stream --output test.jpg

# Test web API
curl http://localhost:8080/api/state
curl http://localhost:8080/api/people
curl http://localhost:8080/api/alerts

# Test MQTT messages
mosquitto_sub -t "esp32cam/#" -v
```

---

## Code Style Guidelines

### Python (Flask + OpenCV services)

**Imports order:**
1. Standard library (`os`, `json`, `time`, `threading`)
2. Third-party (`cv2`, `numpy`, `flask`, `paho.mqtt.client`)
3. Local modules (`counting`, `alerts`)

```python
import json
import os
import time

import cv2
import numpy as np
from flask import Flask, jsonify

from counting import PersonCounter
```

**Naming conventions:**
- Variables/functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Classes: `PascalCase`
- Environment variables: `UPPER_SNAKE_CASE` via `os.getenv("VAR", "default")`

**Type hints:** Optional but encouraged for public functions:
```python
def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))
```

**Error handling:**
```python
try:
    result = risky_operation()
except Exception as e:
    print(f"[CONTEXT] Erreur: {e}", flush=True)
```

**MQTT topics:** `esp32cam/{cmd|status}/{topic}` pattern

### JavaScript (Frontend)

- `camelCase` for variables/functions
- `const` preferred over `let`
- Async/await for API calls
- Fetch API with error handling

### CSS

- CSS custom properties in `:root`
- BEM-like naming for components
- `rgba()` for transparency

---

## Environment Variables

All config via `.env` file (see `.env-example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ESP32_IP` | `192.168.1.83` | ESP32 camera IP address |
| `MQTT_BROKER` | `mqtt` | MQTT broker hostname |
| `YOLO_CONF` | `0.45` | YOLO confidence threshold |
| `ALERT_THRESHOLD` | `5` | Person count alert trigger |
| `ALERT_COOLDOWN` | `300` | Seconds between alerts |

---

## Key Technical Notes

- **YOLO model:** `yolov8n.pt` (nano, 3.2MB) — optimized for CPU inference
- **Detection:** Only class 0 (person) from COCO dataset
- **Servos:** GPIO pins 1 and 2 on ESP32-S3 (avoid 13/15 used by camera)
- **MQTT JSON payloads:** `{"ts": float, "count": int, "faces": [...]}`
- **SQLite tables:** `users`, `people_counts`, `alerts`

---

## Common Tasks

**Change detection confidence:**
```env
YOLO_CONF=0.6  # Higher = fewer false positives
```

**Configure Telegram alerts:**
```env
ALERT_WEBHOOK_URL=https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>
```

**Debug OpenCV container:**
```bash
docker compose exec opencv python -c "from ultralytics import YOLO; print(YOLO('yolov8n.pt'))"
```
