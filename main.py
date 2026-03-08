# main.py - ESP32-S3 Cam Freenove (lemariva) + MJPEG stream + servos
# Etape 3.2 : PAS de MQTT pour l'instant (ENABLE_MQTT = False)

from machine import Pin, PWM
import network, time, socket, _thread, gc
import camera

# =========================
# CONFIG GLOBALE
# =========================
ENABLE_MQTT = False  # -> Mettre True plus tard (après Docker/Mosquitto)

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
servo_pan = PWM(Pin(PIN_SERVO_PAN), freq=SERVO_FREQ, duty=0)
servo_tilt = PWM(Pin(PIN_SERVO_TILT), freq=SERVO_FREQ, duty=0)

def angle_to_duty(angle):
    # Calibration standard (à ajuster selon tes servos)
    # MicroPython ESP32 PWM duty souvent en 0..1023 (10 bits)
    angle = max(0, min(180, int(angle)))
    min_duty = 40    # ~0.5 ms
    max_duty = 115   # ~2.5 ms
    duty = min_duty + (max_duty - min_duty) * angle // 180
    return int(max(0, min(1023, duty)))

def set_servo_pan(angle):
    servo_pan.duty(angle_to_duty(angle))

def set_servo_tilt(angle):
    servo_tilt.duty(angle_to_duty(angle))

# Position initiale
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

    # IMPORTANT: cette init correspond au mapping pins Freenove/lemariva
    camera.init(0,
        d0=11, d1=9, d2=8, d3=10, d4=12, d5=18, d6=17, d7=16,
        format=camera.JPEG,
        framesize=camera.FRAME_VGA,
        xclk_freq=camera.XCLK_10MHz,
        href=7, vsync=6, reset=-1, pwdn=-1,
        sioc=5, siod=4, xclk=15, pclk=13,
        fb_location=camera.PSRAM
    )

    # Réglages image
    camera.framesize(camera.FRAME_VGA)   # 640x480 (si trop lourd -> QVGA)
    camera.quality(12)                   # 0..63 (plus petit = meilleure qualité mais plus lourd)
    camera.flip(0)
    camera.mirror(0)

    print("Caméra initialisée OK")

camera_init()

# Test capture (validation étape 3.2)
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
HEADER_STREAM = b"HTTP/1.0 200 OK\r\n" \
                b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"

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

        # Parse rapide de la première ligne : GET /path HTTP/1.1
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
                # Ajuste la latence / FPS
                time.sleep_ms(80)  # ~12 FPS max (variable)

        else:
            http_response(conn, status="404 Not Found", body=b"Not found")

    except Exception as e:
        # Déconnexion client ou erreur capture
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
        # Un thread par client (si trop lourd, on peut gérer 1 seul client)
        _thread.start_new_thread(handle_client, (conn, addr))

# Lancer le serveur en thread
_thread.start_new_thread(server_loop, ())

# =========================
# BOUCLE PRINCIPALE (étape 3.2)
# =========================
print("Main loop OK (étape 3.2).")

while True:
    # Ici, plus tard: lecture MQTT, télémétrie, etc.
    time.sleep(1)
