#!/bin/sh
# Fills the Alertmanager config and email template from the environment (.env through docker-compose.yml), then
# starts Alertmanager. Fails at once, naming the variable, when one is missing.
set -eu
: "${SMTP_HOST:?set SMTP_HOST in .env}" "${SMTP_PORT:?set SMTP_PORT in .env}" "${SMTP_USER:?set SMTP_USER in .env}"
: "${SMTP_PASSWORD:?set SMTP_PASSWORD in .env}" "${ALERT_EMAIL_TO:?set ALERT_EMAIL_TO in .env}"
: "${GRAFANA_URL:?}" "${DAGSTER_URL:?}" "${APP_URL:?}" "${ALERTMANAGER_URL:?}"

out=/tmp/alertmanager
mkdir -p "$out"
umask 077
printf '%s' "$SMTP_PASSWORD" > "$out/smtp_password"
fill() {
  sed -e "s|__SMTP_HOST__|$SMTP_HOST|g" -e "s|__SMTP_PORT__|$SMTP_PORT|g" -e "s|__SMTP_USER__|$SMTP_USER|g" \
      -e "s|__ALERT_EMAIL_TO__|$ALERT_EMAIL_TO|g" -e "s|__GRAFANA_URL__|$GRAFANA_URL|g" \
      -e "s|__DAGSTER_URL__|$DAGSTER_URL|g" -e "s|__APP_URL__|$APP_URL|g" -e "s|__ALERTMANAGER_URL__|$ALERTMANAGER_URL|g" "$1"
}
fill /etc/alertmanager/src/alertmanager.yml.tmpl > "$out/alertmanager.yml"
fill /etc/alertmanager/src/email.tmpl > "$out/email.tmpl"
exec /bin/alertmanager --config.file="$out/alertmanager.yml" --storage.path=/alertmanager \
  --web.external-url="$ALERTMANAGER_URL" "$@"
