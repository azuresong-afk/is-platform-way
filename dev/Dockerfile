# Образ заглушки продукта: docker build --build-arg PRODUCT=fake-scanner -f dev/Dockerfile dev
FROM python:3.12-slim
ARG PRODUCT
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt .
# Закрытый контур: своё зеркало PyPI (--build-arg PIP_INDEX_URL=…) и корпоративный CA (--secret id=extra_ca,src=ca.crt).
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY fakeproduct ./fakeproduct
COPY ${PRODUCT}/main.py ./main.py
RUN useradd -r -u 10001 app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health/ready')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
