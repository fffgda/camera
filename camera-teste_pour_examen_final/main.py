# main.py
# ESP32-S3 CAM Freenove / lemariva
# Compatible avec :
# - Flux MJPEG: http://<ESP32_IP>:81/stream
# - Docker ai_detection: ESP32_STREAM_URL=http://<ESP32_IP>:81/stream
# - MQTT topics:
#     esp32cam/cmd/pan
#     esp32cam/cmd/tilt
#     esp32cam/cmd/mode
#
# Remarques :
# - Mettre ENABLE_MQTT = True quand Mosquitto est joignable depuis l'ESP32.
# - Les servos utilisent ici GPIO 21 et 20, à adapter selon ton câblage.
# - Ce code suppose que le Wi-Fi est déjà configuré ou connecté avant lancement.

from machine import Pin, PWM
import network
import time
import socket
import _thread
import gc
import camera

try:
    from umqtt.simple import MQTTClient
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


# =========================
# CONFIG GLOBALE
# =========================
ENABLE_MQTT = True

WIFI_WAIT_TIMEOUT_S = 20
MAIN_LOOP_SLEEP_S = 0.2

HOST = "0.0.0.0"
PORT = 81

# GPIO servos
PIN_SERVO_PAN = 21
PIN_SERVO_TILT = 20
SERVO_FREQ = 50

PAN_MIN = 0
PAN_MAX = 180
TILT_MIN = 0
TILT_MAX = 180

PAN_START = 90
TILT_START = 90

# MQTT
MQTT_CLIENT_ID = "esp32cam-servo"
MQTT_BROKER = "172.16.8.32"   # à adapter: IP de ton PC ou du broker Mosquitto
MQTT_PORT = 1883

TOPIC_PAN = b"esp32cam/cmd/pan"
TOPIC_TILT = b"esp32cam/cmd/tilt"
TOPIC_MODE = b"esp32cam/cmd/mode"

TOPIC_STATUS = b"esp32cam/status/device"
TOPIC_STATE = b"esp32cam/status/state"

MQTT_KEEPALIVE = 60
MQTT_RECONNECT_DELAY_S = 5

# HTTP / stream
BOUNDARY = b"frame"
HEADER_STREAM = (
    b"HTTP/1.0 200 OK\r\n"
    b"Cache-Control: no-cache\r\n"
    b"Pragma: no-cache\r\n"
    b"Connection: close\r\n"
    b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"
)

INDEX_HTML = b"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ESP32-S3 CAM</title>
</head>
<body style="font-family:sans-serif;">
  <h2>ESP32-S3 Camera Stream</h2>
  <p><a href="/stream">Ouvrir le stream MJPEG</a></p>
  <img src="/stream" style="max-width:100%;height:auto;" />
