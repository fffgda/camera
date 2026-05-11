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
- `nginx/nginx.conf` — Reverse-proxy TLS, HTTP→HTTPS redirect

---

## Build / Run

```bash
docker compose up --build           # all services
docker compose up --build nginx     # single service
docker compose down                 # stop
docker compose logs -f opencv       # view logs
```

**MQTT must start first** — `opencv` and `web` depend on `mqtt: service_healthy`.

**SSL certs are required before first build:**
```bash
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem -out nginx/ssl/cert.pem \
  -subj "/CN=localhost"
```

**ESP32 firmware** (MicroPython):
```bash
ampy --port /dev/ttyUSB0 put boot.py
ampy --port /dev/ttyUSB0 put main.py
```

---

## Key Config Pattern

Only **`ESP32_IP`** in `.env` needs changing when the camera IP changes. `MJPEG_URL` is derived automatically in docker-compose.yml — do NOT set both or the explicit var wins.

The ESP32 firmware (`main.py`) also needs the MQTT broker IP — it must be the **Docker host IP** (e.g. `172.16.8.1`), not the Docker bridge IP (`172.17.x.x`).

---

## Known Quirks

- **`nginx/ssl/` dir does not exist** in git — must be created manually (see above). Docker build fails without it.
- **Motion SSE events not wired** — OpenCV publishes `esp32cam/status/motion` but `web/app.py` never subscribes. The frontend listens for a `motion` SSE event that never arrives.
- **No direct `/stream` route in nginx** — video goes through Flask `/video` proxy. The OpenCV stream on port 5001 is only accessible inside Docker or via direct port mapping.
- **Main ESP32 entrypoint** is `main.py`, `boot.py` handles WiFi only (imports `wifi_config.py` which is gitignored).
- **PyTorch oneDNN thread crash** — `opencv/app.py` forces `torch.set_num_threads(1)` and disables mkldnn/nnpack to avoid SIGSEGV in container.

---

## Endpoints

| URL | Service | Notes |
|-----|---------|-------|
| `https://localhost/` | nginx → web | Dashboard (Flask) |
| `https://localhost/video` | nginx → web → opencv | MJPEG stream via Flask proxy |
| `https://localhost/api/events` | nginx → web | SSE (faces/people/alerts) |
| `http://localhost:5001/stream` | opencv | Direct stream (Docker host) |

---

## Testing

```bash
# Health
curl -k https://localhost/health
curl http://localhost:8080/health

# API (via nginx or direct)
curl -k https://localhost/api/state
curl http://localhost:8080/api/people

# MQTT
mosquitto_sub -t "esp32cam/#" -v

# MJPEG stream
curl -k https://localhost/video -o /dev/null
```
