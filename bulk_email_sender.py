"""
Bulk Email Sender with Gmail API
Rotates between multiple Gmail accounts to stay under limits and avoid spam.
"""

import os
import csv
import time
import random
import pickle
import base64
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# Gmail API scope for sending emails
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


class GmailAccountManager:
    """Manages multiple Gmail accounts and their sending quotas."""
    
    def __init__(self, credentials_folder="credentials", daily_limit=450):
        """
        Args:
            credentials_folder: Folder containing credentials for each account
            daily_limit: Conservative daily limit per account (Gmail allows 500, we use 450 for safety)
        """
        self.credentials_folder = Path(credentials_folder)
        self.daily_limit = daily_limit
        self.accounts = {}
        self.send_counts = {}
        self.last_reset = datetime.now().date()
        self.load_progress()
    
    def load_progress(self):
        """Load sending progress from file."""
        progress_file = self.credentials_folder / "send_progress.pickle"
        if progress_file.exists():
            with open(progress_file, 'rb') as f:
                data = pickle.load(f)
                # Reset counts if it's a new day
                if data.get('date') == datetime.now().date():
                    self.send_counts = data.get('counts', {})
                else:
                    self.send_counts = {}
    
    def save_progress(self):
        """Save sending progress to file."""
        progress_file = self.credentials_folder / "send_progress.pickle"
        with open(progress_file, 'wb') as f:
            pickle.dump({
                'date': datetime.now().date(),
                'counts': self.send_counts
            }, f)
    
    def setup_account(self, account_name, credentials_file):
        """
        Set up Gmail API service for an account.
        First time will open browser for OAuth.
        """
        token_file = self.credentials_folder / f"{account_name}_token.pickle"
        creds = None
        
        # Load existing token if available
        if token_file.exists():
            with open(token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next time
            with open(token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        service = build('gmail', 'v1', credentials=creds)
        self.accounts[account_name] = service
        
        if account_name not in self.send_counts:
            self.send_counts[account_name] = 0
        
        print(f"✓ Account '{account_name}' ready ({self.send_counts[account_name]}/{self.daily_limit} sent today)")
        return service
    
    def get_available_account(self):
        """Get an account that hasn't reached its daily limit."""
        available = [
            name for name, count in self.send_counts.items()
            if count < self.daily_limit
        ]
        
        if not available:
            return None, None
        
        # Choose account with lowest send count (balance the load)
        account_name = min(available, key=lambda x: self.send_counts[x])
        return account_name, self.accounts[account_name]
    
    def record_send(self, account_name):
        """Record that an email was sent from an account."""
        self.send_counts[account_name] = self.send_counts.get(account_name, 0) + 1
        self.save_progress()
    
    def get_total_capacity(self):
        """Get total remaining capacity across all accounts."""
        return sum(
            self.daily_limit - count 
            for count in self.send_counts.values()
        )


def create_email_with_attachment(sender, to, subject, body, attachment_path):
    """Create an email message with attachment."""
    message = MIMEMultipart()
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    # Add body
    message.attach(MIMEText(body, 'plain'))
    
    # Add attachment
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
    
    # Encode message
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw}


def send_email(service, sender, to, subject, body, attachment_path):
    """Send an email using Gmail API."""
    try:
        message = create_email_with_attachment(sender, to, subject, body, attachment_path)
        sent = service.users().messages().send(userId='me', body=message).execute()
        return True, sent['id']
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
    print(f"Bulk Email Sender")
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
        log_writer.writerow(['timestamp', 'email', 'name', 'account_used', 'status', 'message_id_or_error'])
    
    session_count = 0
    total_sent = 0
    total_failed = 0
    
    for email_data in pending_emails:
        # Get available account
        account_name, service = account_manager.get_available_account()
        
        if not service:
            print("\n⚠ All accounts have reached daily limit. Try again tomorrow.")
            break
        
        recipient_email = email_data['email']
        recipient_name = email_data.get('name', '')
        attachment_path = email_data['pdf_path']
        
        # Personalize subject and body
        personalized_subject = subject.replace('{name}', recipient_name)
        personalized_body = body_template.replace('{name}', recipient_name)
        
        # Get sender email
        try:
            profile = service.users().getProfile(userId='me').execute()
            sender_email = profile['emailAddress']
        except:
            sender_email = account_name
        
        # Send email
        print(f"[{total_sent + total_failed + 1}/{len(pending_emails)}] "
              f"Sending to {recipient_email} via {account_name}...", end=" ")
        
        success, result = send_email(
            service, sender_email, recipient_email,
            personalized_subject, personalized_body, attachment_path
        )
        
        timestamp = datetime.now().isoformat()
        
        if success:
            print(f"✓")
            account_manager.record_send(account_name)
            log_writer.writerow([timestamp, recipient_email, recipient_name, account_name, 'sent', result])
            total_sent += 1
        else:
            print(f"✗ {result}")
            log_writer.writerow([timestamp, recipient_email, recipient_name, account_name, 'failed', result])
            total_failed += 1
        
        log_file_handle.flush()
        session_count += 1
        
        # Anti-spam delays
        if session_count >= emails_per_session:
            # Take a longer break
            break_time = random.randint(300, 600)  # 5-10 minutes
            print(f"\n⏸ Taking a {break_time//60} minute break after {session_count} emails...")
            time.sleep(break_time)
            session_count = 0
        else:
            # Normal delay between emails
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)
    
    log_file_handle.close()
    
    print(f"\n{'='*60}")
    print(f"Session Complete")
    print(f"{'='*60}")
    print(f"Sent: {total_sent}")
    print(f"Failed: {total_failed}")
    print(f"Remaining: {len(pending_emails) - total_sent - total_failed}")
    print(f"{'='*60}\n")


