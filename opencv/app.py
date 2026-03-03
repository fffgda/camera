import json
import os
import threading
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from flask import Flask, Response

# =========================
# CONFIG (ENV)
# =========================
STATUS_FACES_TOPIC = os.getenv("STATUS_FACES_TOPIC", "esp32cam/status/faces")

ESP32_IP = os.getenv("ESP32_IP", "172.16.8.186")
MJPEG_URL = os.getenv("MJPEG_URL", f"http://{ESP32_IP}:81/stream")

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")

TOL = int(os.getenv("TOL", "20"))
STEP = int(os.getenv("STEP", "2"))
MIN_ANGLE = 0
MAX_ANGLE = 180

SCALE_FACTOR = float(os.getenv("SCALE_FACTOR", "1.08"))
MIN_NEIGHBORS = int(os.getenv("MIN_NEIGHBORS", "3"))
MIN_SIZE = int(os.getenv("MIN_SIZE", "20"))

DETECT_EVERY_N = max(1, int(os.getenv("DETECT_EVERY_N", "2")))
DETECT_RESIZE = float(os.getenv("DETECT_RESIZE", "0.5"))
JPEG_QUALITY = max(5, min(95, int(os.getenv("JPEG_QUALITY", "70"))))
DRAW_OVERLAY = os.getenv("DRAW_OVERLAY", "1") == "1"

FACES_MAX = int(os.getenv("FACES_MAX", "5"))
FACES_FPS = float(os.getenv("FACES_FPS", "8"))
FACES_INTERVAL = 1.0 / max(1e-6, FACES_FPS)

DEBUG = os.getenv("DEBUG", "1") == "1"
DEBUG_INTERVAL = float(os.getenv("DEBUG_INTERVAL", "1.0"))

# =========================
# HAAR CASCADE
# =========================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
if face_cascade.empty():
    raise RuntimeError("Cascade Haar introuvable dans OpenCV.")

# =========================
# STATE
# =========================
mode_auto = True
current_pan = int(os.getenv("PAN_START", "90"))
current_tilt = int(os.getenv("TILT_START", "90"))

frame_lock = threading.Lock()
latest_frame_jpeg = None

app = Flask(__name__)


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def mean_brightness(gray: np.ndarray) -> float:
    return float(np.mean(gray))


def on_message(client, userdata, msg):
    global mode_auto
    if msg.topic == TOPIC_MODE:
        m = msg.payload.decode(errors="ignore").strip().lower()
        mode_auto = m == "auto"
        print(f"[MQTT] Mode reçu: {m} -> mode_auto={mode_auto}", flush=True)


def mqtt_connect():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="OpenCVClient")
    c.on_message = on_message
    c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    c.subscribe(TOPIC_MODE)
    c.loop_start()
    print(f"[MQTT] Connecté à {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    return c


def open_stream(url: str):
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return None
    return cap


def generate_stream():
    while True:
        with frame_lock:
            frame = latest_frame_jpeg

        if frame is None:
            time.sleep(0.05)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )


