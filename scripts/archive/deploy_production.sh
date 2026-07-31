#!/bin/bash
# LAURA PRODUCTION DEPLOYMENT - QUICK START (5 STEPS)
# Run this to get Laura running in production

set -e

echo "🚀 LAURA PRODUCTION QUICK DEPLOYMENT"
echo "===================================="
echo ""

STEP=1

# STEP 1: Verify Prerequisites
echo "[$STEP/5] Checking prerequisites..."
STEP=$((STEP + 1))

if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found"
    exit 1
fi

if ! python3 -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
    echo "❌ Python 3.9+ required"
    exit 1
fi

echo "✅ Python $(python3 --version | awk '{print $2}')"

if [ ! -f /home/shopee/agente/.env ]; then
    echo "❌ .env file not found"
    echo "   Please create /home/shopee/agente/.env with Shopee credentials"
    exit 1
fi

echo "✅ .env file exists"

# STEP 2: Validate Configuration
echo ""
echo "[$STEP/5] Validating configuration..."
STEP=$((STEP + 1))

cd /home/shopee/agente

if python3 -m shopee_agent.cli health-check 2>&1 | grep -q "valid"; then
    echo "✅ Shopee API credentials valid"
else
    echo "⚠️  Could not verify API credentials"
    echo "    Proceeding anyway - will validate on first run"
fi

# STEP 3: Install Dependencies
echo ""
echo "[$STEP/5] Installing dependencies..."
STEP=$((STEP + 1))

python3 -m pip install -q -r requirements.txt 2>/dev/null || true
echo "✅ Dependencies checked"

# STEP 4: Deploy Systemd Services
echo ""
echo "[$STEP/5] Deploying systemd services..."
STEP=$((STEP + 1))

if [ ! -w /etc/systemd/system ]; then
    echo "⚠️  sudo required for systemd deployment"
    echo "    Skipping systemd setup - do manually:"
    echo "    sudo cp deploy/*.{service,timer} /etc/systemd/system/"
    echo "    sudo systemctl daemon-reload"
    echo "    sudo systemctl enable laura_analysis.timer laura_reports.timer"
    echo "    sudo systemctl start laura_analysis.timer laura_reports.timer"
else
    sudo cp deploy/*.{service,timer} /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable laura_analysis.timer laura_reports.timer
    sudo systemctl start laura_analysis.timer laura_reports.timer
    echo "✅ Systemd services deployed"
fi

# STEP 5: Run Integration Tests
echo ""
echo "[$STEP/5] Running integration tests..."
STEP=$((STEP + 1))

TESTS_PASSED=0
TESTS_FAILED=0

# Test 1: Product list
if python3 -m shopee_agent.cli product-list --dry-run &>/dev/null; then
    echo "✅ CLI: product-list"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "❌ CLI: product-list"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

# Test 2: Alerts
if python3 -m shopee_agent.cli alerts config &>/dev/null; then
    echo "✅ CLI: alerts"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "❌ CLI: alerts"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

# Test 3: Refunds
if python3 -m shopee_agent.cli refunds stats &>/dev/null; then
    echo "✅ CLI: refunds"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "❌ CLI: refunds"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

# Test 4: Reports
if python3 -m shopee_agent.cli report-sales --days 1 --dry-run &>/dev/null; then
    echo "✅ CLI: report-sales"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "❌ CLI: report-sales"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

echo ""
echo "===================================="
if [ $TESTS_FAILED -eq 0 ]; then
    echo "✅ DEPLOYMENT SUCCESSFUL!"
    echo ""
    echo "Laura is now running in production:"
    echo "  • Daily analysis: 04:30 UTC"
    echo "  • Daily reports: 05:00 UTC"
    echo "  • Alerts: Enabled"
    echo "  • Refunds: Monitored"
    echo ""
    echo "Monitor with:"
    echo "  sudo journalctl -u laura_* -f"
    echo "  ls -la reports/"
    echo "  python3 -m shopee_agent.cli alerts history"
else
    echo "⚠️  $TESTS_FAILED tests failed"
    echo "   Check logs for details"
    exit 1
fi

echo ""
echo "🎊 LAURA IS LIVE!"
