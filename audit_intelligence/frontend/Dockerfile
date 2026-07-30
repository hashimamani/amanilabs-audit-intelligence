FROM node:22-slim AS build

WORKDIR /app

COPY audit_intelligence/frontend/package.json audit_intelligence/frontend/package-lock.json ./
RUN npm ci

COPY audit_intelligence/frontend .

RUN npm run build

FROM nginx:1.27-alpine

COPY audit_intelligence/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
