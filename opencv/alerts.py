import json
import os
import smtplib
import time
from email.mime.text import MIMEText
from urllib.request import Request, urlopen


class AlertManager:
    """Handles alert notifications via webhook and email."""

    def __init__(self):
        self.threshold = int(os.getenv("ALERT_THRESHOLD", "5"))
        self.cooldown = int(os.getenv("ALERT_COOLDOWN", "300"))

        # Webhook config (Telegram, Discord, Slack)
        self.webhook_url = os.getenv("ALERT_WEBHOOK_URL", "")

        # SMTP config
        self.smtp_host = os.getenv("ALERT_SMTP_HOST", "")
        self.smtp_port = int(os.getenv("ALERT_SMTP_PORT", "587"))
        self.smtp_user = os.getenv("ALERT_SMTP_USER", "")
        self.smtp_pass = os.getenv("ALERT_SMTP_PASS", "")
        self.email_to = os.getenv("ALERT_EMAIL_TO", "")

        self.last_alert_time = 0

    def check_threshold(self, count):
        """Check if count exceeds threshold and send alert if cooldown expired."""
        if count < self.threshold:
            return

        now = time.time()
        if (now - self.last_alert_time) < self.cooldown:
            return

        self.last_alert_time = now
        message = f"ALERTE: {count} personnes detectees (seuil: {self.threshold})"
        print(f"[ALERT] {message}", flush=True)

        # Send webhook
        if self.webhook_url:
            self._send_webhook(message)

        # Send email
        if self.smtp_host and self.email_to:
            self._send_email(message)

    def _send_webhook(self, message):
        """Send alert via webhook (works with Telegram/Discord/Slack)."""
        try:
            payload = json.dumps({"text": message}).encode("utf-8")
            req = Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urlopen(req, timeout=10)
            print("[ALERT] Webhook envoye", flush=True)
        except Exception as e:
            print(f"[ALERT] Erreur webhook: {e}", flush=True)

    def _send_email(self, message):
        """Send alert via SMTP email."""
        try:
            msg = MIMEText(message)
            msg["Subject"] = "Alerte Camera - Personnes detectees"
            msg["From"] = self.smtp_user
            msg["To"] = self.email_to

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)

            print("[ALERT] Email envoye", flush=True)
        except Exception as e:
            print(f"[ALERT] Erreur email: {e}", flush=True)
