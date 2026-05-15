FROM python:3.14-slim

WORKDIR /app

# PyTorch: 2.2.x has no cp314 wheels on download.pytorch.org/whl/cpu (Python 3.14).
# Keep CPU index; pin to lowest 3.14-supported line from that index (see pip error "from versions:").
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip --no-cache-dir && \
    pip install --no-cache-dir \
        torch==2.9.0+cpu \
        --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir \
        ccxt>=4.0.0 \
        numpy>=1.24.0 \
        pandas>=2.0.0 \
        scikit-learn>=1.3.0 \
        joblib>=1.3.0 \
        python-dotenv>=1.0.0 \
        prometheus-client>=0.19.0 redis>=5.0.0 aiohttp>=3.9.0 \
        psycopg2-binary>=2.9.9

COPY super_otonom/ ./super_otonom/
COPY pyproject.toml .

EXPOSE 8000

RUN mkdir -p /app/logs /app/data && \
    useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser
CMD ["python", "-m", "super_otonom.main_loop"]

