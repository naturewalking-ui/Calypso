# modules/email_service.py

import email
import email.utils
import email.header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
import imaplib
import logging
from pathlib import Path
import re
import smtplib
import socket
import ssl
import time
import html
import os
from typing import Any, Dict, List, Optional, Tuple

from modules.config import config
from modules.settings_manager import settings_manager

logger = logging.getLogger("Calypso.Email")


class EmailService:
    def __init__(
        self,
        sender_email: Optional[str] = None,
        app_password: Optional[str] = None,
        recipient_email: Optional[str] = None
    ):
        self.smtp_server = "smtp.gmail.com"
        self.imap_server = "imap.gmail.com"
        self.imap_port = 993

        self._sender_override = sender_email
        self._app_password_override = app_password
        self._recipient_override = recipient_email

        self.attachment_dir = config.BASE_DIR / "workspace" / "email_attachments"
        self.attachment_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sender_email(self) -> str:
        if self._sender_override:
            return str(self._sender_override).strip()
        return str(settings_manager.get("gmail_address") or getattr(config, "GMAIL_ADDRESS", "") or "").strip()

    @property
    def app_password(self) -> str:
        if self._app_password_override:
            return str(self._app_password_override).replace(" ", "").strip()
        raw = settings_manager.get("gmail_app_password") or getattr(config, "GMAIL_APP_PASSWORD", "") or ""
        return str(raw).replace(" ", "").strip()

    @property
    def recipient_email(self) -> str:
        if self._recipient_override:
            return str(self._recipient_override).strip()
        return str(settings_manager.get("user_email") or getattr(config, "USER_EMAIL", "") or "").strip()

    @property
    def auto_send(self) -> bool:
        return bool(settings_manager.get("gmail_auto_send", getattr(config, "GMAIL_AUTO_SEND", False)))

    @property
    def is_configured(self) -> bool:
        if self._sender_override is None and not bool(settings_manager.get("email_enabled", False)):
            return False
        return bool(self.sender_email and self.app_password and self.recipient_email)

    def _get_smtp_connection(self, timeout: int = 15):
        """
        Connects to Gmail SMTP using a resilient dual-port strategy:
        1. Direct SSL on Port 465 (bypasses ISP port 587 filters)
        2. Fallback to Port 587 with STARTTLS
        """
        ssl_ctx = ssl.create_default_context()
        err_log = []

        # Strategy 1: Direct SSL over Port 465
        try:
            server = smtplib.SMTP_SSL(self.smtp_server, 465, timeout=timeout, context=ssl_ctx)
            server.login(self.sender_email, self.app_password)
            return server
        except Exception as e:
            err_log.append(f"Port 465 SSL failed ({e})")

        # Strategy 2: STARTTLS over Port 587
        try:
            server = smtplib.SMTP(self.smtp_server, 587, timeout=timeout)
            server.ehlo()
            server.starttls(context=ssl_ctx)
            server.ehlo()
            server.login(self.sender_email, self.app_password)
            return server
        except Exception as e:
            err_log.append(f"Port 587 STARTTLS failed ({e})")

        raise ConnectionError(" | ".join(err_log))

    def verify_connection(self) -> Tuple[bool, str]:
        if not self.is_configured:
            return False, "Email credentials missing (gmail_address, gmail_app_password, or user_email not set)."

        try:
            with self._get_smtp_connection(timeout=12) as server:
                pass
            return True, "SMTP connection & Google authentication successful."
        except smtplib.SMTPAuthenticationError:
            return False, "Authentication failed: Check your Gmail address and 16-character App Password."
        except Exception as e:
            logger.error(f"[Email] Verification failed: {e}")
            return False, f"SMTP connection failed: {e}"

    def send_test_email(self, to_email: Optional[str] = None) -> Tuple[bool, str]:
        """Dispatches a diagnostic test email to verify credentials and delivery."""
        if not self.is_configured:
            return False, "Email credentials missing (gmail_address, gmail_app_password, or user_email not set)."

        target_recipient = to_email or self.recipient_email
        ai_name = settings_manager.get("ai_name", "Calypso")
        subject = f"✨ [{ai_name}] Email Connectivity Verification"
        body = (
            f"Hello,\n\n"
            f"This is an automated test letter dispatched from {ai_name}'s Email Engine.\n\n"
            f"If you received this message, your Gmail address, 16-character App Password, "
            f"and SMTP delivery route are configured and operating correctly!\n\n"
            f"— {ai_name} Emotion Core"
        )
        return self.send_email(subject=subject, body_text=body, to_email=target_recipient)

    def _clean_email_body(self, raw_text: str) -> str:
        """Strips out quoted email replies, signatures, and client footers."""
        lines = []
        for line in raw_text.splitlines():
            stripped = line.strip()
            if re.match(r'^-+\s*Original Message\s*-+', stripped, re.IGNORECASE):
                break
            if re.match(r'^On\s.+wrote:\s*$', stripped, re.IGNORECASE):
                break
            if re.match(r'^-{2,}\s*Forwarded Message\s*-{2,}', stripped, re.IGNORECASE):
                break
            if re.match(r'^(From|Sent|To|Subject):\s', stripped, re.IGNORECASE):
                if len(lines) > 0 and lines[-1] == "":
                    break
            if stripped.startswith(">"):
                continue
            if re.match(r'^Sent from my (iPhone|Android|Galaxy|iPad|Pixel)', stripped, re.IGNORECASE):
                continue
            if re.match(r'^(Get Outlook for|Sent from Outlook)', stripped, re.IGNORECASE):
                continue
            lines.append(line)

        return "\n".join(lines).strip()

    def fetch_unread_replies(self) -> List[Dict[str, Any]]:
        """Polls inbox for unread emails from the companion."""
        if not self.is_configured:
            return []

        messages_found = []
        mail = None

        try:
            ssl_ctx = ssl.create_default_context()
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, ssl_context=ssl_ctx, timeout=20)
            mail.login(self.sender_email, self.app_password)
            mail.select("INBOX")

            search_query = f'(UNSEEN FROM "{self.recipient_email}")'
            status, data = mail.search(None, search_query)

            if status != "OK" or not data or not data[0]:
                mail.close()
                mail.logout()
                return []

            message_ids = data[0].split()

            for msg_id in message_ids:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])

                        subject = msg.get("Subject", "No Subject")
                        sender = msg.get("From", "")
                        message_id_header = msg.get("Message-ID", "")

                        decoded_parts = email.header.decode_header(subject)
                        subj_pieces = []
                        for part, enc in decoded_parts:
                            if isinstance(part, bytes):
                                subj_pieces.append(part.decode(enc or "utf-8", errors="replace"))
                            else:
                                subj_pieces.append(str(part))
                        subject = "".join(subj_pieces)

                        body = ""
                        html_fallback = ""
                        attachments = []

                        if msg.is_multipart():
                            for part in msg.walk():
                                ctype = part.get_content_type()
                                cdisp = str(part.get("Content-Disposition", ""))
                                filename = part.get_filename()

                                if filename:
                                    fn_parts = email.header.decode_header(filename)
                                    fn_pieces = [
                                        p[0].decode(p[1] or "utf-8", errors="replace") if isinstance(p[0], bytes) else str(p[0])
                                        for p in fn_parts
                                    ]
                                    filename = "".join(fn_pieces)

                                is_image = ctype.startswith("image/")
                                MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024
                                if is_image or (filename and any(filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.heic', '.bmp'])):
                                    if not filename:
                                        ext = ctype.split("/")[-1].replace("jpeg", "jpg")
                                        filename = f"photo_{int(time.time())}.{ext}"

                                    safe_basename = Path(filename).name
                                    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', safe_basename)
                                    save_path = (self.attachment_dir / f"{int(time.time())}_{clean_name}").resolve()

                                    if not str(save_path).startswith(str(self.attachment_dir.resolve())):
                                        logger.warning(f"[Email] Traversal attempt detected in filename: {filename}")
                                        continue

                                    payload_bytes = part.get_payload(decode=True)
                                    if payload_bytes:
                                        if len(payload_bytes) > MAX_ATTACHMENT_SIZE_BYTES:
                                            logger.warning(f"[Email] Attachment {clean_name} exceeded limit. Skipping.")
                                            continue

                                        with open(save_path, "wb") as f:
                                            f.write(payload_bytes)
                                        attachments.append({
                                            "filename": clean_name,
                                            "path": str(save_path),
                                            "content_type": ctype
                                        })

                                elif ctype == "text/plain" and "attachment" not in cdisp.lower():
                                    payload_bytes = part.get_payload(decode=True)
                                    if payload_bytes:
                                        body = payload_bytes.decode("utf-8", errors="replace")
                                elif ctype == "text/html" and "attachment" not in cdisp.lower() and not body:
                                    payload_bytes = part.get_payload(decode=True)
                                    if payload_bytes:
                                        html_fallback = payload_bytes.decode("utf-8", errors="replace")
                        else:
                            payload_bytes = msg.get_payload(decode=True)
                            if payload_bytes:
                                body = payload_bytes.decode("utf-8", errors="replace")

                        if not body and html_fallback:
                            clean_html = re.sub(r'<style.*?</style>', '', html_fallback, flags=re.DOTALL | re.IGNORECASE)
                            clean_html = re.sub(r'<script.*?</script>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
                            clean_html = re.sub(r'<[^>]+>', ' ', clean_html)
                            body = html.unescape(clean_html)

                        cleaned_body = self._clean_email_body(body)

                        messages_found.append({
                            "id": msg_id.decode("utf-8", errors="replace"),
                            "subject": subject,
                            "sender": sender,
                            "body": cleaned_body,
                            "message_id": message_id_header,
                            "attachments": attachments
                        })

                mail.store(msg_id, "+FLAGS", "\\Seen")

            mail.close()
            mail.logout()

            if messages_found:
                logger.info(f"[Email] Fetched {len(messages_found)} message(s) from {self.recipient_email}")

            return messages_found

        except Exception as e:
            logger.error(f"[Email] IMAP fetch error: {e}")
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass
            return []

    def send_email(
        self,
        subject: str,
        body_text: str,
        to_email: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachment_path: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Dispatches an email via SMTP with optional image/file attachment."""
        if not self.is_configured:
            return False, "Gmail credentials not configured."

        target_recipient = to_email or self.recipient_email
        ai_name = settings_manager.get("ai_name", "Calypso")

        try:
            msg = MIMEMultipart()
            msg["From"] = email.utils.formataddr((ai_name, self.sender_email))
            msg["To"] = target_recipient
            msg["Subject"] = subject
            msg["Date"] = email.utils.formatdate(localtime=True)

            domain_part = self.sender_email.split("@")[-1] if "@" in self.sender_email else "gmail.com"
            msg["Message-ID"] = email.utils.make_msgid(domain=domain_part)

            if in_reply_to:
                clean_ref = in_reply_to.strip()
                msg["In-Reply-To"] = clean_ref
                msg["References"] = clean_ref

            msg.attach(MIMEText(body_text, "plain", "utf-8"))

            if attachment_path and os.path.exists(attachment_path):
                att_file = Path(attachment_path)
                try:
                    with open(att_file, "rb") as f:
                        file_data = f.read()

                    ext = att_file.suffix.lower()
                    if ext in ['.jpg', '.jpeg']:
                        part = MIMEImage(file_data, _subtype="jpeg")
                    elif ext == '.png':
                        part = MIMEImage(file_data, _subtype="png")
                    elif ext == '.webp':
                        part = MIMEImage(file_data, _subtype="webp")
                    else:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(file_data)
                        encoders.encode_base64(part)

                    part.add_header('Content-Disposition', 'attachment', filename=att_file.name)
                    msg.attach(part)
                    logger.info(f"[Email] Attached file to email: {att_file.name}")
                except Exception as att_err:
                    logger.error(f"[Email] Failed to attach file '{attachment_path}': {att_err}")

            with self._get_smtp_connection(timeout=20) as server:
                server.send_message(msg)

            logger.info(f"[Email] Successfully sent email to {target_recipient}: '{subject}'")
            return True, f"Dispatched '{subject}' to {target_recipient}"

        except smtplib.SMTPAuthenticationError:
            err_msg = "Authentication failed: Ensure 2-Step Verification is on and use a 16-character Google App Password."
            logger.error(f"[Email] {err_msg}")
            return False, err_msg
        except Exception as e:
            logger.error(f"[Email] SMTP send failed: {e}")
            return False, f"Unable to connect or send: {e}"
