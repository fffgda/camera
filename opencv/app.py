import json
import os
import threading
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from flask import Flask, Response
from ultralytics import YOLO

from alerts import AlertManager
from counting import PersonCounter

# =========================
# CONFIG (ENV)
# =========================
STATUS_FACES_TOPIC = os.getenv("STATUS_FACES_TOPIC", "esp32cam/status/faces")
STATUS_PEOPLE_TOPIC = os.getenv("STATUS_PEOPLE_TOPIC", "esp32cam/status/people")

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

YOLO_CONF = float(os.getenv("YOLO_CONF", "0.45"))
DETECT_EVERY_N = max(1, int(os.getenv("DETECT_EVERY_N", "2")))
DETECT_RESIZE = float(os.getenv("DETECT_RESIZE", "0.5"))
JPEG_QUALITY = max(5, min(95, int(os.getenv("JPEG_QUALITY", "70"))))
DRAW_OVERLAY = os.getenv("DRAW_OVERLAY", "1") == "1"

FACES_MAX = int(os.getenv("FACES_MAX", "10"))
FACES_FPS = float(os.getenv("FACES_FPS", "8"))
FACES_INTERVAL = 1.0 / max(1e-6, FACES_FPS)

DEBUG = os.getenv("DEBUG", "1") == "1"
DEBUG_INTERVAL = float(os.getenv("DEBUG_INTERVAL", "1.0"))

# =========================
# YOLO MODEL
# =========================
print("[YOLO] Chargement du modele yolov8n.pt...", flush=True)
model = YOLO("yolov8n.pt")
print("[YOLO] Modele charge OK (classes COCO, filtre: person=0)", flush=True)


def detect_persons(frame, det_resize):
    """Detect persons using YOLOv8. Returns list of (x, y, w, h)."""
    if 0.0 < det_resize < 1.0:
        small = cv2.resize(frame, None, fx=det_resize, fy=det_resize, interpolation=cv2.INTER_LINEAR)
        results = model.predict(small, classes=[0], conf=YOLO_CONF, verbose=False)
        inv = 1.0 / det_resize
    else:
        results = model.predict(frame, classes=[0], conf=YOLO_CONF, verbose=False)
        inv = 1.0

    persons = []
    for box in results[0].boxes:
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
        x = int(x1 * inv)
        y = int(y1 * inv)
        w = int((x2 - x1) * inv)
        h = int((y2 - y1) * inv)
        persons.append((x, y, w, h))
    return persons


def mean_brightness(gray):
    return float(np.mean(gray))


# =========================
# ALERTS
# =========================
alert_manager = AlertManager()


# =========================
# COUNTING
# =========================
person_counter = PersonCounter()


# =========================
# STATE
# =========================
mode_auto = True
current_pan = int(os.getenv("PAN_START", "90"))
current_tilt = int(os.getenv("TILT_START", "90"))

frame_lock = threading.Lock()
latest_frame_jpeg = None

app = Flask(__name__)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def on_message(client, userdata, msg):
    global mode_auto
    if msg.topic == TOPIC_MODE:
        m = msg.payload.decode(errors="ignore").strip().lower()
        mode_auto = m == "auto"
        print(f"[MQTT] Mode recu: {m} -> mode_auto={mode_auto}", flush=True)


def mqtt_connect():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="OpenCVClient")
    c.on_message = on_message
    c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    c.subscribe(TOPIC_MODE)
    c.loop_start()
    print(f"[MQTT] Connecte a {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    return c


def open_stream(url):
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

    print("[SYSTEM] Demarrage du person tracking (YOLO).", flush=True)

    last_ctrl_publish = 0.0
    ctrl_interval = 0.05
    last_faces_publish = 0.0
    last_people_publish = 0.0
    last_debug = 0.0
    frames = 0
    fps_t0 = time.time()
    frame_index = 0
    persons = []

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
                    print(f"[VIDEO] Reconnexion echouee. Nouvelle tentative dans 2s...", flush=True)
                    time.sleep(2)
            continue

        now = time.time()
        frames += 1
        frame_index += 1

        # Detection YOLO 1 frame sur N
        if frame_index % DETECT_EVERY_N == 0:
            persons = detect_persons(frame, DETECT_RESIZE)

        # Publish faces (persons as bounding boxes)
        if (now - last_faces_publish) >= FACES_INTERVAL:
            faces_payload = {
                "ts": now,
                "frame_w": int(frame.shape[1]),
                "frame_h": int(frame.shape[0]),
                "faces": [
                    {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
                    for (x, y, w, h) in persons[:FACES_MAX]
                ],
            }
            client.publish(STATUS_FACES_TOPIC, json.dumps(faces_payload), qos=0, retain=False)
            last_faces_publish = now

        # Publish people count
        count_data = person_counter.update(persons)
        if (now - last_people_publish) >= FACES_INTERVAL:
            people_payload = {
                "ts": now,
                "count": count_data["current"],
                "total_session": count_data["total_session"],
            }
            client.publish(STATUS_PEOPLE_TOPIC, json.dumps(people_payload), qos=0, retain=False)
            last_people_publish = now

            # Check alerts
            alert_manager.check_threshold(count_data["current"])

        # Auto-tracking (track first person)
        if len(persons) > 0 and mode_auto:
            x, y, w, h = persons[0]
            person_center_x = x + (w / 2.0)
            person_center_y = y + (h / 2.0)

            frame_center_x = frame.shape[1] / 2.0
            frame_center_y = frame.shape[0] / 2.0

            error_x = person_center_x - frame_center_x
            error_y = person_center_y - frame_center_y

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

        # Overlay
        if DRAW_OVERLAY:
            for (x, y, w, h) in persons:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(frame, "person", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            fps = frames / max(1e-6, (now - fps_t0))
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (255, 0, 0), 2)
            mode_text = f"Mode: {'AUTO' if mode_auto else 'MANUEL'}"
            cv2.putText(frame, mode_text, (10, 60), cv2.FONT_HERSHEY_PLAIN, 2, (0, 0, 255) if mode_auto else (0, 255, 255), 2)
            cv2.putText(frame, f"Personnes: {len(persons)}", (10, 90), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)

        # Encode JPEG
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            with frame_lock:
                latest_frame_jpeg = encoded.tobytes()

        # Debug log
        if DEBUG and (now - last_debug) >= DEBUG_INTERVAL:
            fps = frames / max(1e-6, (now - fps_t0))
            lum = mean_brightness(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            print(
                f"[DEBUG] fps={fps:.1f} persons={len(persons)} size={frame.shape[1]}x{frame.shape[0]} brightness={lum:.1f}",
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
