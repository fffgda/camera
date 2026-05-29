# ESP32-CAM Person Counting System

Système de comptage de personnes en temps réel avec détection YOLO, suivi pan/tilt et dashboard web.

## Architecture

```
┌──────────────┐    MJPEG    ┌──────────────┐    MQTT     ┌──────────────┐
│   ESP32-S3   │────────────>│   OpenCV     │────────────>│     Web      │
│   (Camera)   │   Stream    │  (YOLO v8)   │   (Mosquitto)│  (Flask)     │
└──────────────┘             └──────────────┘             └──────────────┘
      │                                                    │
      │ MQTT                                              │ HTTP
      │ pan/tilt                                          │ Dashboard
      └────────────────────────────────────────────────────┘
```

## Composants

| Service | Description | Port |
|---------|-------------|------|
| `mqtt` | Broker Mosquitto | 1883 |
| `opencv` | Détection YOLO + tracking | 5001 |
| `web` | Dashboard Flask | 8080 |
| `nginx` | Reverse-proxy TLS (certificats auto-signés) | 80 → 443 |

## Prérequis

- Docker + Docker Compose
- ESP32-S3 avec firmware MicroPython (Freenove/lemariva)
- Réseau: l'ESP32 et la machine Docker doivent être sur le même réseau local

### Configuration réseau requise

**Pont MQTT Docker ↔ Réseau local:**

Le broker MQTT tourne dans Docker. L'ESP32 est sur votre réseau WiFi local. Pour qu'ils communiquent:

1. Utilisez l'IP de la machine hôte Docker (ex: `172.16.8.1`) dans `main.py` pour `MQTT_BROKER`
2. Ou configurez un pont MQTT (ex: `mqtt-forwarder`)

## Installation

1. **Copier la configuration:**
   ```bash
   cp .env-example .env
   ```

2. **Configurer l'IP de l'ESP32 dans `.env`:**
   ```env
   ESP32_IP=192.168.1.XXX
   ```

3. **Configurer les mots de passe (IMPORTANT - sécurité):**
   ```env
   FLASK_SECRET_KEY=une-cle-securisee-tres-longue
   DEFAULT_ADMIN_PASSWORD=mon-super-password
   DEFAULT_VIEWER_PASSWORD=un-autre-password
   ```

4. **Lancer les services:**
   ```bash
   docker compose up --build
   ```

5. **Déployer le firmware ESP32:**
   ```bash
   # Via Thonny ou ampy
   ampy --port /dev/ttyUSB0 put boot.py
   ampy --port /dev/ttyUSB0 put main.py
   ```

## HTTPS (TLS) avec Nginx

Nginx agit comme reverse-proxy TLS. Le trafic HTTP (port 80) est automatiquement redirigé vers HTTPS (port 443).

### 1. Générer les certificats auto-signés

```bash
# Créer le dossier et générer une clé + certificat valide 10 ans
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem \
  -out nginx/ssl/cert.pem \
  -subj "/C=FR/ST=France/L=Paris/O=Home/CN=localhost"
```

