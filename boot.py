# boot.py -- Configuration initiale Wi-Fi
import network, time

SSID = "Livebox-7A60"
PASSWORD = "Pinkfloyd1970!"

sta = network.WLAN(network.STA_IF)
sta.active(True)

if not sta.isconnected():
    print("Connexion au WiFi...", SSID)
    sta.connect(SSID, PASSWORD)

    timeout = 20  # 20 essais * 0.5s = 10 secondes
    while not sta.isconnected() and timeout > 0:
        time.sleep(0.5)
        timeout -= 1

    if sta.isconnected():
        print("Connecté, IP:", sta.ifconfig()[0])
        print("Config réseau:", sta.ifconfig())
    else:
        print("Échec de connexion WiFi")
else:
    print("WiFi déjà connecté")
    print("Config réseau:", sta.ifconfig())
