import hashlib
import secrets
import time
import uuid
from sqlalchemy import create_engine, event, select, update
from argus.config import DATABASE
from argus.schema_v1 import events, keys, workspaces

engine = create_engine(
    DATABASE,
    pool_pre_ping=True,
    **(
        {"connect_args": {"timeout": 15, "check_same_thread": False}}
        if DATABASE.startswith("sqlite:")
        else {}
    ),
)
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def sqlite_options(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")


def uid():
    return uuid.uuid4().hex


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(db, workspace, action, resource):
    db.execute(
        events.insert().values(
            id=uid(),
            workspace=workspace,
            created=time.time(),
            action=action,
            resource=resource,
        )
    )


def lock(db, workspace):
    # A row write serializes admission across processes on both supported databases.
    db.execute(
        update(workspaces)
        .where(workspaces.c.id == workspace)
        .values(name=workspaces.c.name)
    )


def issue(db, ws, role, label):
    token = "argus_" + secrets.token_urlsafe(32)
    db.execute(
        keys.insert().values(id=digest(token), workspace=ws, role=role, label=label)
    )
    audit(db, ws, "key.issued", digest(token))
    return token


def create_workspace(name):
    with engine.begin() as db:
        ws = uid()
        db.execute(
            workspaces.insert().values(
                id=ws, name=name, day_calls=20, day_micros=None, retention_days=7
            )
        )
        return issue(db, ws, "owner", "Owner")


def rows(db, statement):
    return [dict(row) for row in db.execute(statement).mappings()]


def scoped(table, ws):
    return select(table).where(table.c.workspace == ws)
