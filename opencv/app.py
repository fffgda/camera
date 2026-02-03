import os
import time
import cv2
import numpy as np
import paho.mqtt.client as mqtt

ESP32_IP = os.getenv("ESP32_IP", "172.16.8.53")
MJPEG_URL = os.getenv("MJPEG_URL", f"http://{ESP32_IP}:81")

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")  # IMPORTANT: nom du service docker
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")

# Détection visage (Haar)
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
if face_cascade.empty():
    raise RuntimeError("Cascade Haar introuvable dans OpenCV.")

mode_auto = True
current_pan = 90
current_tilt = 90

TOL = int(os.getenv("TOL", "20"))          # tolérance pixels
STEP = int(os.getenv("STEP", "2"))         # pas servo
MIN_ANGLE = 0
MAX_ANGLE = 180

def on_message(client, userdata, msg):
    global mode_auto
    if msg.topic == TOPIC_MODE:
        m = msg.payload.decode(errors="ignore").strip().lower()
        mode_auto = (m == "auto")
        print(f"[MQTT] Mode reçu: {m} -> mode_auto={mode_auto}", flush=True)

def mqtt_connect():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="OpenCVClient")
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.subscribe(TOPIC_MODE)
    client.loop_start()
    print(f"[MQTT] Connecté à {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    return client

def open_stream(url):
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return None
    return cap

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def main():
    global current_pan, current_tilt

    client = mqtt_connect()

    cap = None
    while cap is None:
        cap = open_stream(MJPEG_URL)
        if cap is None:
            print(f"[VIDEO] Impossible d'ouvrir {MJPEG_URL}. Nouvelle tentative dans 2s...", flush=True)
            time.sleep(2)

    print("[SYSTEM] Démarrage face tracking (Docker)", flush=True)

    last_publish = 0
    publish_interval = 0.05  # 20 Hz max

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("[VIDEO] Frame invalide, reconnexion...", flush=True)
            cap.release()
            time.sleep(1)
            cap = None
            while cap is None:
                cap = open_stream(MJPEG_URL)
                if cap is None:
                    print(f"[VIDEO] Reconnexion échouée. Retry 2s...", flush=True)
                    time.sleep(2)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        if len(faces) > 0 and mode_auto:
            x, y, w, h = faces[0]

            fx = x + w / 2.0
            fy = y + h / 2.0
            cx = frame.shape[1] / 2.0
            cy = frame.shape[0] / 2.0

            error_x = fx - cx
            error_y = fy - cy

            moved = False

            if abs(error_x) > TOL:
                # visage à droite => erreur positive => on ajuste pan
                current_pan += (-STEP if error_x > 0 else STEP)
                moved = True

            if abs(error_y) > TOL:
                # visage en bas => erreur positive => on ajuste tilt
                current_tilt += (-STEP if error_y > 0 else STEP)
                moved = True

            current_pan = clamp(current_pan, MIN_ANGLE, MAX_ANGLE)
            current_tilt = clamp(current_tilt, MIN_ANGLE, MAX_ANGLE)

            now = time.time()
            if moved and (now - last_publish) > publish_interval:
                client.publish(TOPIC_PAN, str(current_pan))
                client.publish(TOPIC_TILT, str(current_tilt))
                last_publish = now
                print(f"[CTRL] pan={current_pan} tilt={current_tilt} err=({error_x:.1f},{error_y:.1f})", flush=True)

if __name__ == "__main__":
    main()
