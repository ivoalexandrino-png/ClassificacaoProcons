# cursor-chatgpt-bridge — remote MCP server
# Node 22 is required by @cursor/sdk (>=22.13).
FROM node:22-bookworm-slim AS build
WORKDIR /app

# Install dependencies (better-sqlite3 ships prebuilt binaries; build tools are a fallback).
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# ---- Runtime image ----
FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund

COPY --from=build /app/dist ./dist
RUN mkdir -p /app/data

EXPOSE 3000
# Health: GET /health. MCP endpoint: POST /mcp (bearer auth).
CMD ["node", "dist/index.js"]
