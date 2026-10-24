FROM oven/bun:1 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
RUN bun run build

FROM oven/bun:1-slim
WORKDIR /app
COPY --from=build /app/build ./build
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["bun", "./build"]
