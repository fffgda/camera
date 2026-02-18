import os
<<<<<<< Updated upstream
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
=======
import json
from threading import Lock

from flask import Flask, request, jsonify, send_from_directory
>>>>>>> Stashed changes
import paho.mqtt.client as mqtt

# =========================
# CONFIG
# =========================
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")
FACES_TOPIC = os.getenv("FACES_TOPIC", "esp32cam/status/faces")

<<<<<<< Updated upstream
OPENCV_STREAM_URL = os.getenv("OPENCV_STREAM_URL", "http://opencv:5001/stream")

STEP = int(os.getenv("STEP", "2"))   # pas servo
=======
STEP = int(os.getenv("STEP", "2"))
>>>>>>> Stashed changes
PAN_MIN, PAN_MAX = 0, 180
TILT_MIN, TILT_MAX = 0, 180

# =========================
# STATE
# =========================
state = {
    "pan": int(os.getenv("PAN_START", "90")),
    "tilt": int(os.getenv("TILT_START", "90")),
    "mode": "manual",
}

last_faces = {
    "ts": 0,
    "frame_w": 0,
    "frame_h": 0,
    "faces": []
}

faces_lock = Lock()

# =========================
# HELPERS
# =========================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# =========================
# MQTT CALLBACKS
# =========================
def on_faces_message(client, userdata, msg):
    global last_faces
    try:
        data = json.loads(msg.payload.decode(errors="ignore"))
        with faces_lock:
            last_faces = data
    except Exception as e:
        print("[WEB] Erreur parsing faces:", e, flush=True)

def on_message(client, userdata, msg):
    if msg.topic == FACES_TOPIC:
        on_faces_message(client, userdata, msg)

# =========================
# MQTT CLIENT
# =========================
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="WebUIClient")
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.subscribe(FACES_TOPIC)
client.loop_start()

print(f"[WEB] MQTT connecté à {MQTT_BROKER}:{MQTT_PORT}, subscribe {FACES_TOPIC}", flush=True)

# =========================
# FLASK APP
# =========================
app = Flask(__name__, static_folder="static")

@app.get("/")
def index():
    return send_from_directory("static", "index.html")

def proxy_stream():
    with requests.get(OPENCV_STREAM_URL, stream=True, timeout=10) as res:
        res.raise_for_status()
        for chunk in res.iter_content(chunk_size=1024):
            if chunk:
                yield chunk

@app.get("/video")
def video():
    return Response(
        stream_with_context(proxy_stream()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )

@app.get("/api/state")
def get_state():
    return jsonify(state)

@app.get("/api/faces")
def api_faces():
    with faces_lock:
        return jsonify(last_faces)

@app.post("/api/mode")
def set_mode():
    data = request.get_json(force=True)
    mode = (data.get("mode") or "").strip().lower()

    if mode not in ("auto", "manual"):
        return jsonify({"error": "mode must be auto or manual"}), 400

    state["mode"] = mode
    client.publish(TOPIC_MODE, mode)
    return jsonify({"ok": True, "mode": mode})

@app.post("/api/move")
def move():
    data = request.get_json(force=True)
    direction = (data.get("dir") or "").strip().lower()
    step = int(data.get("step") or STEP)

    # Forcer le mode manuel
    state["mode"] = "manual"
    client.publish(TOPIC_MODE, "manual")

    if direction == "left":
        state["pan"] = clamp(state["pan"] + step, PAN_MIN, PAN_MAX)
    elif direction == "right":
        state["pan"] = clamp(state["pan"] - step, PAN_MIN, PAN_MAX)
    elif direction == "up":
        state["tilt"] = clamp(state["tilt"] + step, TILT_MIN, TILT_MAX)
    elif direction == "down":
        state["tilt"] = clamp(state["tilt"] - step, TILT_MIN, TILT_MAX)
    else:
        return jsonify({"error": "dir must be left/right/up/down"}), 400

    client.publish(TOPIC_PAN, str(state["pan"]))
    client.publish(TOPIC_TILT, str(state["tilt"]))

    return jsonify({"ok": True, **state})

@app.post("/api/center")
def center():
    state["mode"] = "manual"
    client.publish(TOPIC_MODE, "manual")

    state["pan"] = 90
    state["tilt"] = 90
    client.publish(TOPIC_PAN, "90")
    client.publish(TOPIC_TILT, "90")

    return jsonify({"ok": True, **state})

# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
