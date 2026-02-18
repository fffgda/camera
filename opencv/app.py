import os
import time
<<<<<<< Updated upstream
import threading
from typing import Optional

=======
import json
>>>>>>> Stashed changes
import cv2
import numpy as np
import paho.mqtt.client as mqtt
from flask import Flask, Response
import operator

<<<<<<< Updated upstream
# Adresses et URL
ESP32_IP = os.getenv("ESP32_IP", "192.168.1.49") # J'ai mis l'IP de votre exemple
MJPEG_URL = os.getenv("MJPEG_URL", f"http://{ESP32_IP}:81/stream")

# Configuration MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")  # IMPORTANT: nom du service docker ou IP du broker
=======
# =========================
# CONFIG (ENV)
# =========================
STATUS_FACES_TOPIC = os.getenv("STATUS_FACES_TOPIC", "esp32cam/status/faces")

ESP32_IP = os.getenv("ESP32_IP", "172.16.8.53")
# IMPORTANT : pour ESP32-CAM, le flux est généralement /stream
MJPEG_URL = os.getenv("MJPEG_URL", f"http://{ESP32_IP}:81/stream")

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")  # nom du service docker mosquitto
>>>>>>> Stashed changes
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")

<<<<<<< Updated upstream
# Paramètres du contrôle des servos
TOL = int(os.getenv("TOL", "20"))          # Tolérance en pixels avant de bouger
STEP = int(os.getenv("STEP", "2"))         # Pas de mouvement du servo
MIN_ANGLE = 0
MAX_ANGLE = 180

# --- INITIALISATION DÉTECTION (du Code 2, amélioré) ---
# Chargement des classificateurs Haar pour la détection de visage
try:
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
    )
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    if face_cascade.empty() or profile_cascade.empty():
        raise RuntimeError()
except:
    print("Erreur: Impossible de charger un ou plusieurs fichiers de cascade Haar.")
    print("Vérifiez votre installation d'OpenCV.")
    exit()

# --- VARIABLES GLOBALES ---
mode_auto = True
current_pan = 90
current_tilt = 90

# --- FONCTIONS MQTT ---
def on_message(client, userdata, msg):
    """Callback pour la réception des messages MQTT."""
=======
# Réglages tracking (servo)
TOL = int(os.getenv("TOL", "20"))          # zone morte (pixels)
STEP = int(os.getenv("STEP", "2"))         # pas servo
MIN_ANGLE = 0
MAX_ANGLE = 180

# =========================
# Réglages détection (PLUS PERMISSIF)
# =========================
# Ces valeurs sont la raison n°1 de "faces: []" quand la caméra est sombre / 320x240.
SCALE_FACTOR = float(os.getenv("SCALE_FACTOR", "1.08"))   # 1.05–1.15
MIN_NEIGHBORS = int(os.getenv("MIN_NEIGHBORS", "3"))      # 3–5
MIN_SIZE = int(os.getenv("MIN_SIZE", "20"))               # 20–40 (en pixels)

# =========================
# Publication faces (overlay)
# =========================
FACES_MAX = int(os.getenv("FACES_MAX", "5"))              # max faces envoyées
FACES_FPS = float(os.getenv("FACES_FPS", "8"))            # fréquence d'envoi rectangles
FACES_INTERVAL = 1.0 / max(1e-6, FACES_FPS)

# =========================
# Debug / logs
# =========================
DEBUG = os.getenv("DEBUG", "1") == "1"
DEBUG_INTERVAL = float(os.getenv("DEBUG_INTERVAL", "1.0"))  # log toutes les X secondes

# =========================
# Haar cascade (face detect)
# =========================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
if face_cascade.empty():
    raise RuntimeError("Cascade Haar introuvable dans OpenCV.")

# =========================
# Etat
# =========================
mode_auto = True
current_pan = int(os.getenv("PAN_START", "90"))
current_tilt = int(os.getenv("TILT_START", "90"))

# =========================
# MQTT callbacks
# =========================
def on_message(client, userdata, msg):
    """Réception du mode auto/manual depuis MQTT."""
>>>>>>> Stashed changes
    global mode_auto
    if msg.topic == TOPIC_MODE:
        m = msg.payload.decode(errors="ignore").strip().lower()
        mode_auto = (m == "auto")
        print(f"[MQTT] Mode reçu: {m} -> mode_auto={mode_auto}", flush=True)

