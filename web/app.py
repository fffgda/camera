import json
import os
import sqlite3
import time
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
PEOPLE_TOPIC = os.getenv("PEOPLE_TOPIC", "esp32cam/status/people")
ALERTS_TOPIC = os.getenv("ALERT_TOPIC", "esp32cam/status/alerts")

OPENCV_STREAM_URL = os.getenv("OPENCV_STREAM_URL", "http://opencv:5001/stream")

STEP = int(os.getenv("STEP", "2"))
PAN_MIN, PAN_MAX = 0, 180
TILT_MIN, TILT_MAX = 0, 180

USER_DB_DIR = os.path.join(os.path.dirname(__file__), "data")
USER_DB_PATH = os.getenv("USER_DB_PATH", os.path.join(USER_DB_DIR, "users.db"))
os.makedirs(USER_DB_DIR, exist_ok=True)

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

last_people = {
    "ts": 0,
    "count": 0,
    "total_session": 0,
    "faces": [],
}

faces_lock = Lock()
people_lock = Lock()
state_lock = Lock()

# =========================
# SSE MANAGER
# =========================
sse_clients = []
sse_lock = Lock()


def sse_broadcast(event_type, data):
    """Envoie un événement SSE à tous les clients connectés."""
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.append(message)
            except Exception:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                count INTEGER NOT NULL,
                total INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                count INTEGER NOT NULL,
                threshold INTEGER NOT NULL,
                message TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                pan INTEGER NOT NULL,
                tilt INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Seeder les utilisateurs par défaut
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
        sse_broadcast("faces", data)
    except Exception as e:
        print("[WEB] Erreur parsing faces:", e, flush=True)


def on_people_message(client, userdata, msg):
    global last_people
    try:
        data = json.loads(msg.payload.decode(errors="ignore"))
        with people_lock:
            last_people = data

        sse_broadcast("people", data)

        # Sauvegarde dans l'historique SQLite
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO people_counts (timestamp, count, total) VALUES (?, ?, ?)",
                (data.get("ts", time.time()), data.get("count", 0), data.get("entries", 0)),
            )
            conn.commit()
    except Exception as e:
        print("[WEB] Erreur parsing people:", e, flush=True)


def on_alerts_message(client, userdata, msg):
    """Reçoit les alertes publiées par OpenCV et les persiste en base."""
    try:
        data = json.loads(msg.payload.decode(errors="ignore"))
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO alerts (timestamp, count, threshold, message) VALUES (?, ?, ?, ?)",
                (
                    data.get("ts", time.time()),
                    data.get("count", 0),
                    data.get("threshold", 0),
                    data.get("message", ""),
                ),
            )
            conn.commit()
        sse_broadcast("alert", data)
        print(f"[WEB] Alerte sauvegardée: {data.get('message', '')}", flush=True)
    except Exception as e:
        print("[WEB] Erreur parsing alert:", e, flush=True)


def on_message(client, userdata, msg):
    if msg.topic == FACES_TOPIC:
        on_faces_message(client, userdata, msg)
    elif msg.topic == PEOPLE_TOPIC:
        on_people_message(client, userdata, msg)
    elif msg.topic == ALERTS_TOPIC:
        on_alerts_message(client, userdata, msg)


# =========================
# MQTT CLIENT
# =========================
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="WebUIClient")
mqtt_client.on_message = on_message
mqtt_connected = False

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.subscribe([
        (FACES_TOPIC, 0),
        (PEOPLE_TOPIC, 0),
        (ALERTS_TOPIC, 0),
    ])
    mqtt_client.loop_start()
    mqtt_connected = True
    print(f"[WEB] MQTT connecté à {MQTT_BROKER}:{MQTT_PORT}", flush=True)
except Exception as e:
    print(f"[WEB] MQTT indisponible: {e}", flush=True)


# =========================
# FLASK APP
# =========================
app = Flask(__name__, static_folder="static")
_secret_key = os.getenv("FLASK_SECRET_KEY", "")
if not _secret_key or _secret_key == "change-this-secret":
    print("[WARNING] FLASK_SECRET_KEY non configurée - utilisez une valeur sécurisée en production!", flush=True)
    _secret_key = "change-this-secret"
app.config["SECRET_KEY"] = _secret_key

init_user_db()


# =========================
# AUTH ROUTES
# =========================
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


# =========================
# MAIN PAGE
# =========================
@app.get("/")
@login_required
def index():
    return send_from_directory("static", "index.html")


# =========================
# VIDEO PROXY
# =========================
def proxy_stream():
    try:
        print(f"[VIDEO] Connexion à {OPENCV_STREAM_URL}", flush=True)
        with requests.get(OPENCV_STREAM_URL, stream=True, timeout=30) as res:
            res.raise_for_status()
            print(f"[VIDEO] Stream OK, status={res.status_code}", flush=True)
            for chunk in res.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
    except requests.exceptions.ConnectionError as e:
        print(f"[VIDEO] Erreur connexion: {e}", flush=True)
    except requests.exceptions.Timeout as e:
        print(f"[VIDEO] Timeout: {e}", flush=True)
    except Exception as e:
        print(f"[VIDEO] Erreur inattendue: {e}", flush=True)


