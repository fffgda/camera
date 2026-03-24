import json
import os
import threading
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from flask import Flask, Response
from ultralytics import YOLO

# =========================
# CONFIG (ENV)
# =========================
STATUS_FACES_TOPIC = os.getenv("STATUS_FACES_TOPIC", "esp32cam/status/faces")

ESP32_STREAM_URL = os.getenv(
    "ESP32_STREAM_URL",
    "${MJPEG_URL}",
)

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")

TOL = int(os.getenv("TOL", "20"))
STEP = int(os.getenv("STEP", "2"))
MIN_ANGLE = 0
MAX_ANGLE = 180

# =========================
# YOLO CONFIG
# =========================
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
YOLO_CONF = float(os.getenv("YOLO_CONF", "0.45"))
YOLO_IOU = float(os.getenv("YOLO_IOU", "0.50"))
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "320"))
YOLO_DEVICE = os.getenv("YOLO_DEVICE", "cpu")

YOLO_CLASSES_ENV = os.getenv("YOLO_CLASSES", "0").strip()
YOLO_CLASSES = [
    int(class_id.strip())
    for class_id in YOLO_CLASSES_ENV.split(",")
    if class_id.strip()
]

DETECT_EVERY_N = max(1, int(os.getenv("DETECT_EVERY_N", "2")))
JPEG_QUALITY = max(5, min(95, int(os.getenv("JPEG_QUALITY", "70"))))
DRAW_OVERLAY = os.getenv("DRAW_OVERLAY", "1") == "1"

FACES_MAX = int(os.getenv("FACES_MAX", "5"))
FACES_FPS = float(os.getenv("FACES_FPS", "8"))
FACES_INTERVAL = 1.0 / max(1e-6, FACES_FPS)

DEBUG = os.getenv("DEBUG", "1") == "1"
DEBUG_INTERVAL = float(os.getenv("DEBUG_INTERVAL", "1.0"))
STREAM_PORT = int(os.getenv("STREAM_PORT", "5001"))

# =========================
# YOLO MODEL
# =========================
print(f"[YOLO] Chargement du modèle {YOLO_MODEL} sur {YOLO_DEVICE}...", flush=True)
model = YOLO(YOLO_MODEL)
model.predict(
    np.zeros((YOLO_IMGSZ, YOLO_IMGSZ, 3), dtype=np.uint8),
    imgsz=YOLO_IMGSZ,
    device=YOLO_DEVICE,
    verbose=False,
)
print("[YOLO] Modèle prêt.", flush=True)

# =========================
# STATE
# =========================
mode_auto = True
current_pan = int(os.getenv("PAN_START", "90"))
current_tilt = int(os.getenv("TILT_START", "90"))

frame_lock = threading.Lock()
latest_frame_jpeg = None

app = Flask(__name__)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def mean_brightness(gray_frame: np.ndarray) -> float:
    return float(np.mean(gray_frame))


def detect_objects_yolo(frame: np.ndarray) -> list[tuple[int, int, int, int, float]]:
    results = model.predict(
        frame,
        imgsz=YOLO_IMGSZ,
        conf=YOLO_CONF,
        iou=YOLO_IOU,
        classes=YOLO_CLASSES if YOLO_CLASSES else None,
        device=YOLO_DEVICE,
        verbose=False,
    )

    detections = []

    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            confidence = float(box.conf[0])
            x = int(x1)
            y = int(y1)
            w = int(x2 - x1)
            h = int(y2 - y1)
            detections.append((x, y, w, h, confidence))

    detections.sort(key=lambda item: item[2] * item[3], reverse=True)
    return detections


def on_message(client, userdata, msg):
    global mode_auto

    if msg.topic == TOPIC_MODE:
        payload = msg.payload.decode(errors="ignore").strip().lower()
        mode_auto = payload == "auto"
        print(f"[MQTT] Mode reçu: {payload} -> mode_auto={mode_auto}", flush=True)


