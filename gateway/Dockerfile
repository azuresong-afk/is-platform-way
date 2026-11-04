# Шлюз «Платформы»: один origin, маршруты к оболочке, API платформы и продуктам.
FROM nginxinc/nginx-unprivileged:1.27-alpine
USER root
COPY render.sh /docker-entrypoint.d/05-render-gateway.sh
RUN chmod 0755 /docker-entrypoint.d/05-render-gateway.sh \
 && rm -f /etc/nginx/conf.d/default.conf \
 && touch /etc/nginx/conf.d/default.conf && chown 101:101 /etc/nginx/conf.d/default.conf
USER 101
EXPOSE 8080 8443
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