@app.get("/stream")
def stream():
    return Response(generate_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


def main():
    global current_pan, current_tilt, latest_frame_jpeg

    client = mqtt_connect()

    cap = None
    while cap is None:
        cap = open_stream(MJPEG_URL)
        if cap is None:
            print(f"[VIDEO] Impossible d'ouvrir {MJPEG_URL}. Nouvelle tentative dans 2s...", flush=True)
            time.sleep(2)

    print("[SYSTEM] Démarrage du face tracking.", flush=True)

    last_ctrl_publish = 0.0
    ctrl_interval = 0.05
    last_faces_publish = 0.0
    last_debug = 0.0
    frames = 0
    fps_t0 = time.time()
    frame_index = 0
    faces = ()

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("[VIDEO] Frame invalide, reconnexion...", flush=True)
            try:
                cap.release()
            except Exception:
                pass
            time.sleep(1)
            cap = None
            while cap is None:
                cap = open_stream(MJPEG_URL)
                if cap is None:
                    print(f"[VIDEO] Reconnexion échouée. Nouvelle tentative dans 2s...", flush=True)
                    time.sleep(2)
            continue

        now = time.time()
        frames += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_index += 1

        # Optimisation: détection visage 1 frame sur N + downscale
        if frame_index % DETECT_EVERY_N == 0:
            if 0.0 < DETECT_RESIZE < 1.0:
                small_gray = cv2.resize(gray, None, fx=DETECT_RESIZE, fy=DETECT_RESIZE, interpolation=cv2.INTER_LINEAR)
                faces_small = face_cascade.detectMultiScale(
                    small_gray,
                    scaleFactor=SCALE_FACTOR,
                    minNeighbors=MIN_NEIGHBORS,
                    minSize=(max(8, int(MIN_SIZE * DETECT_RESIZE)), max(8, int(MIN_SIZE * DETECT_RESIZE))),
                )
                inv = 1.0 / DETECT_RESIZE
                faces = [
                    (int(x * inv), int(y * inv), int(w * inv), int(h * inv))
                    for (x, y, w, h) in faces_small
                ]
            else:
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=SCALE_FACTOR,
                    minNeighbors=MIN_NEIGHBORS,
                    minSize=(MIN_SIZE, MIN_SIZE),
                )

        if (now - last_faces_publish) >= FACES_INTERVAL:
            faces_payload = {
                "ts": now,
                "frame_w": int(frame.shape[1]),
                "frame_h": int(frame.shape[0]),
                "faces": [
                    {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
                    for (x, y, w, h) in faces[:FACES_MAX]
                ],
            }
            client.publish(STATUS_FACES_TOPIC, json.dumps(faces_payload), qos=0, retain=False)
            last_faces_publish = now

        if len(faces) > 0 and mode_auto:
            x, y, w, h = faces[0]
            face_center_x = x + (w / 2.0)
            face_center_y = y + (h / 2.0)

            frame_center_x = frame.shape[1] / 2.0
            frame_center_y = frame.shape[0] / 2.0

            error_x = face_center_x - frame_center_x
            error_y = face_center_y - frame_center_y

            moved = False
            if abs(error_x) > TOL:
                current_pan += (-STEP if error_x > 0 else STEP)
                moved = True
            if abs(error_y) > TOL:
                current_tilt += (-STEP if error_y > 0 else STEP)
                moved = True

            current_pan = clamp(current_pan, MIN_ANGLE, MAX_ANGLE)
            current_tilt = clamp(current_tilt, MIN_ANGLE, MAX_ANGLE)

            if moved and (now - last_ctrl_publish) > ctrl_interval:
                client.publish(TOPIC_PAN, str(current_pan))
                client.publish(TOPIC_TILT, str(current_tilt))
                last_ctrl_publish = now

        if DRAW_OVERLAY:
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            fps = frames / max(1e-6, (now - fps_t0))
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (255, 0, 0), 2)
            mode_text = f"Mode: {'AUTO' if mode_auto else 'MANUEL'}"
            cv2.putText(
                frame,
                mode_text,
                (10, 60),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (0, 0, 255) if mode_auto else (0, 255, 255),
                2,
            )

        fps = frames / max(1e-6, (now - fps_t0))
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            with frame_lock:
                latest_frame_jpeg = encoded.tobytes()

        if DEBUG and (now - last_debug) >= DEBUG_INTERVAL:
            lum = mean_brightness(gray)
            print(
                f"[DEBUG] fps={fps:.1f} faces={len(faces)} size={frame.shape[1]}x{frame.shape[0]} brightness={lum:.1f}",
                flush=True,
            )
            last_debug = now
            if (now - fps_t0) > 5:
                frames = 0
                fps_t0 = now


if __name__ == "__main__":
    worker = threading.Thread(target=main, daemon=True)
    worker.start()
    app.run(host="0.0.0.0", port=int(os.getenv("STREAM_PORT", "5001")), threaded=True)
