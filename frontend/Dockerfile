FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine

ARG OPENTRACE_FRONTEND_BUILD_FINGERPRINT=unknown
LABEL org.opentrace.build-fingerprint="${OPENTRACE_FRONTEND_BUILD_FINGERPRINT}"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN sed -Ei 's#^pid[[:space:]]+/run/nginx.pid;#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx /var/run /etc/nginx/conf.d /usr/share/nginx/html

USER nginx
EXPOSE 14108
