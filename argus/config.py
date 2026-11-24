import json
import os
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet

HOME = Path(os.getenv("ARGUS_STATE_DIR", ".argus"))
HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
DATABASE = os.getenv("DATABASE_URL", f"sqlite:///{HOME / 'studio.sqlite3'}")
PROVIDERS = json.loads(
    os.getenv(
        "ARGUS_PROVIDERS",
        '{"OpenAI":"https://api.openai.com/v1","NVIDIA":"https://integrate.api.nvidia.com/v1"}',
    )
)
for url in PROVIDERS.values():
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Provider catalog requires HTTPS base URLs without credentials or queries"
        )


def vault():
    key = os.getenv("ARGUS_ENCRYPTION_KEY")
    if key:
        return Fernet(key)
    # Atomic publication prevents workers from ever observing a partial key.
    import tempfile

    with tempfile.NamedTemporaryFile(dir=HOME, delete=False) as tmp:
        tmp.write(Fernet.generate_key())
    try:
        os.link(tmp.name, HOME / "vault.key")
    except FileExistsError:
        pass
    finally:
        os.unlink(tmp.name)
    return Fernet((HOME / "vault.key").read_bytes())


cipher = vault()


def seal(value):
    return cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def unseal(value):
    return json.loads(cipher.decrypt(value.encode()))
