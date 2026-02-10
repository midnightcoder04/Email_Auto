"""
Bulk Email Sender with Gmail SMTP + App Passwords
Rotates between multiple Gmail accounts to stay under limits and avoid spam.
No Google Cloud Console needed — just Gmail App Passwords.

Setup:
  1. Enable 2-Step Verification on each Gmail account
  2. Go to https://myaccount.google.com/apppasswords
  3. Generate an app password for each account
  4. Add them to credentials/accounts.json
"""

import csv
import json
import time
import random
import pickle
import smtplib
import ssl
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime


ACCOUNTS_FILE = "credentials/accounts.json"


class GmailAccountManager:
    """Manages multiple Gmail accounts and their sending quotas."""

    def __init__(self, accounts_file=ACCOUNTS_FILE, daily_limit=450):
        """
        Args:
            accounts_file: JSON file with email/app-password pairs
            daily_limit: Conservative daily limit per account (Gmail allows 500)
        """
        self.accounts_file = Path(accounts_file)
        self.daily_limit = daily_limit
        self.accounts = {}          # name -> {email, password}
        self.connections = {}       # name -> smtplib.SMTP_SSL
        self.send_counts = {}
        self.progress_file = self.accounts_file.parent / "send_progress_smtp.pickle"
        self.load_progress()

    # ---- progress tracking ----

    def load_progress(self):
        """Load sending progress from file."""
        if self.progress_file.exists():
            with open(self.progress_file, 'rb') as f:
                data = pickle.load(f)
                if data.get('date') == datetime.now().date():
                    self.send_counts = data.get('counts', {})
                else:
                    self.send_counts = {}

    def save_progress(self):
        """Save sending progress to file."""
        with open(self.progress_file, 'wb') as f:
            pickle.dump({
                'date': datetime.now().date(),
                'counts': self.send_counts
            }, f)

    # ---- account setup ----

    def load_accounts(self):
        """Load accounts from JSON and verify SMTP login for each."""
        if not self.accounts_file.exists():
            self.accounts_file.parent.mkdir(parents=True, exist_ok=True)
            sample = [
                {"email": "you@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"},
                {"email": "another@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"},
            ]
            with open(self.accounts_file, 'w') as f:
                json.dump(sample, f, indent=2)
            print(f"Created sample accounts file: {self.accounts_file}")
            print("Edit it with your real Gmail addresses and app passwords, then re-run.")
            return False

        with open(self.accounts_file) as f:
            account_list = json.load(f)

        if not account_list:
            print("No accounts found in accounts.json")
            return False

        context = ssl.create_default_context()

        for entry in account_list:
            email = entry["email"]
            password = entry["app_password"]
            name = email.split("@")[0]

            try:
                server = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context)
                server.login(email, password)
                self.accounts[name] = {"email": email, "password": password}
                self.connections[name] = server
                if name not in self.send_counts:
                    self.send_counts[name] = 0
                print(f"✓ {email} logged in ({self.send_counts[name]}/{self.daily_limit} sent today)")
            except Exception as e:
                print(f"✗ {email} login failed: {e}")

        return len(self.accounts) > 0

    def _reconnect(self, account_name):
        """Re-establish SMTP connection for an account."""
        info = self.accounts[account_name]
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context)
        server.login(info["email"], info["password"])
        self.connections[account_name] = server

    def get_available_account(self):
        """Get an account that hasn't reached its daily limit."""
        available = [
            name for name, count in self.send_counts.items()
            if count < self.daily_limit
        ]
        if not available:
            return None, None, None

        account_name = min(available, key=lambda x: self.send_counts[x])
        return account_name, self.accounts[account_name]["email"], self.connections[account_name]

    def record_send(self, account_name):
        """Record that an email was sent from an account."""
        self.send_counts[account_name] = self.send_counts.get(account_name, 0) + 1
        self.save_progress()

    def get_total_capacity(self):
        """Get total remaining capacity across all accounts."""
        return sum(self.daily_limit - c for c in self.send_counts.values())

    def close_all(self):
        """Close all SMTP connections."""
        for server in self.connections.values():
            try:
                server.quit()
            except Exception:
                pass


def create_email_with_attachment(sender, to, subject, body, attachment_path):
    """Create an email message with attachment."""
    message = MIMEMultipart()
    message['To'] = to
    message['From'] = sender
    message['Subject'] = subject

    message.attach(MIMEText(body, 'plain'))

    attachment_path = Path(attachment_path)
    if attachment_path.exists():
        with open(attachment_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename="{attachment_path.name}"'
        )
        message.attach(part)
    else:
        raise FileNotFoundError(f"Attachment not found: {attachment_path}")

    return message


def send_email(server, sender, to, subject, body, attachment_path):
    """Send an email via SMTP."""
    try:
        message = create_email_with_attachment(sender, to, subject, body, attachment_path)
        server.sendmail(sender, to, message.as_string())
        return True, "ok"
    except Exception as e:
        return False, str(e)


