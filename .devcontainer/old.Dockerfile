FROM node:20.15.1

# Install Python 3.11
RUN apt update && apt show python3 && apt install python3 && apt install python3-pip python3-venv -y

# Set the working directory
WORKDIR /workspace

# Expose port 8080
EXPOSE 8080

# Clone the repository to a temp directory
RUN git clone --branch open-webui-devcontainer https://github.com/GSA-TTS/10x-ai-sandbox.git .

# Copy the package.json and package-lock.json files to the container
# COPY /tmp/package.json ./
# COPY /tmp/package-lock.json ./

# Install cypress with zscaler root cert
# COPY /tmp/z-root-public.pem ./
RUN NODE_EXTRA_CA_CERTS=/workspace/z-root-public.pem npm install cypress

# Install Node.js dependencies
RUN npm ci --omit/dev

# # Create and activate virtual environment, then install Python dependencies
# RUN python3 -m venv /workspace/venv \
#     && . /workspace/venv/bin/activate \
#     && pip install --no-cache-dir -r /workspace/backend/requirements.txt

# # Define local variables
# ARG COMBINED_CERT_PATH=/workspace/venv/lib/python3.11/site-packages/certifi/cacert.pem

# # Append z-root-public.pem to the combined certificate path
# RUN cat z-root-public.pem >> ${COMBINED_CERT_PATH}

# # Set environment variables for CA certificates
# ENV REQUESTS_CA_BUNDLE=$COMBINED_CERT_PATH
# ENV SSL_CERT_FILE=$COMBINED_CERT_PATH

# # Run the install_ollama.sh script
# # COPY /tmp/install_ollama.sh ./
# # RUN ./install_ollama.sh

# # RUN ollama serve & sleep 5 && ollama pull llama3.2

# # Copy the rest of the application code into the container
# # COPY /tmp/ .

# # Build the frontend application with increased memory
# ENV NODE_OPTIONS="--max-old-space-size=4096"
# RUN npm run build

# ENV ENABLE_OAUTH_SIGNUP=true
# ENV OAUTH_CLIENT_ID=urn:gov:gsa:openidconnect.profiles:sp:sso:gsa:gsa-ai-sandbox-ada
# ENV OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true
# ENV OAUTH_USE_PKCE=true
# ENV OPENID_PROVIDER_URL=https://idp.int.identitysandbox.gov/.well-known/openid-configuration
# ENV OPENID_REDIRECT_URI=http://0.0.0.0:8080/oauth/oidc/callback
# ENV OAUTH_PROVIDER_NAME="Login.gov"
# ENV OAUTH_ACR_CLAIM=urn:acr.login.gov:auth-only
# ENV OAUTH_NONCE_CLAIM=22

# # not a secret, just an anti-abuse measure
# ARG OAUTH_CLIENT_SECRET
# RUN OAUTH_CLIENT_SECRET=$(head -c 32 /dev/urandom | base64 | sed 's/[^a-zA-Z0-9._-]//g' | sed ':a;N;$!ba;s/\n//g' | head -c 32) && echo "OAUTH_CLIENT_SECRET=$OAUTH_CLIENT_SECRET" > /workspace/.env
# ENV $(cat /workspace/.env)

# COPY start.sh ./start.sh
# # Set the custom start script as the entrypoint
# CMD ["nohup", "./start.sh", "&", "sleep", "infinity"]
