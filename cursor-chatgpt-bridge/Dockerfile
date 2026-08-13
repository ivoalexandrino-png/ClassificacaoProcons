FROM node:22-bookworm-slim AS build

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 make g++ git \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json* ./
RUN npm install

COPY tsconfig.json vitest.config.ts ./
COPY src ./src
COPY tests ./tests

RUN npm run build
RUN npm test

FROM node:22-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY --from=build /app/dist ./dist
COPY data ./data

ENV NODE_ENV=production
ENV PORT=3000
ENV MCP_PATH=/mcp
ENV DATABASE_PATH=/app/data/bridge.db
ENV TRANSPORT=http

EXPOSE 3000

CMD ["node", "dist/index.js"]
