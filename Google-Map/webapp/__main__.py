"""Start the web app: ``python -m webapp`` (from the Google-Map folder)."""
import argparse
import threading
import time
import webbrowser
from urllib.request import urlopen

import uvicorn


def _open_when_ready(url, timeout=30):
    """Open the browser only once the server answers, so the first page load never fails."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urlopen(url + "/api/v1/stats", timeout=1):
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(0.4)


def main():
    parser = argparse.ArgumentParser(description="MapLeads web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(f"http://{args.host}:{args.port}",), daemon=True).start()
    uvicorn.run("webapp.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
