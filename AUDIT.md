# Rapport d'Audit - Projet ESP32-CAM Person Counting

**Date:** 19 avril 2026

---

## 1. Sécurité

### 1.1 Identifiants par défaut durscodés (CRITIQUE)
| Fichier | Problème |
|---------|----------|
| `.env:41-43` | `DEFAULT_ADMIN_PASSWORD=admin123` et `DEFAULT_VIEWER_PASSWORD=viewer123` exposés |
| `.env:37` | `FLASK_SECRET_KEY=change-this-secret` par défaut |
| `docker-compose.yml:85-90` | Identifiants par défaut dans les variables d'environnement |

**Risque**: Accès non autorisé facile au tableau de bord.

### 1.2 MQTT sans authentification
- Mosquitto tourne sans utilisateur/mot de passe
- Aucune configuration TLS pour MQTT

### 1.3 Pas de HTTPS
- Le serveur Flask écoute en clair sur le port 8080
- Les mots de passe transitent en clair sur le réseau

---

## 2. Configuration & Environment

### 2.1 Incohérence IPs MQTT
| Fichier | IP MQTT Broker |
|---------|----------------|
| `main.py:11` | `172.16.8.1` (hardcodé) |
| `docker-compose.yml:28` | `mqtt` (DNS Docker) |

**Problème**: Le code ESP32 utilise une IP fixe qui doit correspondre à la machine hôte Docker. Le réseau Docker et le réseau WiFi de l'ESP32 doivent être pontés.

### 2.2 WiFi credentials non configurables via Docker
- `boot.py:3` importe `wifi_config.py` localement (hors de Docker)
- Comportement normal mais non documenté

---

## 3. Qualité du Code

### 3.1 Gestion d'erreurs insuffisante
| Fichier | Ligne | Problème |
|---------|-------|----------|
| `main.py:69` | `except:` | Bare except, capture tout y compris SystemExit |
| `opencv/app.py:232` | `cap.read()` | Pas de gestion si le flux ESP32 devient indisponible temporairement |

### 3.2 Person counter incomplet
- `opencv/counting.py:22-24` : Logique incohérente - incrémente seulement si `current > last_count`, ne gère pas le départ des personnes

### 3.3 State global non thread-safe
- `web/app.py:53-71` : Les dictionnaires `state`, `last_faces`, `last_people` sont modifiés par MQTT callback et requêtes API sans synchronisation complète

---

## 4. Architecture

### 4.1 Dépendance réseau non documentée
- Le flux MQTT entre Docker et ESP32 nécessite un pont/routeur entre le réseau Docker (`172.17.x.x`) et le réseau WiFi de l'ESP32
- Pas de configuration de pont MQTT dans le projet

### 4.2 Pas de fallback si OpenCV unavailable
- Si le conteneur OpenCV redémarre, le proxy vidéo (`/video`) ne gère pas l'erreur proprement

### 4.3 Health checks insuffisants
- Health check OpenCV fait juste un curl sur le stream - ne vérifie pas si YOLO fonctionne

---

## 5. Documentation & Maintenabilité

### 5.1 README minimaliste
- Seulement 13 lignes, aucune info sur l'architecture ou le troubleshooting

### 5.2 Pas de tests
- Aucune suite de tests configurée
- Impossible de vérifier le comportement après modifications

---

## 6. Priorisation des Correctifs

### Priorité 1 (Sécurité)
1. Changer les mots de passe par défaut
2. Configurer une `FLASK_SECRET_KEY` sécurisée
3. Activer l'authentification MQTT

### Priorité 2 (Stabilité)
4. Corriger la logique du `PersonCounter`
5. Améliorer la gestion des reconnexions flux vidéo
6. Remplacer les bare `except:` par une gestion appropriée

### Priorité 3 (Architecture)
7. Documenter la configuration réseau requise (pont MQTT)
8. Ajouter des tests de base
9. Améliorer les health checks

---

## Résumé

| Catégorie | Problèmes |
|-----------|-----------|
| Sécurité | 6 (passwords par défaut, pas de TLS, pas de HTTPS) |
| Configuration | 2 (incohérence IP, WiFi hors Docker) |
| Qualité code | 3 (exception handling, thread safety, counter) |
| Architecture | 3 (réseau, fallback, health check) |
| Documentation | 2 (README, tests) |

**Score global**: 6/10 - Projet fonctionnel mais avec des faiblesses sécurité et stabilité importantes à corriger avant production.