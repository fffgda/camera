# AGENTS.md

## Architecture

```
ESP32-S3 → MJPEG stream → OpenCV (YOLO) ──MQTT───→ Web (Flask + SQLite) → Browser
               ↑                                      │
               └─────────────── MQTT ─────────────────┘  (pan/tilt commands)
```

**Components:**
- `main.py`, `boot.py` — ESP32 firmware (MicroPython)
- `opencv/app.py` — YOLO detection, MQTT publisher, MJPEG restream
- `opencv/counting.py` — Person counter
- `opencv/alerts.py` — Alert manager (webhook + SMTP)
- `web/app.py` — Flask API, SQLite auth, SSE dashboard
- `web/static/` — Frontend (Chart.js)

---

## Build / Run

```bash
docker compose up --build          # all services
docker compose up --build opencv    # single service
docker compose down                 # stop
docker compose logs -f opencv       # view logs
```

**MQTT must start first** — `opencv` and `web` depend on `mqtt: service_healthy`.

**ESP32 firmware** (MicroPython):
```bash
ampy --port /dev/ttyUSB0 put boot.py
ampy --port /dev/ttyUSB0 put main.py
```

---

## Key Config Pattern

Only **`ESP32_IP`** in `.env` needs changing when the camera IP changes. Everything else (MJPEG_URL, topics) is derived automatically in docker-compose.yml.

The ESP32 firmware (`main.py`) also needs the MQTT broker IP — it must be the **Docker host IP** (e.g. `172.16.8.1`), not the Docker bridge IP (`172.17.x.x`). See README "Pont MQTT Docker ↔ Réseau local" section.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ESP32_IP` | `172.16.8.69` | ESP32 camera IP (change this!) |
| `MQTT_BROKER` | `mqtt` | MQTT broker hostname |
| `YOLO_CONF` | `0.6` | YOLO confidence threshold |
| `DETECT_EVERY_N` | `3` | Process 1 frame every N |
| `DETECT_RESIZE` | `0.4` | Frame resize factor before detection |
| `JPEG_QUALITY` | `50` | MJPEG quality (5-95) |
| `MOTION_ENABLED` | `1` | Enable motion detection |
| `ALERT_THRESHOLD` | `5` | Trigger alert at this count |
| `ALERT_COOLDOWN` | `300` | Seconds between alerts |
| `FLASK_SECRET_KEY` | `change-this-secret` | Flask secret (set this!) |

---

## Technical Notes

- **YOLO model:** `yolov8n.pt` — detects class 0 (person) from COCO
- **MQTT topics:** `esp32cam/{cmd|status}/{pan|tilt|mode|faces|people|alerts}`
- **SQLite tables:** `users`, `people_counts`, `alerts`
- **Servo GPIO:** pins 1 and 2 (avoid 13/15 used by camera)
- **MJPEG restream:** OpenCV publishes processed stream on port 5001

---

## Testing

```bash
# Stream endpoints
curl http://localhost:5001/stream      # OpenCV processed stream
curl http://localhost:8080/health      # web health

# API
curl http://localhost:8080/api/state
curl http://localhost:8080/api/people
curl http://localhost:8080/api/alerts

# MQTT
mosquitto_sub -t "esp32cam/#" -v
```