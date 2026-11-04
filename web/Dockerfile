# Сборка из корня репозитория: docker build -f web/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
COPY packages/ui/package.json packages/ui/
COPY web/package.json web/
# Закрытый контур: своё зеркало npm (--build-arg NPM_REGISTRY=…) и корпоративный CA (--secret id=extra_ca,src=ca.crt).
ARG NPM_REGISTRY=https://registry.npmjs.org/
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca npm_config_cafile=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund --registry "$NPM_REGISTRY"
COPY packages/ui packages/ui
COPY web web
RUN npm run build -w platform-web

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
