import os
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
import paho.mqtt.client as mqtt

# Config via variables d'environnement
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")

OPENCV_STREAM_URL = os.getenv("OPENCV_STREAM_URL", "http://opencv:5001/stream")

STEP = int(os.getenv("STEP", "2"))   # pas servo
PAN_MIN, PAN_MAX = 0, 180
TILT_MIN, TILT_MAX = 0, 180

# Etat (simple)
state = {
    "pan": int(os.getenv("PAN_START", "90")),
    "tilt": int(os.getenv("TILT_START", "90")),
    "mode": "manual",
}

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# MQTT client
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="WebUIClient")
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.loop_start()

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

    # On force le mode manuel dès qu'on bouge à la main
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)