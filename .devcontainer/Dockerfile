# FROM node:20.15.1
# FROM python:3.X-slim
FROM cloudfoundry/cflinuxfs4:1.232.0

# Set the working directory
WORKDIR /workspace

# Install Python 3.11
RUN apt-get update \
    && apt-get install -y \
    build-essential \
    curl \
    gnupg \
    ca-certificates 

RUN apt-get autoclean && apt-get clean && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip 

# Copy the Node.js tarball to the /tmp directory
COPY node-v20.18.1-linux-x64.tar.xz /tmp/

# Extract the tarball to /usr/local and set up symlinks
RUN tar -xJf /tmp/node-v20.18.1-linux-x64.tar.xz -C /usr/local && \
    ln -s /usr/local/node-v20.18.1-linux-x64/bin/node /usr/bin/node && \
    ln -s /usr/local/node-v20.18.1-linux-x64/bin/npm /usr/bin/npm && \
    rm /tmp/node-v20.18.1-linux-x64.tar.xz
RUN node -v

COPY z-root-public.crt /usr/local/share/ca-certificates
RUN update-ca-certificates

# Create a non-root user
RUN useradd -m appuser
RUN chown -R appuser:appuser /workspace
USER appuser

# Add /home/appuser/.local/bin to PATH
ENV PATH=/home/appuser/.local/bin:$PATH

COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN echo $(pip show torch)

EXPOSE 8080

RUN rm -rf workspace/package-lock.json workspace/node_modules
COPY package.json ./
# RUN npm install yarn --verbose
RUN NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/z-root-public.crt npm yarn --verbose

COPY . .

# Build the frontend application with increased memory
ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN npm run build

# Define local variables
ARG COMBINED_CERT_PATH=/workspace/venv/lib/python3.11/site-packages/certifi/cacert.pem
RUN cat /workspace/z-root-public.crt >> ${COMBINED_CERT_PATH}
ENV REQUESTS_CA_BUNDLE=$COMBINED_CERT_PATH
ENV SSL_CERT_FILE=$COMBINED_CERT_PATH

# # Run the install_ollama.sh script
# RUN ./install_ollama.sh
# RUN ollama serve & sleep 5 && ollama pull llama3.2

# Prevent pulling sentence transformers model
ENV RAG_EMBEDDING_ENGINE=openai

CMD ["nohup", "./start.sh", "&", "sleep", "infinity"]
