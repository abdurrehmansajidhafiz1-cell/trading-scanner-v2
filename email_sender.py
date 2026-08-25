"""
Email sender — SMTP se report email bhejta hai. Gmail ke sath istemal karne
ke liye "App Password" chahiye hoga (normal password kaam nahi karega) —
deployment guide mein poora tareeqa hai.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config

logger = logging.getLogger("trading_scanner")


def send_email(subject: str, body: str) -> bool:
    if not config.SMTP_USER or not config.SMTP_PASSWORD or not config.REPORT_EMAIL_TO:
        logger.warning("SMTP credentials set nahi hain (environment variables missing) — email skip ho gaya.")
        return False

    msg = MIMEMultipart()
    msg["From"] = config.SMTP_USER
    msg["To"] = config.REPORT_EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email bhej diya: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email bhejte waqt error aaya: {e}")
        return False


def send_error_alert(error_summary: str, full_traceback: str) -> bool:
    """
    Jab scan cycle poori tarah fail ho jaye, yeh turant ek alert email bhejta
    hai — taake sirf GitHub Actions logs pe depend na karna pade masla
    dhoondne ke liye, seedha email mein exact wajah mil jaye.
    """
    subject = "Trading System — ERROR: Scan Failed"
    body = (
        f"Scan cycle poori tarah fail ho gaya.\n\n"
        f"--- ERROR SUMMARY ---\n{error_summary}\n\n"
        f"--- FULL TRACEBACK ---\n{full_traceback}\n\n"
        f"GitHub Actions ke 'Actions' tab mein poore logs dekhein detail ke liye."
    )
    return send_email(subject, body)
