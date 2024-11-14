# stdlib
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pydantic import BaseModel

from .server_url import ServerURL

SOCKET_TIMEOUT = 5  # seconds

logger = logging.getLogger(__name__)


class SMTPClient(BaseModel):
    server: str
    port: int
    password: str | None = None
    username: str | None = None

    def create_email(self, sender: str, receiver: list[str], subject: str, body: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = ", ".join(receiver)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        return msg

    def send(self, sender: str, receiver: list[str], subject: str, body: str) -> None:
        if not (subject and body and receiver):
            raise ValueError("Subject, body, and recipient email(s) are required")

        msg = self.create_email(sender, receiver, subject, body)

        mail_url = ServerURL.from_url(f"smtp://{self.server}:{self.port}")
        mail_url = mail_url.as_container_host()
        try:
            with smtplib.SMTP(mail_url.host_or_ip, mail_url.port, timeout=SOCKET_TIMEOUT) as server:
                server.ehlo()
                if server.has_extn("STARTTLS"):
                    server.starttls()
                    server.ehlo()
                if self.username and self.password:
                    server.login(self.username, self.password)
                text = msg.as_string()
                server.sendmail(sender, ", ".join(receiver), text)
                return None
        except Exception as e:
            logger.error(f"Unable to send email. {e}")
            raise e

    @classmethod
    def check_credentials(cls, server: str, port: int, username: str, password: str) -> bool:
        """Check if the credentials are valid.

        Returns:
            bool: True if the credentials are valid, False otherwise.
        """
        try:
            mail_url = ServerURL.from_url(f"smtp://{server}:{port}")
            mail_url = mail_url.as_container_host()

            print(f"> Validating SMTP settings: {mail_url}")
            with smtplib.SMTP(mail_url.host_or_ip, mail_url.port, timeout=SOCKET_TIMEOUT) as smtp_server:
                smtp_server.ehlo()
                if smtp_server.has_extn("STARTTLS"):
                    smtp_server.starttls()
                    smtp_server.ehlo()
                smtp_server.login(username, password)
                return True
        except Exception as e:
            message = f"SMTP check_credentials failed. {e}"
            logger.error(message)
            raise e