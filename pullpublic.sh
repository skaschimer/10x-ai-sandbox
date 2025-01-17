#!/bin/bash

# TODO: would be nice if this were idempotent and could be run on an empty repo
# TODO: ...we would need to take an arg for branch to clone from, i.e. development

# Check if the branch argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <public branch name>"
    exit 1
fi

BRANCH=$1

# Add the upstream remote if it doesn't already exist
if ! git remote | grep -q upstream; then
    git remote add upstream https://github.com/GSA-TTS/10x-ai-sandbox.git
fi

# Fetch all remotes
git fetch --all

# Checkout the provided branch
git checkout $BRANCH

# Checkout the development branch
git checkout development

# Reset the development branch to match origin/development
git reset --hard origin/development

# Create a new branch with the current Unix time
git checkout -b "feature/merge-gsai-development/$(date +%s)"

if git ls-remote --exit-code --heads upstream $BRANCH; then
    # Merge the changes from the specified upstream branch
    git merge -X theirs upstream/$BRANCH --allow-unrelated-histories --no-edit
else
    echo "Error: Branch '$BRANCH' does not exist in the upstream repository."
    exit 1
fi
