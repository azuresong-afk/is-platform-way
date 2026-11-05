FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app
WORKDIR /app
# Версии и хэши — из requirements.lock (SECURITY.md, п. 10): сборка повторяема, подмена пакета в зеркале не пройдёт.
# Пересобрать файл после правки зависимостей в pyproject.toml — команда в его заголовке.
COPY requirements.lock ./
# Закрытый контур: своё зеркало PyPI (--build-arg PIP_INDEX_URL=…) и корпоративный CA (--secret id=extra_ca,src=ca.crt).
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --index-url "$PIP_INDEX_URL" --require-hashes --only-binary=:all: -r requirements.lock
# Сам пакет не ставим: код лежит в /app/app, PYTHONPATH=/app.
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh && useradd -r -u 10001 app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health/ready')"
ENTRYPOINT ["docker-entrypoint.sh"]
