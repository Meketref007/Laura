#!/bin/bash

#
# cleanup_project.sh - Automated project cleanup & organization
# 
# This script cleans up temporary files, caches, and archives old logs/backups
# Run periodically (e.g., weekly cron job)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🧹 Starting project cleanup...${NC}"

# 1. Remove Python caches
echo "  • Removing Python caches..."
find "$PROJECT_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PROJECT_ROOT" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find "$PROJECT_ROOT" -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
rm -f "$PROJECT_ROOT"/.coverage 2>/dev/null || true

# 2. Remove temporary files at root
echo "  • Removing temporary files..."
rm -f "$PROJECT_ROOT"/nohup.out
rm -f "$PROJECT_ROOT"/.coverage

# 3. Archive old backups (keep 3 most recent)
if [ -d "$PROJECT_ROOT/backups" ]; then
    echo "  • Archiving old backups..."
    mkdir -p "$PROJECT_ROOT/backups/archive"
    cd "$PROJECT_ROOT/backups"
    ls -1t *.tar.gz 2>/dev/null | tail -n +4 | xargs -r -I {} mv {} archive/ 2>/dev/null || true
fi

# 4. Archive old logs (keep 3 days worth)
if [ -d "$PROJECT_ROOT/logs" ]; then
    echo "  • Archiving old logs..."
    mkdir -p "$PROJECT_ROOT/logs/archive"
    cd "$PROJECT_ROOT/logs"
    
    # Archive analysis logs older than 3 days
    find . -maxdepth 1 -name "laura_analysis_2026-05-0[1-9]*" -exec mv {} archive/ \; 2>/dev/null || true
    find . -maxdepth 1 -type f -mtime +3 -exec mv {} archive/ \; 2>/dev/null || true
fi

# 5. Clean reports directory (keep structure, archive old data)
if [ -d "$PROJECT_ROOT/reports" ]; then
    echo "  • Organizing reports..."
    mkdir -p "$PROJECT_ROOT/reports/archive"
    
    # Keep only most recent state files
    cd "$PROJECT_ROOT/reports"
    find . -maxdepth 1 -name "*.state.bak" -delete 2>/dev/null || true
fi

echo -e "${GREEN}✓ Cleanup completed!${NC}"

# Display space savings
echo ""
echo -e "${YELLOW}📊 Storage Usage:${NC}"
du -sh "$PROJECT_ROOT"/* 2>/dev/null | sort -rh | head -10
echo ""
echo -e "${GREEN}✓ Project organized and cleaned${NC}"
