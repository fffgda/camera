import os
import time
import cv2
import numpy as np
import paho.mqtt.client as mqtt
import operator

# --- CONFIGURATION (du Code 1) ---
# Adresses et URL
ESP32_IP = os.getenv("ESP32_IP", "192.168.1.49") # J'ai mis l'IP de votre exemple
MJPEG_URL = os.getenv("MJPEG_URL", f"http://{ESP32_IP}:81/stream")

# Configuration MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")  # IMPORTANT: nom du service docker ou IP du broker
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PAN = os.getenv("TOPIC_PAN", "esp32cam/cmd/pan")
TOPIC_TILT = os.getenv("TOPIC_TILT", "esp32cam/cmd/tilt")
TOPIC_MODE = os.getenv("TOPIC_MODE", "esp32cam/cmd/mode")

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

# --- FONCTIONS MQTT (du Code 1) ---
def on_message(client, userdata, msg):
    """Callback pour la réception des messages MQTT."""
    global mode_auto
    if msg.topic == TOPIC_MODE:
        m = msg.payload.decode(errors="ignore").strip().lower()
        mode_auto = (m == "auto")
        print(f"[MQTT] Mode reçu: {m} -> mode_auto={mode_auto}", flush=True)

def mqtt_connect():
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
    print(f"[MQTT] Connecté à {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    return client

# --- FONCTIONS UTILITAIRES ---
def open_stream(url):
    """Ouvre le flux vidéo."""
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return None
    return cap

def clamp(v, lo, hi):
    """Limite une valeur dans un intervalle [lo, hi]."""
    return max(lo, min(hi, v))

# --- FONCTION PRINCIPALE (Fusion) ---
def main():
    global current_pan, current_tilt

    client = mqtt_connect()
    if client is None:
        print("[SYSTEM] Arrêt du programme en raison de l'échec de la connexion MQTT.", flush=True)
        return

    # Boucle de connexion au flux vidéo
    cap = None
    while cap is None:
        cap = open_stream(MJPEG_URL)
        if cap is None:
            print(f"[VIDEO] Impossible d'ouvrir {MJPEG_URL}. Nouvelle tentative dans 2s...", flush=True)
            time.sleep(2)

    print("[SYSTEM] Démarrage du face tracking.", flush=True)

    last_publish = 0
    publish_interval = 0.05  # 20 Hz max

    while True:
        # Mesure du temps pour le calcul des FPS
        tickmark = cv2.getTickCount()

        ret, frame = cap.read()
        if not ret or frame is None:
            print("[VIDEO] Frame invalide, reconnexion...", flush=True)
            cap.release()
            time.sleep(1)
            cap = None
            while cap is None:
                cap = open_stream(MJPEG_URL)
                if cap is None:
                    print(f"[VIDEO] Reconnexion échouée. Nouvelle tentative dans 2s...", flush=True)
                    time.sleep(2)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_width = frame.shape[1]
        
        # --- BLOC DE DÉTECTION AVANCÉE (du Code 2) ---
        all_faces = []
        
        # 1. Détection frontale
        faces_front = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30))
        for (x, y, w, h) in faces_front:
            all_faces.append([x, y, x + w, y + h])

        # 2. Détection de profil
        faces_profile = profile_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30))
        for (x, y, w, h) in faces_profile:
            all_faces.append([x, y, x + w, y + h])

        # 3. Détection de profil sur image inversée
        gray_flipped = cv2.flip(gray, 1)
        faces_profile_flipped = profile_cascade.detectMultiScale(gray_flipped, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30))
        for (x, y, w, h) in faces_profile_flipped:
            # On re-convertit les coordonnées pour l'image originale
            all_faces.append([frame_width - (x + w), y, frame_width - x, y + h])

        # Tri des visages détectés pour un traitement cohérent
        all_faces = sorted(all_faces, key=operator.itemgetter(0, 1))
        
        # --- BLOC DE CONTRÔLE (du Code 1, adapté) ---
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

            # Publication des commandes MQTT si un mouvement est nécessaire
            now = time.time()
            if moved and (now - last_publish) > publish_interval:
                client.publish(TOPIC_PAN, str(int(current_pan)))
                client.publish(TOPIC_TILT, str(int(current_tilt)))
                last_publish = now
                print(f"[CTRL] pan={current_pan} tilt={current_tilt} err=({error_x:.1f},{error_y:.1f})", flush=True)

        # --- BLOC D'AFFICHAGE (du Code 2) ---
        # Dessine les rectangles autour de tous les visages détectés
        for (x, y, x2, y2) in all_faces:
             cv2.rectangle(frame, (x, y), (x2, y2), (0, 255, 0), 2)
        
        # Affiche les FPS
        fps = cv2.getTickFrequency() / (cv2.getTickCount() - tickmark)
        cv2.putText(frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (255, 0, 0), 2)
        
        # Affiche le mode actuel
        mode_text = f"Mode: {'AUTO' if mode_auto else 'MANUEL'}"
        cv2.putText(frame, mode_text, (10, 60), cv2.FONT_HERSHEY_PLAIN, 2, (0, 0, 255) if mode_auto else (0, 255, 255), 2)
        
        # Montre l'image
        cv2.imshow('Face Tracking', frame)

        # Quitter avec la touche 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Nettoyage
    print("[SYSTEM] Arrêt du programme.", flush=True)
    cap.release()
    cv2.destroyAllWindows()
    client.loop_stop()

if __name__ == "__main__":
    main()