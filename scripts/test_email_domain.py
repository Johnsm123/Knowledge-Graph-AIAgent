"""
Quick diagnostic: test Azure email domain connectivity.
Run with: venv\Scripts\python.exe scripts\test_email_domain.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

conn_str = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING", "")
sender   = os.getenv("AZURE_COMMUNICATION_SENDER", "")

print("=== Azure Communication Email Diagnostic ===\n")
endpoint = ""
for part in conn_str.split(";"):
    if part.lower().startswith("endpoint="):
        endpoint = part.split("=", 1)[1]
        break

print(f"ACS Endpoint   : {endpoint}")
print(f"Sender Address : {sender}")
print(f"Sender Domain  : {sender.split('@')[-1] if '@' in sender else 'MISSING @'}")
print()

try:
    from azure.communication.email import EmailClient
    client = EmailClient.from_connection_string(conn_str)

    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": "test@mailinator.com"}]},
        "content": {
            "subject": "Azure Domain Diagnostic Test",
            "plainText": "Domain check test",
        },
    }
    print("Sending test email to test@mailinator.com ...")
    poller = client.begin_send(message)
    result = poller.result()
    print(f"\n✅ SUCCESS! Email accepted by Azure.")
    print(f"   Status    : {getattr(result, 'status', result.get('status', '?') if isinstance(result, dict) else '?')}")
    print(f"   Message ID: {getattr(result, 'id', result.get('id', '?') if isinstance(result, dict) else '?')}")

except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}")
    print(f"   Message : {e}")
    if hasattr(e, 'error') and e.error:
        code = getattr(e.error, 'code', None)
        msg  = getattr(e.error, 'message', None)
        print(f"   Code    : {code}")
        print(f"   Detail  : {msg}")
        if code == "DomainNotLinked":
            print()
            print("DIAGNOSIS: The sender domain is NOT linked to this ACS resource.")
            print(f"  - Your ACS resource  : {endpoint}")
            print(f"  - Sender domain used : {sender.split('@')[-1] if '@' in sender else sender}")
            print()
            print("FIX OPTIONS:")
            print("  1. Go to Azure Portal → Your ACS resource → Email → Domains")
            print("     and copy the correct linked domain, then update AZURE_COMMUNICATION_SENDER in .env")
            print("  2. OR link the domain shown above to this ACS resource.")
