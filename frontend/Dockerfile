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

EXPOSE 14108
