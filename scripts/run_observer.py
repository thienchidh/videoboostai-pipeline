#!/usr/bin/python3
"""
scripts/run_observer.py — Launch the Pipeline Observer HTTP server.

Usage:
    python scripts/run_observer.py                    # default 0.0.0.0:8765
    python scripts/run_observer.py --port 8765
    python scripts/run_observer.py --host 127.0.0.1 --port 8765

Environment variables:
    OBSERVER_HOST  Override host
    OBSERVER_PORT  Override port
"""
import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.ops.pipeline_observer import PipelineObserver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pipeline-observer] %(levelname)s %(message)s",
)
logger = logging.getLogger("pipeline-observer")


def main():
    parser = argparse.ArgumentParser(description="Video Pipeline Observer HTTP Server")
    parser.add_argument("--host", default=os.getenv("OBSERVER_HOST", "0.0.0.0"),
                        help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("OBSERVER_PORT", "8765")),
                        help="Bind port (default: 8765)")
    args = parser.parse_args()

    logger.info(f"Starting Pipeline Observer on {args.host}:{args.port}")
    observer = PipelineObserver(host=args.host, port=args.port, daemon=False)
    observer.start()

    # Keep main thread alive (Ctrl-C to stop)
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        observer.stop()


if __name__ == "__main__":
    main()
