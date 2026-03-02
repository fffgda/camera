# main.py - ESP32-S3 Cam Freenove (lemariva) + MJPEG stream + servos + MQTT

from machine import Pin, PWM
import network, time, socket, _thread, gc
import camera
from umqtt.simple import MQTTClient

# =========================
# CONFIG GLOBALE
# =========================
MQTT_BROKER  = "172.16.8.1"   # IP de la machine qui héberge Docker (hôte du broker Mosquitto)
MQTT_PORT    = 1883
MQTT_CLIENT_ID = b"esp32cam"

TOPIC_PAN    = b"esp32cam/cmd/pan"
TOPIC_TILT   = b"esp32cam/cmd/tilt"
TOPIC_MODE   = b"esp32cam/cmd/mode"

# IMPORTANT:
# D'apres Freenove/lemariva pour ESP32-S3 CAM :
# PCLK = GPIO13 et XCLK = GPIO15 -> NE PAS utiliser 13 ou 15 pour les servos.
PIN_SERVO_PAN  = 1   # A ADAPTER selon ton câblage (évite 13/15/4/5/6/7/8/9/10/11/12/16/17/18)
PIN_SERVO_TILT = 2   # A ADAPTER

SERVO_FREQ = 50

# =========================
# WIFI (on suppose boot.py a déjà connecté, mais on sécurise)
# =========================
sta = network.WLAN(network.STA_IF)
sta.active(True)
if sta.isconnected():
    ip = sta.ifconfig()[0]
    print("WiFi OK, IP:", ip)
else:
    print("WiFi pas connecté (boot.py devrait le faire).")

# =========================
# SERVOS
# =========================
servo_pan  = PWM(Pin(PIN_SERVO_PAN),  freq=SERVO_FREQ, duty=0)
servo_tilt = PWM(Pin(PIN_SERVO_TILT), freq=SERVO_FREQ, duty=0)

def angle_to_duty(angle):
    # Calibration standard (à ajuster selon tes servos)
    # MicroPython ESP32 PWM duty en 0..1023 (10 bits)
    angle = max(0, min(180, int(angle)))
    min_duty = 40    # ~0.5 ms
    max_duty = 115   # ~2.5 ms
    duty = min_duty + (max_duty - min_duty) * angle // 180
    return int(max(0, min(1023, duty)))

def set_servo_pan(angle):
    servo_pan.duty(angle_to_duty(angle))

def set_servo_tilt(angle):
    servo_tilt.duty(angle_to_duty(angle))

# Position initiale : centre
set_servo_pan(90)
set_servo_tilt(90)

# =========================
# CAMERA INIT (lemariva / Freenove)
# =========================
def camera_init():
    try:
        camera.deinit()
    except:
        pass

    # Mapping pins Freenove/lemariva ESP32-S3
    camera.init(0,
        d0=11, d1=9, d2=8, d3=10, d4=12, d5=18, d6=17, d7=16,
        format=camera.JPEG,
        framesize=camera.FRAME_QVGA,
        xclk_freq=camera.XCLK_10MHz,
        href=7, vsync=6, reset=-1, pwdn=-1,
        sioc=5, siod=4, xclk=15, pclk=13,
        fb_location=camera.PSRAM
    )
    camera.framesize(camera.FRAME_QVGA)  # 320x240 pour des FPS corrects
    camera.quality(20)
    camera.flip(0)
    camera.mirror(0)
    print("Caméra initialisée OK")

camera_init()
buf = camera.capture()
print("Test capture OK, bytes =", len(buf) if buf else None)
del buf
gc.collect()

# =========================
# SERVEUR HTTP MJPEG
# =========================
HOST = "0.0.0.0"
PORT = 81

BOUNDARY = b"frame"
HEADER_STREAM = (
    b"HTTP/1.0 200 OK\r\n"
    b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"
)

def http_response(conn, status="200 OK", content_type="text/html", body=b""):
    hdr = "HTTP/1.0 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n\r\n".format(
        status, content_type, len(body)
    )
    conn.send(hdr.encode() + body)

INDEX_HTML = b"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>ESP32-S3 Cam</title></head>
<body style="font-family: sans-serif;">
  <h2>ESP32-S3 Camera Stream</h2>
  <p>Stream: <a href="/stream">/stream</a></p>
  <img src="/stream" style="max-width: 100%; height: auto;" />
</body>
</html>
"""

def handle_client(conn, addr):
    try:
        req = conn.recv(1024)
        if not req:
            conn.close()
            return

        line = req.split(b"\r\n", 1)[0]
        parts = line.split()
        path = b"/"
        if len(parts) >= 2:
            path = parts[1]

        if path == b"/" or path == b"/index.html":
            http_response(conn, body=INDEX_HTML)

        elif path == b"/stream":
            conn.send(HEADER_STREAM)
            while True:
                frame = camera.capture()
                if not frame:
                    continue
                conn.send(b"--" + BOUNDARY + b"\r\n")
                conn.send(b"Content-Type: image/jpeg\r\n")
                conn.send(b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n")
                conn.send(frame)
                conn.send(b"\r\n")

        else:
            http_response(conn, status="404 Not Found", body=b"Not found")

    except Exception as e:
        print("Client fini:", addr, "err:", e)
    finally:
        try:
            conn.close()
        except:
            pass

def server_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(2)
    print("Serveur HTTP OK sur http://{}:{}/".format(sta.ifconfig()[0], PORT))
    while True:
        conn, addr = s.accept()
        _thread.start_new_thread(handle_client, (conn, addr))

# Lancer le serveur en thread secondaire
_thread.start_new_thread(server_loop, ())

# =========================
# MQTT - Réception des commandes pan/tilt
# =========================
def on_mqtt_message(topic, msg):
    """Callback appelé à chaque message MQTT reçu."""
    try:
        val = int(msg.decode("utf-8").strip())
    except Exception:
        print("MQTT: valeur invalide:", msg)
        return

    if topic == TOPIC_PAN:
        print("Pan ->", val)
        set_servo_pan(val)
    elif topic == TOPIC_TILT:
        print("Tilt ->", val)
        set_servo_tilt(val)
    elif topic == TOPIC_MODE:
        print("Mode ->", msg)
        # Le mode (auto/manual) est géré par OpenCV, pas besoin d'agir ici

def mqtt_connect():
    """Connexion au broker MQTT avec reconnexion automatique."""
    c = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=60)
    c.set_callback(on_mqtt_message)
    c.connect()
    c.subscribe(TOPIC_PAN)
    c.subscribe(TOPIC_TILT)
    c.subscribe(TOPIC_MODE)
    print("MQTT connecté, abonné pan/tilt/mode")
    return c

def mqtt_loop():
    """Boucle MQTT dans un thread dédié avec reconnexion."""
    while True:
        try:
            mqttc = mqtt_connect()
            while True:
                mqttc.check_msg()   # non-bloquant : traite 1 message s'il y en a
                time.sleep_ms(20)   # laisser du temps aux autres threads
        except Exception as e:
            print("MQTT erreur, reconnexion dans 3s:", e)
            time.sleep(3)

# Lancer la boucle MQTT en thread dédié
_thread.start_new_thread(mqtt_loop, ())

# =========================
# BOUCLE PRINCIPALE
# =========================
print("Système démarré. Stream: http://{}:81/stream".format(sta.ifconfig()[0]))

while True:
    time.sleep(5)
    gc.collect()   # nettoyage mémoire régulier
