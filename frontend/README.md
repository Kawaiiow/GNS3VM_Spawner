# Frontend

SvelteKit + Tailwind CSS, JavaScript only, managed with Bun.

## Getting Started

### 1. Install dependencies

```bash
bun install
```

### 2. Create the environment file

```bash
cp .env.example .env
```

### 3. Run the frontend

```bash
bun run dev
```

Open `http://localhost:5173`.

## Production

`ORIGIN` is the public URL of the frontend. SvelteKit uses it to accept form submissions, so set it when building.

```bash
ORIGIN=http://localhost:8080 bun run build
PORT=8080 bun run start
```

Behind a TLS proxy that sets `X-Forwarded-Proto`, you can skip `ORIGIN` and run with `PROTOCOL_HEADER=x-forwarded-proto`.

## Docker

```bash
docker build --build-arg ORIGIN=http://localhost:8080 -t netlab-frontend .
docker run -p 8080:8080 -e BACKEND_URL=http://host.docker.internal:8000 netlab-frontend
```
