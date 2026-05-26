import smtplib
import ssl
import time
import random
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# ==========================================
# CONFIGURATION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env_file(env_file=".env"):
    """Loads KEY=VALUE pairs from a local .env file into os.environ if not already set."""
    env_path = os.path.join(BASE_DIR, env_file)
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()


def normalize_sender_email(value):
    if not value:
        return value
    return value.strip()


def normalize_app_password(value):
    if not value:
        return value
    return value.strip().replace(" ", "").replace("-", "")


SENDER_EMAIL = normalize_sender_email(os.getenv("SENDER_EMAIL"))
SENDER_NAME = "Khaleel Ahmad"
APP_PASSWORD = normalize_app_password(os.getenv("APP_PASSWORD"))

SUBJECT = "Data Engineer / AI Engineer – Open to New Roles in Germany"

ATTACHMENTS = [
    "Khaleel_Resume.pdf"
    #"Certificate of Enrolment [PDF].pdf",
    #"Khaleel_Certifications.pdf"
]

SENT_LOG_FILE = "sent_log.txt"


def validate_config():
    missing = []
    if not SENDER_EMAIL:
        missing.append("SENDER_EMAIL")
    if not APP_PASSWORD:
        missing.append("APP_PASSWORD")

    if missing:
        print("❌ Missing required environment variables:", ", ".join(missing))
        print("Set them in your shell or add them to a local .env file (never commit .env).")
        return False

    return True


# ==========================================
# EMAIL CONTENT (Plain Text & HTML)
# ==========================================

TEXT_BODY = """\
Guten Tag,

I came across your company and wanted to reach out directly. I am based in Berlin and have spent the last few years working in Data Engineering and AI at Ericsson, building production data pipelines with Python, SQL and Airflow, and deploying LLM-powered automation systems using LangChain and the OpenAI API.

I work with Spark, Docker, and cloud infrastructure across AWS, GCP and Azure, and I am CKA certified. On the AI side I have built end-to-end systems where LLMs handle real business logic in production.

I am now finishing my M.Sc. in AI at BTU and actively looking for my next role in Germany. If you have anything relevant open or coming up, I would love to hear about it.

Website: https://khaleel.eu
GitHub: https://github.com/khaleel-git
LinkedIn: https://linkedin.com/in/khaleel-ahmad

Best regards,
Khaleel Ahmad
+49 15563611714
khaleel.eu@gmail.com
"""

HTML_BODY = """\
<html>
  <body>
    <p>Guten Tag,</p>

    <p>I came across your company and wanted to reach out directly. I am based in Berlin and have spent the last few years working in Data Engineering and AI at Ericsson, building production data pipelines with Python, SQL and Airflow, and deploying LLM-powered automation systems using LangChain and the OpenAI API.</p>

    <p>I work with Spark, Docker, and cloud infrastructure across AWS, GCP and Azure, and I am CKA certified. On the AI side I have built end-to-end systems where LLMs handle real business logic in production.</p>

    <p>I am now finishing my M.Sc. in AI at BTU and actively looking for my next role in Germany. If you have anything relevant open or coming up, I would love to hear about it.</p>

    <p>
      Website: <a href="https://khaleel.eu">khaleel.eu</a><br>
      GitHub: <a href="https://github.com/khaleel-git">github.com/khaleel-git</a><br>
      LinkedIn: <a href="https://linkedin.com/in/khaleel-ahmad">linkedin.com/in/khaleel-ahmad</a>
    </p>

    <p>
      <strong>Khaleel Ahmad</strong><br>
      +49 15563611714<br>
      <a href="mailto:khaleel.eu@gmail.com">khaleel.eu@gmail.com</a>
    </p>
  </body>
</html>
"""


def create_email(recipient_email):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = SUBJECT
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = recipient_email

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(TEXT_BODY, "plain"))
    body_part.attach(MIMEText(HTML_BODY, "html"))
    msg.attach(body_part)

    for filename in ATTACHMENTS:
        if not os.path.exists(filename):
            print(f"⚠️ Warning: File '{filename}' not found. Skipping attachment.")
            continue

        with open(filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())

        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {filename}")
        msg.attach(part)

    return msg