def bulk_send_emails(
    account_manager,
    email_list_csv,
    subject,
    body_template,
    min_delay=15,
    max_delay=45,
    emails_per_session=150,
    log_file="send_log.csv"
):
    """
    Send bulk emails with anti-spam measures.

    Args:
        account_manager: GmailAccountManager instance
        email_list_csv: CSV file with columns: email, name, pdf_path
        subject: Email subject (can use {name} placeholder)
        body_template: Email body (can use {name} placeholder)
        min_delay: Minimum seconds between emails
        max_delay: Maximum seconds between emails
        emails_per_session: Max emails before taking a longer break
        log_file: File to log sent/failed emails
    """
    # Load email list
    with open(email_list_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        pending_emails = list(reader)

    # Load already sent emails
    sent_emails = set()
    log_path = Path(log_file)
    if log_path.exists():
        with open(log_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('status') == 'sent':
                    sent_emails.add(row['email'])

    # Filter out already sent
    pending_emails = [e for e in pending_emails if e['email'] not in sent_emails]

    print(f"\n{'='*60}")
    print(f"Bulk Email Sender (SMTP)")
    print(f"{'='*60}")
    print(f"Total pending: {len(pending_emails)}")
    print(f"Already sent: {len(sent_emails)}")
    print(f"Daily capacity remaining: {account_manager.get_total_capacity()}")
    print(f"{'='*60}\n")

    # Open log file for appending
    log_exists = log_path.exists()
    log_file_handle = open(log_path, 'a', newline='', encoding='utf-8')
    log_writer = csv.writer(log_file_handle)
    if not log_exists:
        log_writer.writerow(['timestamp', 'email', 'name', 'account_used', 'status', 'detail'])

    session_count = 0
    total_sent = 0
    total_failed = 0

    for email_data in pending_emails:
        account_name, sender_email, server = account_manager.get_available_account()

        if not server:
            print("\n⚠ All accounts have reached daily limit. Try again tomorrow.")
            break

        recipient_email = email_data['email']
        recipient_name = email_data.get('name', '')
        attachment_path = email_data['pdf_path']

        personalized_subject = subject.replace('{name}', recipient_name)
        personalized_body = body_template.replace('{name}', recipient_name)

        print(f"[{total_sent + total_failed + 1}/{len(pending_emails)}] "
              f"Sending to {recipient_email} via {sender_email}...", end=" ")

        success, result = send_email(
            server, sender_email, recipient_email,
            personalized_subject, personalized_body, attachment_path
        )

        # Reconnect once and retry on SMTP failure
        if not success and ("SMTPServerDisconnected" in result or "Connection" in result):
            try:
                account_manager._reconnect(account_name)
                server = account_manager.connections[account_name]
                success, result = send_email(
                    server, sender_email, recipient_email,
                    personalized_subject, personalized_body, attachment_path
                )
            except Exception as e:
                result = str(e)

        timestamp = datetime.now().isoformat()

        if success:
            print("✓")
            account_manager.record_send(account_name)
            log_writer.writerow([timestamp, recipient_email, recipient_name, sender_email, 'sent', result])
            total_sent += 1
        else:
            print(f"✗ {result}")
            log_writer.writerow([timestamp, recipient_email, recipient_name, sender_email, 'failed', result])
            total_failed += 1

        log_file_handle.flush()
        session_count += 1

        # Anti-spam delays
        if session_count >= emails_per_session:
            break_time = random.randint(300, 600)  # 5-10 minutes
            print(f"\n⏸ Taking a {break_time//60} minute break after {session_count} emails...")
            time.sleep(break_time)
            session_count = 0
        else:
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

    log_file_handle.close()
    account_manager.close_all()

    print(f"\n{'='*60}")
    print(f"Session Complete")
    print(f"{'='*60}")
    print(f"Sent: {total_sent}")
    print(f"Failed: {total_failed}")
    print(f"Remaining: {len(pending_emails) - total_sent - total_failed}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    # ==================== CONFIGURATION ====================

    ACCOUNTS_FILE = "credentials/accounts.json"
    EMAIL_LIST_CSV = "renamed_pdfs/email_list.csv"  # CSV from extract_rename_pdfs.py

    # Email content
    SUBJECT = "Your Document - {name}"  # {name} will be replaced
    BODY = """Dear {name},

Please find your document attached.

If you have any questions, please don't hesitate to reach out.

Best regards,
Your Name
"""

    # Anti-spam settings (conservative for safety)
    MIN_DELAY = 20        # Minimum seconds between emails
    MAX_DELAY = 60        # Maximum seconds between emails
    EMAILS_PER_SESSION = 100   # Take a break after this many
    DAILY_LIMIT = 400     # Conservative (Gmail allows 500)

    # =======================================================

    print("Setting up Gmail accounts...")
    manager = GmailAccountManager(accounts_file=ACCOUNTS_FILE, daily_limit=DAILY_LIMIT)

    if manager.load_accounts():
        print(f"\n{len(manager.accounts)} account(s) ready to use")

        bulk_send_emails(
            account_manager=manager,
            email_list_csv=EMAIL_LIST_CSV,
            subject=SUBJECT,
            body_template=BODY,
            min_delay=MIN_DELAY,
            max_delay=MAX_DELAY,
            emails_per_session=EMAILS_PER_SESSION,
        )
    else:
        print("No accounts configured. See credentials/accounts.json")
