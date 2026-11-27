"""Smoke test of the platform: MinIO, buckets, Kafka, topics, Kafka UI. Standard library only.

python scripts/smoke_test.py                        (Windows: python scripts\\smoke_test.py)
DOCKER="sudo docker" python scripts/smoke_test.py   (only if Docker needs sudo on your machine)
"""

import os
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shlex.split(os.getenv("DOCKER", "docker"))


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+#.*$", "", line.strip())
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def compose(*args: str, timeout: int = 60) -> str:
    cmd = [*DOCKER, "compose", *args]
    try:
        r = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"timeout after {timeout}s") from e
    except OSError as e:
        raise RuntimeError(f"cannot run {DOCKER[0]}: {e}") from e
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:])
    return r.stdout + r.stderr


def http_ok(url: str) -> bool:
    try:
        return urllib.request.urlopen(url, timeout=5).status < 400
    except Exception:
        return False


def main() -> int:
    if not (ROOT / ".env").exists():
        print("No .env file: run  cp .env.example .env  (Windows: copy .env.example .env)")
        return 1
    env = load_env()
    failed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        failed += not ok
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))

    print("MinIO")
    check("API health", http_ok(f"http://localhost:{env['MINIO_API_PORT']}/minio/health/live"))
    check("console", http_ok(f"http://localhost:{env['MINIO_CONSOLE_PORT']}"))
    try:
        ready = "buckets ready" in compose("logs", "minio-init")
        check(f"buckets created ({env['MINIO_BUCKETS']})", ready, "see: docker compose logs minio-init")
    except RuntimeError as e:
        check("buckets created", False, str(e))

    print("Kafka")
    try:
        out = compose(
            "exec",
            "-T",
            "-e",
            "KAFKA_HEAP_OPTS=-Xmx128m",
            "kafka",
            "/opt/kafka/bin/kafka-topics.sh",
            "--bootstrap-server",
            "localhost:9092",
            "--describe",
        )
    except RuntimeError as e:
        out = ""
        check("Kafka reachable", False, str(e))
    for spec in env["KAFKA_TOPICS"].split(","):
        name, parts = spec.split(":")
        found = re.search(rf"Topic: {re.escape(name)}\s.*?PartitionCount: (\d+)", out)
        check(f"topic {name} ({parts} partitions)", bool(found) and found.group(1) == parts)
    check("Kafka UI", http_ok(f"http://localhost:{env['KAFKA_UI_PORT']}"))

    print("ALL OK" if not failed else f"{failed} CHECK(S) FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
