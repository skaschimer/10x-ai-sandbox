# Stage 1: Frontend build
FROM node:20.18.1 AS build-frontend

ARG PUBLIC_DATADOG_APP_ID=1570fdb1-4af6-40bd-8afc-33962f7e4f75
ARG PUBLIC_DATADOG_CLIENT_TOKEN=pub4943adb8fbab823c0b0d2c75a8100771
ARG PUBLIC_DATADOG_BROWSERLOGS_CLIENT_TOKEN=pub010cb3969c15a90f52d688046cb62a8e
ARG PUBLIC_DATADOG_SERVICE=gsai_rum

ENV PUBLIC_DATADOG_APP_ID=$PUBLIC_DATADOG_APP_ID
ENV PUBLIC_DATADOG_CLIENT_TOKEN=$PUBLIC_DATADOG_CLIENT_TOKEN
ENV PUBLIC_DATADOG_BROWSERLOGS_CLIENT_TOKEN=$PUBLIC_DATADOG_BROWSERLOGS_CLIENT_TOKEN
ENV PUBLIC_DATADOG_SERVICE=$PUBLIC_DATADOG_SERVICE

ENV NODE_OPTIONS=--max-old-space-size=4096
ENV NODE_EXTRA_CA_CERTS=/app/z-root-public.pem

WORKDIR /app

# Add the custom root CA certificate for Zscaler
COPY z-root-public.pem $NODE_EXTRA_CA_CERTS

# Add application manifests and config files
COPY package.json package-lock.json ./
COPY svelte.config.js tailwind.config.js postcss.config.js vite.config.ts tsconfig.json ./

# Install dependencies
RUN npm ci

# Add in the rest of the source code
COPY src ./src

# Build the frontend
RUN npm run build


# Stage 2: Final image build
FROM ubuntu:24.04

# Avoid prompts during package upgrades/installation
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC

# Workaround for Ubuntu + FIPS + openssl bug
# https://bugs.launchpad.net/ubuntu/+source/ca-certificates/+bug/2066990
ARG OPENSSL_FORCE_FIPS_MODE=0

# Install prerequisites
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    # For custom root CA
    ca-certificates \
    # For RAG
    pandoc ffmpeg libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Add the custom root CA certificate for Zscaler
COPY z-root-public.crt /usr/local/share/ca-certificates/z-root-public.crt
RUN update-ca-certificates

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /usr/local/bin/

# Create and set ownership for the app directory
RUN mkdir -p /app && chown -R ubuntu:ubuntu /app

# Switch to the non-root user
USER ubuntu
WORKDIR /app

# Add in the backend files
COPY --chown=ubuntu:ubuntu .python-version .
COPY --chown=ubuntu:ubuntu backend/requirements.txt ./backend/requirements.txt
COPY --chown=ubuntu:ubuntu backend ./backend
COPY --chown=ubuntu:ubuntu start.sh ./start.sh
COPY --chown=ubuntu:ubuntu CHANGELOG.md ./CHANGELOG.md
RUN chmod +x ./start.sh

# Add in the built frontend
COPY --chown=ubuntu:ubuntu --from=build-frontend /app/build ./build

# Install Python (with retries due to Zscaler unreliability)
RUN for i in 1 2 3 4 5; do \
        uv --native-tls python install $(cat .python-version) && break || \
        echo "Attempt $i failed. Retrying in 5 seconds..." && sleep 5; \
    done

# Set up venv and install dependencies
RUN uv venv && uv pip install --no-cache-dir -r backend/requirements.txt

# Set the PATH to include the Python venv
ENV PATH="/app/.venv/bin:$PATH"

# Set the entrypoint for the container
CMD ["/app/start.sh"]