</body>
</html>
"""

# Etat global
current_pan = PAN_START
current_tilt = TILT_START
current_mode = "manual"

mqtt_client = None
mqtt_connected = False

state_lock = _thread.allocate_lock()


# =========================
# OUTILS
# =========================
def clamp(value, minimum, maximum):
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def sleep_ms_safe(ms):
    try:
        time.sleep_ms(ms)
    except AttributeError:
        time.sleep(ms / 1000.0)


def conn_send_all(conn, data):
    view = memoryview(data)
    total_sent = 0

    while total_sent < len(data):
        sent = conn.send(view[total_sent:])
        if sent is None or sent <= 0:
            raise OSError("send failed")
        total_sent += sent


def http_response(conn, status="200 OK", content_type="text/html", body=b""):
    header = (
        "HTTP/1.0 {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n\r\n"
    ).format(status, content_type, len(body))
    conn_send_all(conn, header.encode())
    if body:
        conn_send_all(conn, body)


# =========================
# WIFI
# =========================
def wait_for_wifi(timeout_s=WIFI_WAIT_TIMEOUT_S):
    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    start = time.time()
    while (not sta.isconnected()) and ((time.time() - start) < timeout_s):
        print("Attente Wi-Fi...")
        time.sleep(0.5)

    if sta.isconnected():
        ip = sta.ifconfig()[0]
        print("WiFi OK, IP:", ip)
        return sta

    print("WiFi non connecté après timeout.")
    return sta


# =========================
# SERVOS
# =========================
servo_pan = PWM(Pin(PIN_SERVO_PAN), freq=SERVO_FREQ, duty=0)
servo_tilt = PWM(Pin(PIN_SERVO_TILT), freq=SERVO_FREQ, duty=0)


def angle_to_duty(angle):
    # Calibration standard SG90 / MG90 à ajuster selon ton montage.
    # MicroPython ESP32: duty sur 10 bits, généralement 0..1023.
    angle = clamp(int(angle), 0, 180)
    min_duty = 40
    max_duty = 115
    return int(min_duty + ((max_duty - min_duty) * angle) // 180)


def set_servo_pan(angle):
    global current_pan

    angle = clamp(int(angle), PAN_MIN, PAN_MAX)
    with state_lock:
        current_pan = angle
    servo_pan.duty(angle_to_duty(angle))


def set_servo_tilt(angle):
    global current_tilt

    angle = clamp(int(angle), TILT_MIN, TILT_MAX)
    with state_lock:
        current_tilt = angle
    servo_tilt.duty(angle_to_duty(angle))


def set_mode(mode):
    global current_mode

    if mode not in ("auto", "manual"):
        return

    with state_lock:
        current_mode = mode


def get_state_payload():
    with state_lock:
        payload = (
            '{{"pan":{},"tilt":{},"mode":"{}"}}'.format(
                current_pan,
                current_tilt,
                current_mode,
            )
        )
    return payload


# =========================
# CAMERA
# =========================
def camera_init():
    try:
        camera.deinit()
        sleep_ms_safe(200)
    except Exception:
        pass

    camera.init(
        0,
        d0=11,
        d1=9,
        d2=8,
        d3=10,
        d4=12,
        d5=18,
        d6=17,
        d7=16,
        format=camera.JPEG,
        framesize=camera.FRAME_QVGA,
        xclk_freq=camera.XCLK_10MHz,
        href=7,
        vsync=6,
        reset=-1,
        pwdn=-1,
        sioc=5,
        siod=4,
        xclk=15,
        pclk=13,
        fb_location=camera.PSRAM,
    )

    # 320x240 réel
    camera.framesize(camera.FRAME_QVGA)
    camera.quality(20)
    camera.flip(0)
    camera.mirror(0)

    print("Camera initialisée OK.")


def test_capture():
    frame = camera.capture()
    size = len(frame) if frame else 0
    print("Test capture OK, bytes =", size)
    del frame
    gc.collect()


# =========================
# MQTT
# =========================
def mqtt_publish(topic, payload, retain=False):
    global mqtt_connected

    if (not ENABLE_MQTT) or (not MQTT_AVAILABLE):
        return

    if not mqtt_connected or mqtt_client is None:
        return

    try:
        mqtt_client.publish(topic, payload, retain=retain)
    except Exception as error:
        mqtt_connected = False
        print("MQTT publish error:", error)


def mqtt_callback(topic, msg):
    try:
        if topic == TOPIC_PAN:
            angle = int(msg.decode().strip())
            set_servo_pan(angle)
            print("MQTT PAN:", angle)

        elif topic == TOPIC_TILT:
            angle = int(msg.decode().strip())
            set_servo_tilt(angle)
            print("MQTT TILT:", angle)

        elif topic == TOPIC_MODE:
            mode = msg.decode().strip().lower()
            set_mode(mode)
            print("MQTT MODE:", mode)

        mqtt_publish(TOPIC_STATE, get_state_payload())
    except Exception as error:
        print("MQTT callback error:", error)


def mqtt_connect():
    global mqtt_client, mqtt_connected

    if not ENABLE_MQTT:
        print("MQTT désactivé.")
        mqtt_connected = False
        return False

    if not MQTT_AVAILABLE:
        print("Module umqtt.simple introuvable, MQTT désactivé.")
        mqtt_connected = False
        return False

    try:
        client = MQTTClient(
            client_id=MQTT_CLIENT_ID,
            server=MQTT_BROKER,
            port=MQTT_PORT,
            keepalive=MQTT_KEEPALIVE,
        )
        client.set_callback(mqtt_callback)
        client.connect()
        client.subscribe(TOPIC_PAN)
        client.subscribe(TOPIC_TILT)
        client.subscribe(TOPIC_MODE)

        mqtt_client = client
        mqtt_connected = True

        print("MQTT connecté à {}:{}.".format(MQTT_BROKER, MQTT_PORT))
        print("MQTT subscribed:", TOPIC_PAN, TOPIC_TILT, TOPIC_MODE)

        mqtt_publish(TOPIC_STATUS, b'{"status":"online"}', retain=True)
        mqtt_publish(TOPIC_STATE, get_state_payload(), retain=True)
        return True

    except Exception as error:
        mqtt_connected = False
        mqtt_client = None
        print("MQTT connexion échouée:", error)
        return False


def mqtt_loop():
    global mqtt_connected

    while True:
        if not ENABLE_MQTT:
            time.sleep(2)
            continue

        if not mqtt_connected or mqtt_client is None:
            mqtt_connect()
            time.sleep(MQTT_RECONNECT_DELAY_S)
            continue

        try:
            mqtt_client.check_msg()
        except Exception as error:
            mqtt_connected = False
            print("MQTT check_msg error:", error)
            time.sleep(MQTT_RECONNECT_DELAY_S)

        time.sleep(0.05)


# =========================
# HTTP / MJPEG
# =========================
def send_jpeg_part(conn, frame):
    conn_send_all(conn, b"--" + BOUNDARY + b"\r\n")
    conn_send_all(conn, b"Content-Type: image/jpeg\r\n")
    conn_send_all(
        conn,
        b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n",
    )
    conn_send_all(conn, frame)
    conn_send_all(conn, b"\r\n")


def stream_loop(conn):
    while True:
        frame = camera.capture()
        if not frame:
            sleep_ms_safe(20)
            continue

        send_jpeg_part(conn, frame)
        del frame
        gc.collect()
        sleep_ms_safe(30)


def handle_client(conn, addr):
    try:
        conn.settimeout(10)
        request = conn.recv(1024)

        if not request:
            return

        first_line = request.split(b"\r\n", 1)[0]
        parts = first_line.split()
        path = b"/"

        if len(parts) >= 2:
            path = parts[1]

        if path == b"/" or path == b"/index.html":
            http_response(conn, body=INDEX_HTML)
            return

        if path == b"/health":
            http_response(
                conn,
                content_type="application/json",
                body=b'{"status":"ok"}',
            )
            return

        if path == b"/state":
            http_response(
                conn,
                content_type="application/json",
                body=get_state_payload().encode(),
            )
            return

        if path == b"/stream":
            conn_send_all(conn, HEADER_STREAM)
            stream_loop(conn)
            return

        http_response(conn, status="404 Not Found", body=b"Not found")

    except Exception as error:
        print("Client fini:", addr, "err:", error)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        gc.collect()


def server_loop(sta):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(2)

    ip = "0.0.0.0"
    try:
        ip = sta.ifconfig()[0]
    except Exception:
        pass

    print("Serveur HTTP OK sur http://{}:{}/".format(ip, PORT))

    while True:
        try:
            conn, addr = server.accept()
            print("Client connecté:", addr)
            _thread.start_new_thread(handle_client, (conn, addr))
        except Exception as error:
            print("HTTP accept error:", error)
            time.sleep(1)


# =========================
# BOOT
# =========================
def boot():
    print("Boot ESP32-CAM...")
    sta = wait_for_wifi()

    camera_init()
    test_capture()

    set_servo_pan(PAN_START)
    set_servo_tilt(TILT_START)
    set_mode("manual")

    _thread.start_new_thread(server_loop, (sta,))
    _thread.start_new_thread(mqtt_loop, ())

    print("Main loop OK.")
    print("Mode initial:", current_mode)
    print("Pan initial:", current_pan)
    print("Tilt initial:", current_tilt)

    while True:
        # Publication périodique optionnelle de l'état.
        if ENABLE_MQTT and mqtt_connected:
            try:
                mqtt_publish(TOPIC_STATE, get_state_payload(), retain=True)
            except Exception as error:
                print("MQTT state publish error:", error)

        time.sleep(MAIN_LOOP_SLEEP_S)


boot()