def mqtt_connect():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="yolo-tracker")
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.subscribe(TOPIC_MODE)
    client.loop_start()
    print(f"[MQTT] Connecté à {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    return client


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
    return Response(
        generate_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/health")
def health():
    return {"status": "ok"}, 200


def main():
    global current_pan, current_tilt, latest_frame_jpeg

    client = mqtt_connect()

    cap = None
    while cap is None:
        cap = open_stream(ESP32_STREAM_URL)
        if cap is None:
            print(
                f"[VIDEO] Impossible d'ouvrir {ESP32_STREAM_URL}. Nouvelle tentative dans 2s...",
                flush=True,
            )
            time.sleep(2)

    print("[SYSTEM] Démarrage du tracking YOLO.", flush=True)

    last_ctrl_publish = 0.0
    ctrl_interval = 0.05
    last_faces_publish = 0.0
    last_debug = 0.0
    frames = 0
    fps_t0 = time.time()
    frame_index = 0
    detections: list[tuple[int, int, int, int, float]] = []

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
                cap = open_stream(ESP32_STREAM_URL)
                if cap is None:
                    print("[VIDEO] Reconnexion échouée. Nouvelle tentative dans 2s...", flush=True)
                    time.sleep(2)
            continue

        now = time.time()
        frames += 1
        frame_index += 1

        if frame_index % DETECT_EVERY_N == 0:
            detections = detect_objects_yolo(frame)

        if (now - last_faces_publish) >= FACES_INTERVAL:
            payload = {
                "ts": now,
                "frame_w": int(frame.shape[1]),
                "frame_h": int(frame.shape[0]),
                "faces": [
                    {"x": x, "y": y, "w": w, "h": h, "conf": round(conf, 3)}
                    for (x, y, w, h, conf) in detections[:FACES_MAX]
                ],
            }
            client.publish(
                STATUS_FACES_TOPIC,
                json.dumps(payload),
                qos=0,
                retain=False,
            )
            last_faces_publish = now

        if detections and mode_auto:
            x, y, w, h, _conf = detections[0]

            target_center_x = x + (w / 2.0)
            target_center_y = y + (h / 2.0)

            frame_center_x = frame.shape[1] / 2.0
            frame_center_y = frame.shape[0] / 2.0

            error_x = target_center_x - frame_center_x
            error_y = target_center_y - frame_center_y

            moved = False

            if abs(error_x) > TOL:
                current_pan += -STEP if error_x > 0 else STEP
                moved = True

            if abs(error_y) > TOL:
                current_tilt += -STEP if error_y > 0 else STEP
                moved = True

            current_pan = clamp(current_pan, MIN_ANGLE, MAX_ANGLE)
            current_tilt = clamp(current_tilt, MIN_ANGLE, MAX_ANGLE)

            if moved and (now - last_ctrl_publish) > ctrl_interval:
                client.publish(TOPIC_PAN, str(current_pan))
                client.publish(TOPIC_TILT, str(current_tilt))
                last_ctrl_publish = now

        if DRAW_OVERLAY:
            for x, y, w, h, conf in detections:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    f"{conf:.2f}",
                    (x, max(15, y - 8)),
                    cv2.FONT_HERSHEY_PLAIN,
                    1.2,
                    (0, 255, 0),
                    1,
                )

            fps = frames / max(1e-6, (now - fps_t0))
            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (255, 0, 0),
                2,
            )
            cv2.putText(
                frame,
                f"Mode: {'AUTO' if mode_auto else 'MANUEL'}",
                (10, 60),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (0, 0, 255) if mode_auto else (0, 255, 255),
                2,
            )

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )

        if ok:
            with frame_lock:
                latest_frame_jpeg = encoded.tobytes()

        if DEBUG and (now - last_debug) >= DEBUG_INTERVAL:
            fps = frames / max(1e-6, (now - fps_t0))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = mean_brightness(gray)

            print(
                f"[DEBUG] fps={fps:.1f} detections={len(detections)} "
                f"size={frame.shape[1]}x{frame.shape[0]} brightness={brightness:.1f}",
                flush=True,
            )

            last_debug = now

            if (now - fps_t0) > 5:
                frames = 0
                fps_t0 = now


if __name__ == "__main__":
    worker = threading.Thread(target=main, daemon=True)
    worker.start()
    app.run(host="0.0.0.0", port=STREAM_PORT, threaded=True)