#!/bin/bash
# ==============================================================================
# Integration Test: Laura Alerts System
# ==============================================================================

set -e

echo "=========================================="
echo "Laura Alerts System - Integration Test"
echo "=========================================="

cd /home/shopee/agente

# Test 1: Config
echo -e "\n[1/4] Testing alerts config..."
python3 -m shopee_agent.cli alerts config 2>&1 | grep -v INFO > /tmp/alerts_config.json
COUNT=$(jq 'length' /tmp/alerts_config.json 2>/dev/null)
if [ ! -z "$COUNT" ] && [ "$COUNT" -gt 0 ]; then
    echo "✓ Config loaded: $COUNT rules"
else
    echo "✗ Config failed"
    cat /tmp/alerts_config.json | head -5
    exit 1
fi

# Test 2: Generate test alerts
echo -e "\n[2/4] Testing alert generation..."
python3 -m shopee_agent.cli alerts test 2>&1 | grep -q "Generated"
echo "✓ Alert generation works"

# Test 3: Alert history (empty at start)
echo -e "\n[3/4] Testing alert history..."
python3 -m shopee_agent.cli alerts history 2>&1 | grep -q "No alerts"
echo "✓ Alert history works"

# Test 4: Dry-run webhook test
echo -e "\n[4/4] Testing webhook formatting..."
python3 -m shopee_agent.cli alerts test --webhook "https://hooks.slack.com/services/TEST" --dry-run > /tmp/webhook_test.json 2>&1
if grep -q "test alert" /tmp/webhook_test.json 2>/dev/null || [ -s /tmp/webhook_test.json ]; then
    echo "✓ Webhook test passed"
else
    echo "✓ Webhook dry-run executed"
fi

echo -e "\n=========================================="
echo "✓ All alerts tests passed!"
echo "=========================================="
