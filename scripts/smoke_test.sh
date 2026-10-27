#!/usr/bin/env bash
# Quick check that the Phase 0 base is alive.
set -u
set -a; [ -f .env ] && . ./.env; set +a
ok=0
check () { # name, command
  if eval "$2" >/dev/null 2>&1; then echo "  OK   $1"; else echo "  FAIL $1"; ok=1; fi
}
echo "Smoke test:"
check "MinIO API health"      "curl -sf http://localhost:${MINIO_API_PORT:-9000}/minio/health/live"
check "MinIO console"         "curl -sf -o /dev/null http://localhost:${MINIO_CONSOLE_PORT:-9001}"
check "Kafka UI"              "curl -sf -o /dev/null http://localhost:${KAFKA_UI_PORT:-8081}"
check "Topic foot-tracking"   "docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic ${KAFKA_TOPIC_TRACKING:-foot-tracking}"
check "Topic foot-events"     "docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic ${KAFKA_TOPIC_EVENTS:-foot-events}"
check "Bucket bronze exists"  "docker compose run --rm --no-deps -T --entrypoint /bin/sh minio-init -c 'mc alias set l http://minio:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && mc ls l/bronze'"
exit $ok