def setup_all_accounts(credentials_folder="credentials"):
    """Set up all Gmail accounts from credentials folder."""
    creds_path = Path(credentials_folder)
    
    if not creds_path.exists():
        print(f"Creating credentials folder: {creds_path}")
        creds_path.mkdir(parents=True)
        print(f"""
To set up Gmail API:
1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable Gmail API
4. Create OAuth 2.0 credentials (Desktop app type)
5. Download the credentials JSON for each account
6. Place them in '{creds_path}/' folder as:
   - account1_credentials.json
   - account2_credentials.json
   - etc.
""")
        return None
    
    # Find all credential files
    cred_files = list(creds_path.glob("*_credentials.json"))
    
    if not cred_files:
        print(f"No credential files found in {creds_path}/")
        print("Expected format: account1_credentials.json, account2_credentials.json, etc.")
        return None
    
    manager = GmailAccountManager(credentials_folder=credentials_folder)
    
    for cred_file in cred_files:
        account_name = cred_file.stem.replace('_credentials', '')
        try:
            manager.setup_account(account_name, str(cred_file))
        except Exception as e:
            print(f"✗ Failed to set up {account_name}: {e}")
    
    return manager


if __name__ == "__main__":
    # ==================== CONFIGURATION ====================
    
    CREDENTIALS_FOLDER = "credentials"  # Folder with Gmail credentials
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
    MIN_DELAY = 20  # Minimum seconds between emails
    MAX_DELAY = 60  # Maximum seconds between emails
    EMAILS_PER_SESSION = 100  # Take a break after this many
    DAILY_LIMIT_PER_ACCOUNT = 400  # Conservative (Gmail allows 500)
    
    # =======================================================
    
    # Set up accounts
    print("Setting up Gmail accounts...")
    manager = setup_all_accounts(CREDENTIALS_FOLDER)
    
    if manager and manager.accounts:
        print(f"\n{len(manager.accounts)} accounts ready to use")
        
        # Start sending
        bulk_send_emails(
            account_manager=manager,
            email_list_csv=EMAIL_LIST_CSV,
            subject=SUBJECT,
            body_template=BODY,
            min_delay=MIN_DELAY,
            max_delay=MAX_DELAY,
            emails_per_session=EMAILS_PER_SESSION
        )
    else:
        print("No accounts configured. Please set up Gmail API credentials first.")
