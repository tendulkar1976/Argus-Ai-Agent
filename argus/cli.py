import argparse
from alembic import command
from alembic.config import Config
from argus.db import create_workspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["init", "bootstrap", "workspace", "prune", "tokenizer"]
    )
    parser.add_argument("name", nargs="?", default="Local workspace")
    args = parser.parse_args()
    command.upgrade(Config("alembic.ini"), "head")
    if args.action == "bootstrap":
        from sqlalchemy import select
        from argus.db import engine, workspaces

        with engine.connect() as db:
            first = db.scalar(select(workspaces.c.id).limit(1)) is None
        if first:
            print("Save your private workspace owner key. It is shown once.")
            print(create_workspace(args.name))
    elif args.action == "workspace":
        print(create_workspace(args.name))
    elif args.action == "tokenizer":
        from argus.tokens import directory
        from pathlib import Path
        import hashlib

        data = Path(args.name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        directory().mkdir(mode=0o700, parents=True, exist_ok=True)
        from tokenizers import Tokenizer

        Tokenizer.from_buffer(data)
        (directory() / (digest + ".json")).write_bytes(data)
        print(digest)
    elif args.action == "prune":
        from argus.research import prune

        print(prune())


if __name__ == "__main__":
    main()
