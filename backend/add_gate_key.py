r"""Generate a gate security key and print the INSERT for the security_keys table.

Usage (from repo root):
  backend\.venv\\Scripts\\python.exe backend\\add_gate_key.py [label] [--key EXISTING]

Then run the printed INSERT against Postgres and restart the backend
(keys are loaded into memory at startup only). Store the plaintext safely:
the DB keeps only the SHA-256 hash.
"""
import argparse
import secrets
from hashlib import sha256

parser = argparse.ArgumentParser(description="Generate a gate security key + INSERT SQL")
parser.add_argument("label", nargs="?", default=None, help="optional label, e.g. 'front desk'")
parser.add_argument("--key", default=None, help="use an existing plaintext key instead of generating one")
args = parser.parse_args()

key = args.key or secrets.token_urlsafe(12)
key_hash = sha256(key.encode("utf-8")).hexdigest()
label = (args.label or "").replace("'", "''")

print(f"Key (shown once): {key}")
print(f"SHA-256:          {key_hash}")
print()
print(
    "INSERT INTO security_keys (label, key_hash) "
    f"VALUES ('{label}', '{key_hash}');"
)
