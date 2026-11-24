"""Start Argus-AI on localhost. The release archive includes the compiled Studio."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rebuild-studio", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    os.chdir(root)
    if sys.version_info < (3, 12):
        raise SystemExit("Install Python 3.12 or later before starting Argus-AI.")
    python = (
        root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            "requirements.txt",
        ],
        check=True,
    )
    if args.rebuild_studio or not (root / "studio/out/index.html").is_file():
        npm = shutil.which("npm")
        if not npm:
            raise SystemExit("Install Node.js 24 and npm to build Studio from source.")
        env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
        for command in ([npm, "ci"], [npm, "run", "build"]):
            subprocess.run(command, cwd=root / "studio", env=env, check=True)
    subprocess.run([str(python), "-m", "argus.cli", "bootstrap"], check=True)
    print(f"Open http://127.0.0.1:{args.port} in your browser.", flush=True)
    subprocess.run(
        [
            str(python),
            "-m",
            "uvicorn",
            "argus.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--no-access-log",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