> **Production :** remplacez par des certificats signés par une CA (Let's Encrypt, ZeroSSL).

### 2. Lancer les services

```bash
docker compose up --build
```

### 3. Accéder au dashboard

Ouvrir **https://localhost** dans le navigateur.

Le navigateur affichera un avertissement de sécurité (certificat auto-signé). Pour les tests : cliquez "Avancé" → "Continuer vers localhost".

### 4. (Optionnel) Certificats Let's Encrypt

Si le serveur a un nom de domaine public :

```bash
# Installer certbot, puis :
certbot certonly --standalone -d votre-domaine.fr
# Copier les certificats :
cp /etc/letsencrypt/live/votre-domaine.fr/fullchain.pem nginx/ssl/cert.pem
cp /etc/letsencrypt/live/votre-domaine.fr/privkey.pem nginx/ssl/key.pem
docker compose up --build nginx
```

---

## Utilisation

- **Dashboard:** https://localhost (port 443, redirection auto depuis le port 80)
- **Stream brut ESP32:** http://<ESP32_IP>:81/stream
- **Stream traité OpenCV:** http://localhost:5001/stream

### Identifiants par défaut

- Admin: `admin` / `admin123`
- Viewer: `viewer` / `viewer123`

**→ Changer immédiatement en production!**

## Variables d'environnement

### ESP32 / OpenCV

| Variable | Défaut | Description |
|----------|--------|-------------|
| `ESP32_IP` | - | IP de l'ESP32 sur le réseau local |
| `YOLO_CONF` | 0.45 | Seuil de confiance YOLO (0-1) |
| `DETECT_EVERY_N` | 2 | Détecter 1 frame sur N |
| `MOTION_ENABLED` | 1 | Activer détection mouvement |

### Alertes

| Variable | Défaut | Description |
|----------|--------|-------------|
| `ALERT_THRESHOLD` | 5 | Déclenchement alerte si >= |
| `ALERT_COOLDOWN` | 300 | Secondes entre alertes |
| `ALERT_WEBHOOK_URL` | - | URL webhook (Telegram/Discord) |

### Authentification

| Variable | Défaut | Description |
|----------|--------|-------------|
| `FLASK_SECRET_KEY` | - | Clé secrète Flask (REQUIRED) |
| `DEFAULT_ADMIN_PASSWORD` | - | Mot de passe admin (REQUIRED) |

## Troubleshooting

### L'ESP32 ne se connecte pas au WiFi
- Vérifier `wifi_config.py` avec les bons SSID/mot de passe
- Vérifier que l'ESP32 est sur le même réseau que la machine Docker

### Pas de flux vidéo
```bash
# Tester le flux ESP32 directement
curl http://<ESP32_IP>:81/stream

# Tester le flux OpenCV
curl http://localhost:5001/stream
```

### MQTT ne connecte pas
```bash
# Vérifier les logs
docker compose logs mqtt

# Tester la connexion
docker compose exec mqtt mosquitto_pub -t test -m "hello"
```

### Nginx ne démarre pas (certificats manquants)

```bash
# Erreur typique : nginx/ssl/cert.pem introuvable
# Solution :
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem \
  -out nginx/ssl/cert.pem \
  -subj "/C=FR/ST=France/L=Paris/O=Home/CN=localhost"
docker compose up --build nginx
```

### Les commandes pan/tilt ne fonctionnent pas
- Vérifier que l'IP MQTT dans `main.py` (ESP32) correspond à la machine hôte Docker
- Le réseau Docker (`172.17.x.x`) n'est pas accessible depuis l'ESP32 directement

## Commandes utiles

```bash
# Démarrer un service spécifique
docker compose up --build opencv

# Voir les logs
docker compose logs -f opencv
docker compose logs -f web

# Arrêter tout
docker compose down

# Reconstruire sans cache
docker compose build --no-cache
```

## License

MIT

# Credits
     
-  **ESP32 Firmware & Servo Control:** [@mou1234568](https://github.com/mou1234568)
-  **OpenCV Face Detection & Tracking:** [@mou1234568](https://github.com/mou1234568)
-  **YOLO / Ultralytics Integration:** [@mou1234568](https://github.com/mou1234568), [@Ravenbaudry](https://github.com/Ravenbaudry)
-  **Docker Architecture (MQTT, PostgreSQL):** [@Ravenbaudry](https://github.com/Ravenbaudry)
-  **Web UI & Video Stream:** [@Ravenbaudry](https://github.com/Ravenbaudry)
-  **Système de login par rôles:** [@Ravenbaudry](https://github.com/Ravenbaudry)
-  **SSE (Server-Sent Events):** [@mou1234568](https://github.com/mou1234568)
-  **Reverse Proxy & SSL:** [@mou1234568](https://github.com/mou1234568), [@Ravenbaudry](https://github.com/Ravenbaudry)
-  **Optimisations FPS & Stream:** [@Ravenbaudry](https://github.com/Ravenbaudry)
-  **Données d'entraînement & MCD:** [@mou1234568](https://github.com/mou1234568)