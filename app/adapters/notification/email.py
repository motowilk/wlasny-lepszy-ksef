from email.message import EmailMessage
from smtplib import SMTP, SMTP_SSL

from app.core.config import settings


class EmailNotificationAdapter:
    @staticmethod
    def _validate_settings() -> None:
        if not settings.smtp_host:
            raise RuntimeError("SMTP_HOST must be configured before sending email notifications.")
        if settings.smtp_port not in {25, 465, 587}:
            raise RuntimeError(f"Unsupported SMTP_PORT={settings.smtp_port}.")
        if bool(settings.smtp_user) != bool(settings.smtp_password):
            raise RuntimeError("SMTP_USER and SMTP_PASSWORD must be configured together.")

    def send(self, recipient: str, subject: str, body: str) -> None:
        self._validate_settings()

        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)

        if settings.smtp_port == 465:
            # Implicit TLS (SMTPS)
            with SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
        else:
            # STARTTLS (ports 25 / 587 — always upgraded to TLS)
            with SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
