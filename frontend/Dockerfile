FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./

# 冷构建时 npm registry 连接可能被中断；跨构建复用下载缓存，并对瞬时网络故障重试。
ARG NPM_REGISTRY=https://registry.npmjs.org/
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm config set registry "${NPM_REGISTRY}" \
    && npm config set fetch-retries 5 \
    && npm config set fetch-retry-factor 2 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm config set fetch-timeout 300000 \
    && npm config set maxsockets 5 \
    && for attempt in 1 2 3; do \
        if npm ci --prefer-offline; then exit 0; fi; \
        if [ "${attempt}" -ge 3 ]; then exit 1; fi; \
        echo "npm ci 第 ${attempt} 次失败，复用缓存后重试"; \
        sleep $((attempt * 5)); \
    done

COPY . .
RUN npm run build

FROM nginx:alpine

ARG OPENTRACE_FRONTEND_BUILD_FINGERPRINT=unknown
LABEL org.opentrace.build-fingerprint="${OPENTRACE_FRONTEND_BUILD_FINGERPRINT}"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY configure-nginx-rootless.sh /usr/local/bin/configure-nginx-rootless.sh
COPY --from=build /app/dist /usr/share/nginx/html
RUN sh /usr/local/bin/configure-nginx-rootless.sh /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx /etc/nginx/conf.d /usr/share/nginx/html

USER nginx
EXPOSE 14108