@app.get("/video")
@login_required
def video():
    return Response(
        stream_with_context(proxy_stream()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# =========================
# API STATE & FACES
# =========================
@app.get("/api/state")
@login_required
def get_state():
    with state_lock:
        return jsonify(state.copy())


@app.get("/api/faces")
@login_required
def api_faces():
    with faces_lock:
        return jsonify(last_faces)


# =========================
# SSE
# =========================
@app.get("/api/events")
@login_required
def sse_stream():
    def generate():
        q = []
        with sse_lock:
            sse_clients.append(q)
        try:
            while True:
                if q:
                    msg = q.pop(0)
                    yield msg
                else:
                    yield ": heartbeat\n\n"
                    time.sleep(0.5)
        finally:
            with sse_lock:
                if q in sse_clients:
                    sse_clients.remove(q)
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =========================
# CAMERA CONTROL
# =========================
@app.post("/api/mode")
@admin_required
def set_mode():
    data = request.get_json(force=True)
    mode = (data.get("mode") or "").strip().lower()

    if mode not in ("auto", "manual"):
        return jsonify({"error": "mode must be auto or manual"}), 400

    with state_lock:
        state["mode"] = mode
    if mqtt_connected:
        mqtt_client.publish(TOPIC_MODE, mode)
    return jsonify({"ok": True, "mode": mode})


@app.post("/api/move")
@admin_required
def move():
    data = request.get_json(force=True)
    direction = (data.get("dir") or "").strip().lower()

    try:
        step = int(data.get("step") or STEP)
    except (ValueError, TypeError):
        return jsonify({"error": "step must be an integer"}), 400
    step = clamp(step, 1, 45)

    with state_lock:
        state["mode"] = "manual"
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

        pan_val = state["pan"]
        tilt_val = state["tilt"]

    if mqtt_connected:
        mqtt_client.publish(TOPIC_MODE, "manual")
        mqtt_client.publish(TOPIC_PAN, str(pan_val))
        mqtt_client.publish(TOPIC_TILT, str(tilt_val))

    return jsonify({"ok": True, "pan": pan_val, "tilt": tilt_val, "mode": "manual"})


@app.post("/api/center")
@admin_required
def center():
    with state_lock:
        state["mode"] = "manual"
        state["pan"] = 90
        state["tilt"] = 90

    if mqtt_connected:
        mqtt_client.publish(TOPIC_MODE, "manual")
        mqtt_client.publish(TOPIC_PAN, "90")
        mqtt_client.publish(TOPIC_TILT, "90")

    return jsonify({"ok": True, "pan": 90, "tilt": 90, "mode": "manual"})


# =========================
# POSITIONS
# =========================
@app.get("/api/positions")
@login_required
def api_positions():
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, pan, tilt, created_at FROM positions ORDER BY name ASC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/positions")
@admin_required
def api_positions_create():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    with state_lock:
        default_pan = state["pan"]
        default_tilt = state["tilt"]

    try:
        pan = int(data.get("pan", default_pan))
        tilt = int(data.get("tilt", default_tilt))
    except (ValueError, TypeError):
        return jsonify({"error": "pan and tilt must be integers"}), 400

    pan = clamp(pan, PAN_MIN, PAN_MAX)
    tilt = clamp(tilt, TILT_MIN, TILT_MAX)

    with get_db_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO positions (name, pan, tilt) VALUES (?, ?, ?)",
                (name, pan, tilt),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": f"position '{name}' already exists"}), 409

    return jsonify({"ok": True, "name": name, "pan": pan, "tilt": tilt})


@app.post("/api/positions/recall")
@admin_required
def api_positions_recall():
    data = request.get_json(force=True)
    pos_id = data.get("id")
    if not pos_id:
        return jsonify({"error": "id is required"}), 400

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, name, pan, tilt FROM positions WHERE id = ?", (pos_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": "position not found"}), 404

    with state_lock:
        state["pan"] = row["pan"]
        state["tilt"] = row["tilt"]
        state["mode"] = "manual"

    if mqtt_connected:
        mqtt_client.publish(TOPIC_MODE, "manual")
        mqtt_client.publish(TOPIC_PAN, str(row["pan"]))
        mqtt_client.publish(TOPIC_TILT, str(row["tilt"]))

    return jsonify({"ok": True, "name": row["name"], "pan": row["pan"], "tilt": row["tilt"], "mode": "manual"})


@app.delete("/api/positions/<int:pos_id>")
@admin_required
def api_positions_delete(pos_id):
    with get_db_connection() as conn:
        result = conn.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
        conn.commit()
        if result.rowcount == 0:
            return jsonify({"error": "position not found"}), 404
    return jsonify({"ok": True})


# =========================
# PEOPLE COUNT
# =========================
@app.get("/api/people")
@login_required
def api_people():
    with people_lock:
        return jsonify(last_people)


@app.get("/api/people/history")
@login_required
def api_people_history():
    limit = int(request.args.get("limit", "100"))
    limit = min(max(1, limit), 1000)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT timestamp, count, total FROM people_counts ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    history = [{"timestamp": r["timestamp"], "count": r["count"], "total": r["total"]} for r in rows]
    return jsonify(history)


# =========================
# ALERTS
# =========================
@app.get("/api/alerts")
@login_required
def api_alerts():
    limit = int(request.args.get("limit", "50"))
    limit = min(max(1, limit), 200)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, count, threshold, message FROM alerts ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return jsonify([
        {"id": r["id"], "timestamp": r["timestamp"], "count": r["count"],
         "threshold": r["threshold"], "message": r["message"]}
        for r in rows
    ])


# =========================
# HEALTH CHECK
# =========================
@app.get("/health")
@app.get("/v1/health")
def health_check():
    return jsonify({"status": "healthy", "service": "web"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
