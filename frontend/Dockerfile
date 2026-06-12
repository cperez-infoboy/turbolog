FROM node:22-slim AS build

WORKDIR /app

# Copy dependency files first (for caching)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# Production stage — just the build output
FROM node:22-slim
WORKDIR /app
COPY --from=build /app/build ./build
