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

ESP32_IP = os.getenv("ESP32_IP", "172.16.8.81")
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

MOTION_ENABLED = os.getenv("MOTION_ENABLED", "1") == "1"
MOTION_THRESHOLD = int(os.getenv("MOTION_THRESHOLD", "25"))
MOTION_MIN_PIXELS = int(os.getenv("MOTION_MIN_PIXELS", "500"))
MOTION_TOPIC = os.getenv("MOTION_TOPIC", "esp32cam/status/motion")
MOTION_COOLDOWN = float(os.getenv("MOTION_COOLDOWN", "2.0"))

# =========================
# YOLO MODEL
# =========================
# Stabilise PyTorch dans le conteneur : limite a 1 thread et desactive
# le backend oneDNN/MKL-DNN qui crashait avec "could not create a primitive".
try:
    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if hasattr(torch.backends, "mkldnn"):
        torch.backends.mkldnn.enabled = False
    if hasattr(torch.backends, "nnpack"):
        torch.backends.nnpack.enabled = False
    print("[YOLO] PyTorch threads=1, mkldnn+nnpack desactives", flush=True)
except Exception as _e:
    print(f"[YOLO] Reglage PyTorch ignore: {_e}", flush=True)

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
# MOTION DETECTOR
# =========================
class MotionDetector:
    def __init__(self, threshold=25, min_pixels=500):
        self.prev_gray = None
        self.threshold = threshold
        self.min_pixels = min_pixels
        self.motion_detected = False

    def detect(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self.prev_gray is None:
            self.prev_gray = gray
            return False
        delta = cv2.absdiff(self.prev_gray, gray)
        self.prev_gray = gray
        _, thresh = cv2.threshold(delta, self.threshold, 255, cv2.THRESH_BINARY)
        changed_pixels = cv2.countNonZero(thresh)
        self.motion_detected = changed_pixels > self.min_pixels
        return self.motion_detected


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
    global mode_auto, current_pan, current_tilt
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore").strip()

    if topic == TOPIC_MODE:
        mode_auto = payload.lower() == "auto"
        print(f"[MQTT] Mode recu: {payload} -> mode_auto={mode_auto}", flush=True)

    elif topic == TOPIC_PAN:
        # Synchronisation : quand le web envoie une commande manuelle,
        # OpenCV met à jour sa position pour ne pas repartir d'un angle périmé
        try:
            current_pan = clamp(int(payload), MIN_ANGLE, MAX_ANGLE)
            print(f"[MQTT] Pan sync: {current_pan}", flush=True)
        except ValueError:
            pass

    elif topic == TOPIC_TILT:
        try:
            current_tilt = clamp(int(payload), MIN_ANGLE, MAX_ANGLE)
            print(f"[MQTT] Tilt sync: {current_tilt}", flush=True)
        except ValueError:
            pass


def mqtt_connect():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="OpenCVClient")
    c.on_message = on_message
    c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    # S'abonner aussi à pan/tilt pour rester synchronisé avec les commandes manuelles du web
    c.subscribe([(TOPIC_MODE, 0), (TOPIC_PAN, 0), (TOPIC_TILT, 0)])
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

    # Injecter le client MQTT dans l'AlertManager pour publier les alertes
    alert_manager.mqtt_client = client

    cap = None
    while cap is None:
        cap = open_stream(MJPEG_URL)
        if cap is None:
            print(f"[VIDEO] Impossible d'ouvrir {MJPEG_URL}. Nouvelle tentative dans 2s...", flush=True)
            time.sleep(2)

    print("[SYSTEM] Demarrage du person tracking (YOLO).", flush=True)

    motion_detector = MotionDetector(threshold=MOTION_THRESHOLD, min_pixels=MOTION_MIN_PIXELS) if MOTION_ENABLED else None
    last_motion_publish = 0.0
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
            old_cap = cap
            cap = None
            try:
                old_cap.release()
            except Exception:
                pass
            time.sleep(1)
            retry_count = 0
            while cap is None and retry_count < 10:
                cap = open_stream(MJPEG_URL)
                if cap is None:
                    print(f"[VIDEO] Reconnexion echouee tentative {retry_count+1}/10. Nouvelle tentative dans 2s...", flush=True)
                    time.sleep(2)
                    retry_count += 1
            if cap is None:
                print("[VIDEO] Impossible de reconnecter après 10 tentatives, attente longue...", flush=True)
                time.sleep(30)
            continue

        now = time.time()
        frames += 1
        frame_index += 1

        # Motion detection
        has_motion = False
        if motion_detector:
            has_motion = motion_detector.detect(frame)
            if has_motion and (now - last_motion_publish) >= MOTION_COOLDOWN:
                client.publish(MOTION_TOPIC, json.dumps({"ts": now, "motion": True}), qos=0, retain=False)
                last_motion_publish = now

        # Detection YOLO 1 frame sur N, or when motion detected
        should_detect = (frame_index % DETECT_EVERY_N == 0) or has_motion
        if should_detect:
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
                "entries": count_data.get("entries", 0),
                "exits": count_data.get("exits", 0),
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
            if motion_detector:
                motion_color = (0, 0, 255) if has_motion else (128, 128, 128)
                motion_text = f"Motion: {'OUI' if has_motion else 'NON'}"
                cv2.putText(frame, motion_text, (10, 120), cv2.FONT_HERSHEY_PLAIN, 2, motion_color, 2)

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
