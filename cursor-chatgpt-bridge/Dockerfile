# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/dist ./dist
RUN mkdir -p /app/data

EXPOSE 3000

# CURSOR_BRIDGE_TOKEN and CURSOR_API_KEY must be provided at runtime
# (e.g. `docker run --env-file .env ...`); see README.md.
CMD ["node", "dist/index.js"]
