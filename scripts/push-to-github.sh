#!/bin/bash
# push-to-github.sh - Helper script to push Laura project to GitHub
# Usage: bash scripts/push-to-github.sh <github-url>

set -e

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/push-to-github.sh <github-repo-url>"
    echo ""
    echo "Examples:"
    echo "  bash scripts/push-to-github.sh https://github.com/username/laura-shopee-agent.git"
    echo "  bash scripts/push-to-github.sh git@github.com:username/laura-shopee-agent.git"
    echo ""
    echo "To create a repository on GitHub:"
    echo "  1. Go to https://github.com/new"
    echo "  2. Create a new repository (don't initialize with README)"
    echo "  3. Copy the repository URL"
    echo "  4. Run this script with that URL"
    exit 1
fi

REPO_URL="$1"

echo "🚀 Pushing Laura Shopee Agent to GitHub..."
echo "Repository: $REPO_URL"
echo ""

# Add remote
echo "▶ Adding GitHub remote..."
git remote add origin "$REPO_URL" 2>/dev/null || {
    echo "Remote 'origin' already exists. Updating..."
    git remote set-url origin "$REPO_URL"
}

# Rename branch if needed
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "▶ Renaming branch from '$CURRENT_BRANCH' to 'main'..."
    git branch -M main
fi

# Push to GitHub
echo "▶ Pushing to GitHub (this may take a moment)..."
git push -u origin main

echo ""
echo "✅ SUCCESS! Your repository is now on GitHub!"
echo ""
echo "Repository URL: $REPO_URL"
echo "Branch: main"
echo ""
echo "Next steps:"
echo "  • Visit: $REPO_URL"
echo "  • Add topics: shopee-api, automation, ai, ollama, python"
echo "  • Enable Issues & Discussions"
echo "  • Share with your team!"
echo ""

