"""Local launcher for TriageDesk that automatically selects a free port."""

import argparse
import os
import socket
import sys

import uvicorn


def is_port_free(host: str, port: int) -> bool:
    """Return True if a TCP bind attempt on host:port succeeds cleanly."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host: str, preferred: int) -> int:
    """Return preferred port when free, otherwise select the next free port."""
    if is_port_free(host, preferred):
        return preferred
    for candidate in range(max(preferred + 1, 8001), 8100):
        if is_port_free(host, candidate):
            return candidate
    raise RuntimeError("No free port available in range 8001-8099.")


def main() -> int:
    """Launch TriageDesk uvicorn server on an available port."""
    parser = argparse.ArgumentParser(description="Run TriageDesk locally on a free port.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8000")),
        help="Preferred port (automatically picks next free port if busy)",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    selected = pick_port(args.host, args.port)
    if selected != args.port:
        print(f"Port {args.port} is already in use; starting TriageDesk on free port {selected}.")
    print(f"TriageDesk UI:  http://{args.host}:{selected}/")
    print(f"Swagger Docs:   http://{args.host}:{selected}/docs")

    uvicorn.run("backend.main:app", host=args.host, port=selected, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
