# Bulk Email Sender

Send 6000+ emails with attachments using 8 Gmail accounts while avoiding spam filters.

**Two methods available:**
- `bulk_email_sender_smtp.py` — Uses **App Passwords** (recommended, no Google Cloud needed)
- `bulk_email_sender.py` — Uses **Gmail API + OAuth** (requires Google Cloud Console)

---

## Quick Start (App Password Method)

### 1. Install Dependencies
```bash
pip install pdfplumber
```

### 2. Set Up App Passwords (One-time per account)

For **each** Gmail account:

1. Enable **2-Step Verification**: [myaccount.google.com/security](https://myaccount.google.com/security)
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an app password (select "Mail" / "Other")
4. Copy the 16-character password

### 3. Add Accounts

Create `credentials/accounts.json` (or run the script once and it creates a template):

```json
[
  { "email": "account1@gmail.com", "app_password": "abcd efgh ijkl mnop" },
  { "email": "account2@gmail.com", "app_password": "qrst uvwx yzab cdef" }
]
```

### 4. Prepare Your PDFs

Place all PDFs in a folder, then run:
```bash
python extract_rename_pdfs.py
```

This will:
- Extract email and name from each PDF
- Rename PDFs to `email_name.pdf` format
- Create `email_list.csv` mapping file

### 5. Configure Email Content

Edit `bulk_email_sender_smtp.py`:
```python
SUBJECT = "Your Document - {name}"
BODY = """Dear {name},

Your document is attached.

Best regards,
Your Team
"""
```

### 6. Send Emails

```bash
python bulk_email_sender_smtp.py
```

---

## Alternative: Gmail API Method

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Set Up Gmail API (One-time per account)

For **each** Gmail account:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable **Gmail API**:
   - Go to "APIs & Services" → "Enable APIs"
   - Search for "Gmail API" and enable it
4. Create OAuth credentials:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Choose "Desktop app"
   - Download the JSON file
5. Save as `credentials/account1_credentials.json` (account2, account3, etc.)

Then run:
```bash
python bulk_email_sender.py
```
First run will open browser for each account to authorize.

## Folder Structure

```
├── credentials/
│   ├── accounts.json              # App passwords (SMTP method)
│   ├── account1_credentials.json  # OAuth creds (API method)
│   └── account1_token.pickle      # Created after OAuth auth
├── pdfs/                          # Your original PDFs
├── renamed_pdfs/                  # Renamed PDFs
│   └── email_list.csv             # Generated mapping
├── extract_rename_pdfs.py
├── bulk_email_sender_smtp.py      # ← App Password method
├── bulk_email_sender.py           # ← Gmail API method
└── send_log.csv                   # Tracks sent/failed emails
```

## Anti-Spam Measures

The scripts automatically:
- ✓ Rotate between 8 accounts
- ✓ Keep under 400-450 emails/day/account
- ✓ Add random delays (20-60 sec) between emails
- ✓ Take breaks after every 100 emails
- ✓ Track progress (can resume if interrupted)
- ✓ Auto-reconnect on SMTP connection drops

## Daily Schedule (Recommended)

For 6000 emails in 5 days with 8 accounts:

| Day | Emails/Account | Total | Cumulative |
|-----|----------------|-------|------------|
| 1   | 150 each       | 1,200 | 1,200      |
| 2   | 150 each       | 1,200 | 2,400      |
| 3   | 150 each       | 1,200 | 3,600      |
| 4   | 150 each       | 1,200 | 4,800      |
| 5   | 150 each       | 1,200 | 6,000      |

## Cost: FREE

- Gmail API: Free
- Python: Free
- No third-party email services needed

## Resuming After Interruption

The script automatically tracks progress in `send_log.csv`. Simply run again to continue.

## Troubleshooting

**"Daily limit reached"**: Wait until tomorrow or add more accounts

**"Attachment not found"**: Check paths in `email_list.csv`

**"Token expired"** (API method): Delete `*_token.pickle` files and re-authorize

**"Login failed"** (SMTP method): Regenerate app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)

## Important Notes

1. **Warm up new accounts**: If accounts are new, send fewer emails first week
2. **Avoid spam words**: Don't use "FREE", "WINNER", etc. in subject
3. **Monitor**: Check sent folder to confirm delivery
4. **Attachment size**: Gmail limit is 25MB per email