def mqtt_connect():
<<<<<<< Updated upstream
    """Initialise et connecte le client MQTT."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="OpenCVFaceTracker")
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[MQTT] Erreur de connexion: {e}", flush=True)
        return None
    client.subscribe(TOPIC_MODE)
    client.loop_start()
=======
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="OpenCVClient")
    c.on_message = on_message
    c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    c.subscribe(TOPIC_MODE)
    c.loop_start()
>>>>>>> Stashed changes
    print(f"[MQTT] Connecté à {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    return c

<<<<<<< Updated upstream
# --- FONCTIONS UTILITAIRES ---
def open_stream(url):
    """Ouvre le flux vidéo."""
=======
# =========================
# Video helpers
# =========================
def open_stream(url: str):
>>>>>>> Stashed changes
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return None
    return cap

<<<<<<< Updated upstream
def clamp(v, lo, hi):
    """Limite une valeur dans un intervalle [lo, hi]."""
    return max(lo, min(hi, v))

app = Flask(__name__)

frame_lock = threading.Lock()
latest_frame: Optional[bytes] = None


def generate_stream():
    while True:
        with frame_lock:
            frame = latest_frame
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")


@app.get("/stream")
def stream():
    return Response(generate_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


def process_loop():
    global current_pan, current_tilt, latest_frame
=======
def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def mean_brightness(gray: np.ndarray) -> float:
    # luminosité moyenne (0-255). Si tu es < ~40, la Haar galère souvent.
    return float(np.mean(gray))

# =========================
# Main loop
# =========================
def main():
    global current_pan, current_tilt
>>>>>>> Stashed changes

    client = mqtt_connect()
    if client is None:
        print("[SYSTEM] Arrêt du programme en raison de l'échec de la connexion MQTT.", flush=True)
        return

<<<<<<< Updated upstream
    # Boucle de connexion au flux vidéo
=======
    # Ouvrir le stream
>>>>>>> Stashed changes
    cap = None
    while cap is None:
        cap = open_stream(MJPEG_URL)
        if cap is None:
            print(f"[VIDEO] Impossible d'ouvrir {MJPEG_URL}. Nouvelle tentative dans 2s...", flush=True)
            time.sleep(2)

    print("[SYSTEM] Démarrage du face tracking.", flush=True)

    # Limite publication servo
    last_ctrl_publish = 0.0
    ctrl_interval = 0.05  # 20 Hz max

    # Publication overlay rectangles
    last_faces_publish = 0.0

    # Debug logs
    last_debug = 0.0
    frames = 0
    fps_t0 = time.time()

    while True:
        # Mesure du temps pour le calcul des FPS
        tickmark = cv2.getTickCount()

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

<<<<<<< Updated upstream
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_width = frame.shape[1]

        # --- BLOC DE DÉTECTION AVANCÉE ---
        all_faces = []
=======
        now = time.time()
        frames += 1

        # Traitement image
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Détection visage (plus permissive)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=SCALE_FACTOR,
            minNeighbors=MIN_NEIGHBORS,
            minSize=(MIN_SIZE, MIN_SIZE)
        )

        # =========================
        # 1) Publier rectangles (overlay web)
        # =========================
        if (now - last_faces_publish) >= FACES_INTERVAL:
            faces_payload = {
                "ts": now,
                "frame_w": int(frame.shape[1]),
                "frame_h": int(frame.shape[0]),
                "faces": [
                    {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
                    for (x, y, w, h) in faces[:FACES_MAX]
                ]
            }
            client.publish(STATUS_FACES_TOPIC, json.dumps(faces_payload), qos=0, retain=False)
            last_faces_publish = now

        # =========================
        # 2) Tracking pan/tilt (mode auto)
        # =========================
        if len(faces) > 0 and mode_auto:
            x, y, w, h = faces[0]
>>>>>>> Stashed changes

        # 1. Détection frontale
        faces_front = face_cascade.detectMultiScale(
            gray, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30)
        )
        for (x, y, w, h) in faces_front:
            all_faces.append([x, y, x + w, y + h])

        # 2. Détection de profil
        faces_profile = profile_cascade.detectMultiScale(
            gray, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30)
        )
        for (x, y, w, h) in faces_profile:
            all_faces.append([x, y, x + w, y + h])

        # 3. Détection de profil sur image inversée
        gray_flipped = cv2.flip(gray, 1)
        faces_profile_flipped = profile_cascade.detectMultiScale(
            gray_flipped, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30)
        )
        for (x, y, w, h) in faces_profile_flipped:
            # On re-convertit les coordonnées pour l'image originale
            all_faces.append([frame_width - (x + w), y, frame_width - x, y + h])

        # Tri des visages détectés pour un traitement cohérent
        all_faces = sorted(all_faces, key=operator.itemgetter(0, 1))

        # --- BLOC DE CONTRÔLE ---
        if len(all_faces) > 0 and mode_auto:
            # On prend la première face de la liste triée
            x1, y1, x2, y2 = all_faces[0]
            w, h = x2 - x1, y2 - y1

            # Centre du visage
            face_center_x = x1 + w / 2.0
            face_center_y = y1 + h / 2.0

            # Centre de l'image
            frame_center_x = frame.shape[1] / 2.0
            frame_center_y = frame.shape[0] / 2.0

            # Calcul de l'erreur
            error_x = face_center_x - frame_center_x
            error_y = face_center_y - frame_center_y

            moved = False
            # Ajustement du PAN (horizontal)
            if abs(error_x) > TOL:
                current_pan += (-STEP if error_x > 0 else STEP)
                moved = True

            # Ajustement du TILT (vertical)
            if abs(error_y) > TOL:
                current_tilt += (-STEP if error_y > 0 else STEP)
                moved = True

            current_pan = clamp(current_pan, MIN_ANGLE, MAX_ANGLE)
            current_tilt = clamp(current_tilt, MIN_ANGLE, MAX_ANGLE)

<<<<<<< Updated upstream
            # Publication des commandes MQTT si un mouvement est nécessaire
            now = time.time()
            if moved and (now - last_publish) > publish_interval:
                client.publish(TOPIC_PAN, str(int(current_pan)))
                client.publish(TOPIC_TILT, str(int(current_tilt)))
                last_publish = now
                print(
                    f"[CTRL] pan={current_pan} tilt={current_tilt} err=({error_x:.1f},{error_y:.1f})",
                    flush=True,
                )

        # --- BLOC D'AFFICHAGE ---
        # Dessine les rectangles autour de tous les visages détectés
        for (x, y, x2, y2) in all_faces:
            cv2.rectangle(frame, (x, y), (x2, y2), (0, 255, 0), 2)

        # Affiche les FPS
        fps = cv2.getTickFrequency() / (cv2.getTickCount() - tickmark)
        cv2.putText(frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (255, 0, 0), 2)

        # Affiche le mode actuel
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

        success, encoded = cv2.imencode(".jpg", frame)
        if success:
            with frame_lock:
                latest_frame = encoded.tobytes()

=======
            if moved and (now - last_ctrl_publish) > ctrl_interval:
                client.publish(TOPIC_PAN, str(current_pan))
                client.publish(TOPIC_TILT, str(current_tilt))
                last_ctrl_publish = now

                if DEBUG:
                    print(
                        f"[CTRL] pan={current_pan} tilt={current_tilt} err=({error_x:.1f},{error_y:.1f}) faces={len(faces)}",
                        flush=True
                    )

        # =========================
        # 3) Debug périodique
        # =========================
        if DEBUG and (now - last_debug) >= DEBUG_INTERVAL:
            # FPS approx
            dt = now - fps_t0
            fps = frames / dt if dt > 0 else 0.0

            lum = mean_brightness(gray)
            print(
                f"[DEBUG] fps={fps:.1f} faces={len(faces)} size={frame.shape[1]}x{frame.shape[0]} "
                f"brightness={lum:.1f} scale={SCALE_FACTOR} neigh={MIN_NEIGHBORS} min={MIN_SIZE}",
                flush=True
            )

            # reset fps window
            frames = 0
            fps_t0 = now
            last_debug = now
>>>>>>> Stashed changes

if __name__ == "__main__":
    worker = threading.Thread(target=process_loop, daemon=True)
    worker.start()
    app.run(host="0.0.0.0", port=int(os.getenv("STREAM_PORT", "5001")), threaded=True)
