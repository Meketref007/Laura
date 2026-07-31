#!/bin/bash
set -euo pipefail

# Laura MediaSpace Video Upload Orchestrator
# Automates: init -> upload parts -> complete -> wait completion
# Usage: ./laura_media_video_upload.sh --video-file /path/to/video.mp4 [--access-token TOKEN] [--shop-id SHOP_ID]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PY_CMD="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PY_CMD" ]]; then
    PY_CMD="python3"
fi

LOG_FILE="${PROJECT_DIR}/logs/laura_media_video_upload_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"

# Default values
VIDEO_FILE=""
ACCESS_TOKEN="${SHOPEE_DEFAULT_ACCESS_TOKEN:-}"
SHOP_ID="${SHOPEE_DEFAULT_SHOP_ID:-}"
CHUNK_SIZE=$((5 * 1024 * 1024))  # 5MB chunks
MAX_WAIT_SECONDS=3600
POLL_INTERVAL_SECONDS=10

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --video-file)
            VIDEO_FILE="$2"
            shift 2
            ;;
        --access-token)
            ACCESS_TOKEN="$2"
            shift 2
            ;;
        --shop-id)
            SHOP_ID="$2"
            shift 2
            ;;
        --chunk-size)
            CHUNK_SIZE="$2"
            shift 2
            ;;
        --max-wait-seconds)
            MAX_WAIT_SECONDS="$2"
            shift 2
            ;;
        --poll-interval-seconds)
            POLL_INTERVAL_SECONDS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Validation
if [[ -z "$VIDEO_FILE" ]]; then
    echo "ERROR: --video-file is required" >&2
    exit 1
fi

if [[ ! -f "$VIDEO_FILE" ]]; then
    echo "ERROR: Video file not found: $VIDEO_FILE" >&2
    exit 1
fi

if [[ -z "$ACCESS_TOKEN" ]]; then
    echo "ERROR: Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)" >&2
    exit 1
fi

if [[ -z "$SHOP_ID" ]]; then
    echo "ERROR: Missing shop ID (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)" >&2
    exit 1
fi

FILE_SIZE=$(wc -c < "$VIDEO_FILE" | tr -d ' ')
FILE_MD5=$(md5sum "$VIDEO_FILE" | awk '{print $1}')
FILE_NAME=$(basename "$VIDEO_FILE")

log_message() {
    local level="$1"
    shift
    local msg="$*"
    local ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [$level] $msg" | tee -a "$LOG_FILE"
}

log_message "INFO" "=========================================="
log_message "INFO" "Laura MediaSpace Video Upload"
log_message "INFO" "=========================================="
log_message "INFO" "Video file: $VIDEO_FILE"
log_message "INFO" "File size: $FILE_SIZE bytes"
log_message "INFO" "File MD5: $FILE_MD5"
log_message "INFO" "Chunk size: $CHUNK_SIZE bytes"
log_message "INFO" "Shop ID: $SHOP_ID"

# Step 1: Init upload
log_message "INFO" "[1/4] Initializing video upload..."
INIT_RESPONSE=$("$PY_CMD" -m shopee_agent.cli media-video-init-upload \
    --access-token "$ACCESS_TOKEN" \
    --shop-id "$SHOP_ID" \
    --file-size "$FILE_SIZE" \
    --file-md5 "$FILE_MD5" 2>&1)

VIDEO_UPLOAD_ID=$(echo "$INIT_RESPONSE" | "$PY_CMD" -c "import sys, json; print(json.load(sys.stdin)['response']['video_upload_id'])" 2>/dev/null || true)

if [[ -z "$VIDEO_UPLOAD_ID" ]]; then
    log_message "ERROR" "Failed to initialize video upload"
    echo "$INIT_RESPONSE" >> "$LOG_FILE"
    exit 1
fi

log_message "INFO" "Video upload ID: $VIDEO_UPLOAD_ID"

# Step 2: Upload parts
log_message "INFO" "[2/4] Uploading video parts..."

TOTAL_CHUNKS=$(( (FILE_SIZE + CHUNK_SIZE - 1) / CHUNK_SIZE ))
PART_SEQ_LIST=""

