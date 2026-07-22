#!/usr/bin/env bash
# Generates the secrets for .env. Run once, on the Mac, then fill in the rest.
#
#   bash gen-secrets.sh > .env.generated
#
# The SUPABASE_SERVICE_KEY is a real HS256 JWT signed with JWT_SECRET — the
# supabase-py client validates the shape, and PostgREST validates the signature.
set -euo pipefail

python3 - <<'PY'
import base64, hashlib, hmac, json, secrets, string, sys, time

# Alphanumeric only: this value travels through docker-compose variable
# interpolation, where $ and friends would be eaten.
alphabet = string.ascii_letters + string.digits
jwt_secret = "".join(secrets.choice(alphabet) for _ in range(48))

def b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")

# 10 years; this token lives on the NAS and is never handed out.
now = int(time.time())
header  = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
payload = b64(json.dumps({
    "role": "service_role",
    "iss": "wodpilot-nas",
    "iat": now,
    "exp": now + 3600 * 24 * 3650,
}, separators=(",", ":")).encode())

signing_input = header + b"." + payload
signature = b64(hmac.new(jwt_secret.encode(), signing_input, hashlib.sha256).digest())
service_key = (signing_input + b"." + signature).decode()

print(f"JWT_SECRET={jwt_secret}")
print(f"SUPABASE_SERVICE_KEY={service_key}")
print(f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}")
print(f"AUTHENTICATOR_PASSWORD={secrets.token_urlsafe(24)}")
print(f"INTERNAL_API_TOKEN={secrets.token_urlsafe(32)}")
print(f"WEB_SECRET_KEY={secrets.token_urlsafe(32)}")
print(f"MCP_TOKEN={secrets.token_urlsafe(32)}")

from cryptography.fernet import Fernet  # noqa: E402
print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
PY
