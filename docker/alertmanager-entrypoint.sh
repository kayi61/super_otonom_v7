#!/bin/sh
set -e
CFG=/tmp/alertmanager.yml
BASE=/etc/alertmanager/alertmanager.base.yml

if [ -n "$WEBHOOK_URL" ]; then
  cat >"$CFG" <<EOF
global:
  resolve_timeout: 5m

route:
  receiver: webhook
  group_by: ["alertname", "severity"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: webhook
    webhook_configs:
      - url: "${WEBHOOK_URL}"
        send_resolved: true

inhibit_rules:
  - source_matchers:
      - severity="critical"
    target_matchers:
      - severity="warning"
    equal: ["alertname"]
EOF
else
  cp "$BASE" "$CFG"
fi

exec /bin/alertmanager --config.file="$CFG" --storage.path=/alertmanager "$@"
