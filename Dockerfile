FROM python:3.12-slim

WORKDIR /app

# CI matrisi (3.10/3.12) ile hizali; torch opsiyonel lstm extra
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip --no-cache-dir

COPY pyproject.toml .
COPY super_otonom/ ./super_otonom/

RUN pip install --no-cache-dir -e ".[lstm]"

EXPOSE 8000

RUN mkdir -p /app/logs /app/data && \
    useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser
CMD ["python", "-m", "super_otonom.main_loop"]