def get_recipients(txt_file="contacts.txt"):
    recipients = []
    try:
        with open(txt_file, mode="r", encoding="utf-8-sig") as file:
            for line in file:
                email = line.strip()
                if email:
                    recipients.append(email)
    except FileNotFoundError:
        print(f"❌ Error: Could not find {txt_file}. Please create it with one email per line.")
    return recipients


def get_already_sent_emails(log_file):
    if not os.path.exists(log_file):
        return set()
    with open(log_file, "r", encoding="utf-8") as f:
        return set(line.strip().lower() for line in f if line.strip())


def log_sent_email(log_file, email):
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{email.strip().lower()}\n")


def connect_smtp(context):
    server = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30)
    server.login(SENDER_EMAIL, APP_PASSWORD)
    return server


def ensure_smtp_connected(server, context):
    if server is None:
        return connect_smtp(context)

    try:
        code, _ = server.noop()
        if code != 250:
            raise smtplib.SMTPServerDisconnected(f"NOOP returned unexpected status: {code}")
        return server
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError):
        try:
            server.quit()
        except Exception:
            pass
        return connect_smtp(context)


def main():
    if not validate_config():
        return

    all_recipients = get_recipients()
    if not all_recipients:
        print("No recipients found in your TXT file. Exiting.")
        return

    already_sent = get_already_sent_emails(SENT_LOG_FILE)
    already_sent_in_list = {r.lower() for r in all_recipients if r.lower() in already_sent}
    pending_recipients = [r for r in all_recipients if r.lower() not in already_sent_in_list]

    if not pending_recipients:
        print(f"✅ All {len(all_recipients)} recipients in your list have already been emailed. Exiting.")
        return

    print(f"Found {len(all_recipients)} total recipients in TXT file.")
    print(f"Skipping {len(already_sent_in_list)} already emailed.")
    print(f"Preparing to send to {len(pending_recipients)} NEW recipients...\n")

    context = ssl.create_default_context()
    server = None

    try:
        server = connect_smtp(context)
        print("✅ Successfully logged into Gmail SMTP server.")

        for index, recipient in enumerate(pending_recipients):
            print(f"[{index + 1}/{len(pending_recipients)}] Sending to {recipient}...")

            try:
                server = ensure_smtp_connected(server, context)
                msg = create_email(recipient)
                server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
                log_sent_email(SENT_LOG_FILE, recipient)
                print("   -> 🚀 Sent and logged successfully")

            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, smtplib.SMTPException, OSError) as e:
                print(f"   -> ⚠ SMTP connection issue for {recipient}: {e}")
                print("   -> Reconnecting and retrying once...")

                try:
                    server = connect_smtp(context)
                    msg = create_email(recipient)
                    server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
                    log_sent_email(SENT_LOG_FILE, recipient)
                    print("   -> 🚀 Sent successfully after reconnect")
                except Exception as retry_error:
                    print(f"   -> ❌ Failed after reconnect for {recipient}: {retry_error}")
                    continue

            except Exception as e:
                print(f"   -> ❌ Failed to send to {recipient}: {e}")
                continue

            if index < len(pending_recipients) - 1:
                delay = random.uniform(30, 120)
                print(f"   -> ⏳ Pausing for {int(delay)} seconds to mimic human sending...\n")
                time.sleep(delay)

    except smtplib.SMTPAuthenticationError as auth_error:
        details = ""
        if hasattr(auth_error, "smtp_error") and auth_error.smtp_error:
            try:
                details = auth_error.smtp_error.decode("utf-8", errors="ignore")
            except Exception:
                details = str(auth_error.smtp_error)

        print("❌ Authentication Error: Gmail rejected the login.")
        print("   Check that SENDER_EMAIL is the Gmail account that generated the App Password.")
        print("   Check that 2-Step Verification is enabled for that same account.")
        print("   Check that APP_PASSWORD is the 16-character app password (no spaces).")
        if details:
            print(f"   Gmail says: {details}")
    except Exception as e:
        print(f"❌ A critical error occurred: {e}")
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

    print("\n🎉 Process completed!")


if __name__ == "__main__":
    main()