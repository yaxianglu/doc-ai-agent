#!/usr/bin/env python3
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doc_ai_agent.config import AppConfig  # noqa: E402
from doc_ai_agent.server import build_http_server  # noqa: E402


def main() -> None:
    cfg = AppConfig.from_env(os.environ)
    server = build_http_server(cfg)
    host, port = server.server_address
    print(f"doc-ai-agent listening on http://{host}:{port}")

    stop = threading.Event()

    def refresh_loop() -> None:
        while not stop.wait(cfg.refresh_interval_minutes * 60):
            inserted = server.app.refresh()
            print(f"[refresh] inserted={inserted}")

    worker = threading.Thread(target=refresh_loop, daemon=True)
    worker.start()

    inserted = server.app.refresh()
    print(f"[refresh] startup inserted={inserted}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        time.sleep(0.05)
        server.server_close()


if __name__ == "__main__":
    main()
