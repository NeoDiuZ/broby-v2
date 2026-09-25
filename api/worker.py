"""Separate single-host worker: python worker.py [--check]."""
import argparse
import logging
import signal
import threading
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
    pass


def main():
    import runtime
    from worker_runtime import ExternalWorkers, WorkerRuntime
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check the registered external worker heartbeat and progress')
    args = parser.parse_args()
    runtime.validate()
    if runtime.worker_mode() != 'external':
        raise RuntimeError('Standalone workers require BROBY_WORKER_MODE=external on API and worker')
    if args.check:
        return int(any(value['attention'] for value in ExternalWorkers(register=False).snapshot()))
    stop = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stop.set())
    monitor = WorkerRuntime(stop, 'external').start()
    try:
        stop.wait()
    finally:
        monitor.close(timeout=30)
    return int(monitor.failure)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Database errors may contain credentials or paths. Detailed exceptions
        # stay out of process-manager logs, just as they do in worker health.
        logging.error('Worker could not start or verify health; check mode, storage and database ownership')
        raise SystemExit(1)
