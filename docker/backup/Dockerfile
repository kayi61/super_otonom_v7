FROM docker:27-cli

RUN apk add --no-cache bash python3 postgresql16-client redis \
    && chmod 4755 /usr/bin/docker 2>/dev/null || true

COPY docker/backup/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV BACKUP_ROOT=/backup \
    REPO_ROOT=/app \
    BACKUP_CRON="0 2 * * *"

WORKDIR /app
ENTRYPOINT ["/entrypoint.sh"]
