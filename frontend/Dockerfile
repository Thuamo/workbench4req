FROM node:22-slim AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY scripts/prepare-standalone.mjs /scripts/prepare-standalone.mjs
ENV API_INTERNAL_URL=http://api:8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build
FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
