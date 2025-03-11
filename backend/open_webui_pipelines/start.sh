#!/usr/bin/env bash
PORT=9099
HOST="${HOST:-0.0.0.0}"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR" || exit


# Function to download the pipeline files
download_pipelines() {
  local path=$1
  local destination=$2

  # Remove any surrounding quotes from the path
  path=$(echo "$path" | sed 's/^"//;s/"$//')

  echo "Downloading pipeline files from $path to $destination..."

  if [[ "$path" =~ ^https://github.com/.*/.*/blob/.* ]]; then
    # It's a single file
    dest_file=$(basename "$path")
    curl -L "$path?raw=true" -o "$destination/$dest_file"
  elif [[ "$path" =~ ^https://github.com/.*/.*/tree/.* ]]; then
    # It's a folder
    git_repo=$(echo "$path" | awk -F '/tree/' '{print $1}')
    subdir=$(echo "$path" | awk -F '/tree/' '{print $2}')
    git clone --depth 1 --filter=blob:none --sparse "$git_repo" "$destination"
    (
      cd "$destination" || exit
      git sparse-checkout set "$subdir"
    )
  elif [[ "$path" =~ \.py$ ]]; then
    # It's a single .py file (but not from GitHub)
    dest_file=$(basename "$path")
    curl -L "$path" -o "$destination/$dest_file"
  else
    echo "Invalid URL format: $path"
    exit 1
  fi
}

# Function to parse and install requirements from frontmatter
install_frontmatter_requirements() {
  local file=$1
  local file_content=$(cat "$1")
  # Extract the first triple-quoted block
  local first_block=$(echo "$file_content" | awk '/"""/{flag=!flag; if(flag) count++; if(count == 2) {exit}} flag')

  # Check if the block contains requirements
  local requirements=$(echo "$first_block" | grep -i 'requirements:')

  if [ -n "$requirements" ]; then
    # Extract the requirements list
    requirements=$(echo "$requirements" | awk -F': ' '{print $2}' | tr ',' ' ' | tr -d '\r')

    # Construct and echo the pip install command
    local pip_command="pip3 install $requirements"
    echo "$pip_command"
    pip3 install $requirements
  else
    echo "No requirements found in frontmatter of $file."
  fi
}

# Check if PIPELINES_URLS environment variable is set and non-empty
if [[ -n "$PIPELINES_URLS" ]]; then
  pipelines_dir="./pipelines"
  mkdir -p "$pipelines_dir"

  # Split PIPELINES_URLS by ';' and iterate over each path
  IFS=';' read -ra ADDR <<<"$PIPELINES_URLS"
  for path in "${ADDR[@]}"; do
    download_pipelines "$path" "$pipelines_dir"
  done

  for file in "$pipelines_dir"/*; do
    if [[ -f "$file" ]]; then
      install_frontmatter_requirements "$file"
    fi
  done
else
  echo "PIPELINES_URLS not specified. Skipping pipelines download and installation."
fi

uvicorn main:app --host "$HOST" --port "$PORT" --forwarded-allow-ips '*'
