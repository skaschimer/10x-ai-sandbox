# syntax=docker/dockerfile:1
FROM ubuntu:22.04 AS final

COPY z-root-public.crt /usr/local/share/ca-certificates/z-root-public.crt
RUN apt-get update && \
    apt-get install -y ca-certificates \
    curl \
    dnsutils \
    htop \
    less \
    net-tools \
    procps \
    vim \
    python3.11 \
    python3-pip \
    ffmpeg && \
    update-ca-certificates

## We re-declare our ARGs/ENVs as needed
ARG USE_CUDA=false
ARG USE_OLLAMA=false
ARG USE_CUDA_VER
ARG USE_EMBEDDING_MODEL
ARG USE_RERANKING_MODEL
ARG UID=0
ARG GID=0
ARG BUILD_HASH=dev-build

# Minimal runtime environment variables
# ARG PORT_DEFAULT=8081
ENV ENV=prod \
    # PORT=${PORT_DEFAULT} \
    USE_OLLAMA_DOCKER=${USE_OLLAMA} \
    USE_CUDA_DOCKER=${USE_CUDA} \
    USE_CUDA_DOCKER_VER=${USE_CUDA_VER} \
    USE_EMBEDDING_MODEL_DOCKER=${USE_EMBEDDING_MODEL} \
    USE_RERANKING_MODEL_DOCKER=${USE_RERANKING_MODEL} \
    HOME=/root \
    RAG_EMBEDDING_ENGINE=openai \
    WEBUI_BUILD_VERSION=${BUILD_HASH} \
    DOCKER=true

WORKDIR /app

# (Optional) If you run as non-root
RUN if [ $UID -ne 0 ]; then \
    if [ $GID -ne 0 ]; then \
    addgroup --gid $GID app; \
    fi; \
    adduser --uid $UID --gid $GID --home $HOME --disabled-password --no-create-home app; \
    fi
