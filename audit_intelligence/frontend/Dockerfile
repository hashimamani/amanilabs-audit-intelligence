FROM node:22-slim AS build

WORKDIR /app

COPY audit_intelligence/frontend/package.json audit_intelligence/frontend/package-lock.json ./
RUN npm ci

COPY audit_intelligence/frontend .

# Baked into the JS bundle at build time (Vite statically replaces
# import.meta.env.VITE_*) - must be a build ARG, not a container runtime
# env var, since nothing reads it after `npm run build` has already run.
ARG VITE_TENANT_KEY
ENV VITE_TENANT_KEY=$VITE_TENANT_KEY
RUN npm run build

FROM nginx:1.27-alpine

COPY audit_intelligence/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