for PART_NUM in $(seq 0 $((TOTAL_CHUNKS - 1))); do
    OFFSET=$((PART_NUM * CHUNK_SIZE))
    UPLOAD_SIZE=$((FILE_SIZE - OFFSET < CHUNK_SIZE ? FILE_SIZE - OFFSET : CHUNK_SIZE))
    
    log_message "INFO" "  Uploading part $PART_NUM (offset=$OFFSET, size=$UPLOAD_SIZE)..."
    
    CHUNK_FILE="/tmp/laura_video_part_${PART_NUM}.bin"
    dd if="$VIDEO_FILE" of="$CHUNK_FILE" bs=1 skip=$OFFSET count=$UPLOAD_SIZE 2>/dev/null
    
    PART_MD5=$(md5sum "$CHUNK_FILE" | awk '{print $1}')
    
    UPLOAD_RESPONSE=$("$PY_CMD" -m shopee_agent.cli media-video-upload-part \
        --access-token "$ACCESS_TOKEN" \
        --shop-id "$SHOP_ID" \
        --video-upload-id "$VIDEO_UPLOAD_ID" \
        --part-seq "$PART_NUM" \
        --part-file "$CHUNK_FILE" \
        --content-md5 "$PART_MD5" 2>&1)
    
    rm -f "$CHUNK_FILE"
    
    ERROR=$(echo "$UPLOAD_RESPONSE" | "$PY_CMD" -c "import sys, json; d=json.load(sys.stdin); print(d.get('error', ''))" 2>/dev/null || true)
    if [[ -n "$ERROR" ]] && [[ "$ERROR" != "null" ]]; then
        log_message "ERROR" "Failed to upload part $PART_NUM: $ERROR"
        echo "$UPLOAD_RESPONSE" >> "$LOG_FILE"
        exit 1
    fi
    
    PART_SEQ_LIST="${PART_SEQ_LIST}${PART_NUM},"
    log_message "INFO" "  Part $PART_NUM uploaded successfully"
done

# Remove trailing comma
PART_SEQ_LIST="${PART_SEQ_LIST%,}"

# Step 3: Complete upload
log_message "INFO" "[3/4] Completing video upload..."

COMPLETE_RESPONSE=$("$PY_CMD" -m shopee_agent.cli media-video-complete-upload \
    --access-token "$ACCESS_TOKEN" \
    --shop-id "$SHOP_ID" \
    --video-upload-id "$VIDEO_UPLOAD_ID" \
    --part-seq-list "$PART_SEQ_LIST" 2>&1)

ERROR=$(echo "$COMPLETE_RESPONSE" | "$PY_CMD" -c "import sys, json; d=json.load(sys.stdin); print(d.get('error', ''))" 2>/dev/null || true)
if [[ -n "$ERROR" ]] && [[ "$ERROR" != "null" ]]; then
    log_message "ERROR" "Failed to complete upload: $ERROR"
    echo "$COMPLETE_RESPONSE" >> "$LOG_FILE"
    exit 1
fi

log_message "INFO" "Upload completed successfully (parts: $PART_SEQ_LIST)"

# Step 4: Wait for transcoding
log_message "INFO" "[4/4] Waiting for video transcoding (max $MAX_WAIT_SECONDS seconds)..."

WAIT_RESPONSE=$("$PY_CMD" -m shopee_agent.cli media-video-wait-completion \
    --access-token "$ACCESS_TOKEN" \
    --shop-id "$SHOP_ID" \
    --video-upload-id "$VIDEO_UPLOAD_ID" \
    --max-wait-seconds "$MAX_WAIT_SECONDS" \
    --poll-interval-seconds "$POLL_INTERVAL_SECONDS" 2>&1)

COMPLETED=$(echo "$WAIT_RESPONSE" | "$PY_CMD" -c "import sys, json; print(json.load(sys.stdin).get('completed', False))" 2>/dev/null || echo "false")

if [[ "$COMPLETED" == "True" ]]; then
    FINAL_STATUS=$(echo "$WAIT_RESPONSE" | "$PY_CMD" -c "import sys, json; print(json.load(sys.stdin).get('status', 'UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
    ELAPSED=$(echo "$WAIT_RESPONSE" | "$PY_CMD" -c "import sys, json; print(json.load(sys.stdin).get('elapsed_seconds', 0))" 2>/dev/null || echo "0")
    
    log_message "INFO" "=========================================="
    log_message "INFO" "Video upload completed!"
    log_message "INFO" "Status: $FINAL_STATUS"
    log_message "INFO" "Elapsed: ${ELAPSED}s"
    log_message "INFO" "Video upload ID: $VIDEO_UPLOAD_ID"
    log_message "INFO" "=========================================="
    
    exit 0
else
    TIMEOUT=$(echo "$WAIT_RESPONSE" | "$PY_CMD" -c "import sys, json; print(json.load(sys.stdin).get('timeout', False))" 2>/dev/null || echo "false")
    
    if [[ "$TIMEOUT" == "True" ]]; then
        LAST_STATUS=$(echo "$WAIT_RESPONSE" | "$PY_CMD" -c "import sys, json; print(json.load(sys.stdin).get('last_status', 'UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
        log_message "WARN" "Wait timeout (still $LAST_STATUS). Video upload ID: $VIDEO_UPLOAD_ID"
        log_message "WARN" "Check status later with: laura media-video-upload-result --video-upload-id $VIDEO_UPLOAD_ID"
        exit 0
    else
        log_message "ERROR" "Unexpected response from wait-completion"
        echo "$WAIT_RESPONSE" >> "$LOG_FILE"
        exit 1
    fi
fi
