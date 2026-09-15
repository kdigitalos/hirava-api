"""Run the split application locally; terminate owned children together on exit."""
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "hirava-webapp"


def main():
    for port in (3000, 8000):
        for host in ('127.0.0.1', 'localhost'):
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    raise SystemExit(f"Port {port} is already in use. Stop its existing app before starting Hirava; no process was stopped.")
            except OSError:
                pass
    node = shutil.which("node")
    if not node:
        raise SystemExit("Install Node.js 22 or newer first")
    for root in (WEB,):
        if not (root / "node_modules/next/dist/bin/next").is_file():
            raise SystemExit(f"Run npm ci in {root.name} first")
    children = []
    try:
        commands = [
            (API, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]),
            (WEB, [node, "node_modules/next/dist/bin/next", "dev", "--webpack", "--hostname", "127.0.0.1", "--port", "3000"]),
        ]
        for cwd, command in commands:
            env = os.environ.copy()
            if cwd == API:
                env["LEGACY_API_URL"] = ""
            else:
                env["APP_BASE_URL"] = "http://localhost:3000"
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            children.append(subprocess.Popen(command, cwd=cwd, env=env, **kwargs))
        print("Hirava: http://localhost:3000 | FastAPI: http://127.0.0.1:8000/docs", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is not None:
                continue
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill()


if __name__ == "__main__":
    main()
