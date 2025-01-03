#!/bin/bash

# Request the tag from the user
read -p "Enter the tag to look up (in v1.0.0 format): " tag

# Add the public upstream repo, ignore error if it already exists
git remote add upstream https://github.com/open-webui/open-webui.git 2>/dev/null

# Fetch the tags from the upstream remote without updating local tags
git fetch upstream tag $tag

# Show the commit associated with the specified tag
commit=$(git rev-list -n 1 $tag)
echo "Commit associated with tag $tag: $commit"

# Create a new local branch from the specified commit
branch_name="open-webui-release/$tag"
git checkout -b $branch_name $commit

echo "New branch '$branch_name' created from commit $commit"
