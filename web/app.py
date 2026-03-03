import json
import os
import sqlite3
from functools import wraps
from threading import Lock

import paho.mqtt.client as mqtt
import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    request,
    send_from_directory,
    session,
    stream_with_context,
)
from werkzeug.security import check_password_hash, generate_password_hash

# =========================
# CONFIG
# =========================
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")
FACES_TOPIC = os.getenv("FACES_TOPIC", "esp32cam/status/faces")

OPENCV_STREAM_URL = os.getenv("OPENCV_STREAM_URL", "http://opencv:5001/stream")

STEP = int(os.getenv("STEP", "2"))
PAN_MIN, PAN_MAX = 0, 180
TILT_MIN, TILT_MAX = 0, 180

USER_DB_PATH = os.getenv("USER_DB_PATH", os.path.join(os.path.dirname(__file__), "users.db"))
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
DEFAULT_VIEWER_USERNAME = os.getenv("DEFAULT_VIEWER_USERNAME", "viewer")
DEFAULT_VIEWER_PASSWORD = os.getenv("DEFAULT_VIEWER_PASSWORD", "viewer123")

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
    "faces": [],
}

faces_lock = Lock()

# =========================
# HELPERS
# =========================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def get_db_connection():
    conn = sqlite3.connect(USER_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_user_db():
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        users_to_seed = [
            (DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, "admin"),
            (DEFAULT_VIEWER_USERNAME, DEFAULT_VIEWER_PASSWORD, "viewer"),
        ]

        for username, password, role in users_to_seed:
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), role),
                )

        conn.commit()


def login_required(view_fn):
    @wraps(view_fn)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "auth required"}), 401
            return redirect("/login")
        return view_fn(*args, **kwargs)

    return wrapped


def admin_required(view_fn):
    @wraps(view_fn)
    def wrapped(*args, **kwargs):
        user = session.get("user")
        if not user:
            return jsonify({"error": "auth required"}), 401
        if user.get("role") != "admin":
            return jsonify({"error": "admin role required"}), 403
        return view_fn(*args, **kwargs)

    return wrapped


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
mqtt_connected = False

try:
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.subscribe(FACES_TOPIC)
    client.loop_start()
    mqtt_connected = True
    print(
        f"[WEB] MQTT connecté à {MQTT_BROKER}:{MQTT_PORT}, subscribe {FACES_TOPIC}",
        flush=True,
    )
except Exception as e:
    print(f"[WEB] MQTT indisponible: {e}", flush=True)


# =========================
# FLASK APP
# =========================
app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-secret")

init_user_db()


@app.get("/login")
def login_page():
    return send_from_directory("static", "login.html")


@app.post("/api/login")
def login_api():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    with get_db_connection() as conn:
        user = conn.execute(
            "SELECT username, password_hash, role FROM users WHERE username = ?", (username,)
        ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    session["user"] = {"username": user["username"], "role": user["role"]}
    return jsonify({"ok": True, "user": session["user"]})


@app.post("/api/logout")
def logout_api():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    user = session.get("user")
    if not user:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "user": user})


@app.get("/")
@login_required
def index():
    return send_from_directory("static", "index.html")


def proxy_stream():
    with requests.get(OPENCV_STREAM_URL, stream=True, timeout=10) as res:
        res.raise_for_status()
        for chunk in res.iter_content(chunk_size=8192):
            if chunk:
                yield chunk


@app.get("/video")
@login_required
def video():
    return Response(
        stream_with_context(proxy_stream()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/state")
@login_required
def get_state():
    return jsonify(state)


@app.get("/api/faces")
@login_required
def api_faces():
    with faces_lock:
        return jsonify(last_faces)


@app.post("/api/mode")
@admin_required
def set_mode():
    data = request.get_json(force=True)
    mode = (data.get("mode") or "").strip().lower()

    if mode not in ("auto", "manual"):
        return jsonify({"error": "mode must be auto or manual"}), 400

    state["mode"] = mode
    if mqtt_connected:
        client.publish(TOPIC_MODE, mode)
    return jsonify({"ok": True, "mode": mode})


@app.post("/api/move")
@admin_required
def move():
    data = request.get_json(force=True)
    direction = (data.get("dir") or "").strip().lower()
    step = int(data.get("step") or STEP)

    state["mode"] = "manual"
    if mqtt_connected:
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

    if mqtt_connected:
        client.publish(TOPIC_PAN, str(state["pan"]))
        client.publish(TOPIC_TILT, str(state["tilt"]))

    return jsonify({"ok": True, **state})


@app.post("/api/center")
@admin_required
def center():
    state["mode"] = "manual"
    state["pan"] = 90
    state["tilt"] = 90

    if mqtt_connected:
        client.publish(TOPIC_MODE, "manual")
        client.publish(TOPIC_PAN, "90")
        client.publish(TOPIC_TILT, "90")

    return jsonify({"ok": True, **state})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
