FROM node:22-slim

WORKDIR /app

COPY audit_intelligence/frontend/package.json audit_intelligence/frontend/package-lock.json ./
RUN npm ci

COPY audit_intelligence/frontend .

EXPOSE 5173

# Runs the same Vite dev server as local development (not a production
# nginx build) - this project is pre-pilot with no deployment target yet,
# and matching local dev keeps one code path instead of two.
CMD ["npm", "run", "dev", "--", "--host"]
