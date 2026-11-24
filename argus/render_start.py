"""Launch the Render deployment using credentials managed by Render."""
import base64
import hashlib
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url


def main():
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+psycopg")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    secret = os.environ["ARGUS_ENCRYPTION_SECRET"].encode()
    os.environ["ARGUS_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(
        hashlib.sha256(secret).digest()
    ).decode()

    from argus.db import audit, digest, engine, keys, uid, workspaces

    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(81730194)"))
        command.upgrade(Config("alembic.ini"), "head")
        if db.scalar(select(workspaces.c.id).limit(1)) is None:
            workspace = uid()
            key_id = digest(os.environ["ARGUS_OWNER_KEY"])
            db.execute(workspaces.insert().values(
                id=workspace, name="Argus Studio", day_calls=20, retention_days=7
            ))
            db.execute(keys.insert().values(
                id=key_id, workspace=workspace, role="owner", label="Owner"
            ))
            audit(db, workspace, "key.issued", key_id)
    os.execlp("uvicorn", "uvicorn", "argus.api:app", "--host", "0.0.0.0",
              "--port", os.getenv("PORT", "8000"), "--no-access-log")


if __name__ == "__main__":
    main()
