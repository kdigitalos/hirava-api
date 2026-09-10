"""Create local .env once without printing or overwriting secrets."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print(".env already exists; preserved existing configuration")
else:
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace("JWT_SECRET=\n", f"JWT_SECRET={secrets.token_urlsafe(48)}\n")
    content = content.replace("POSTGRES_PASSWORD=\n", f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n")
    with target.open("x", encoding="utf-8") as output:
        output.write(content)
    print("Created .env with random local secrets")
