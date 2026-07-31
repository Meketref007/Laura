#!/bin/bash
# Test Refunds System Integration
# Tests refund management, auto-remediation, and CLI commands

set -e

echo "=========================================="
echo "Testing Refunds System Integration"
echo "=========================================="

cd /home/shopee/agente

# Test 1: Verify modules exist
echo ""
echo "[Test 1] Verifying modules..."
python3 -c "from shopee_agent.refunds import RefundManager, RefundStatus, RefundReason; print('✓ refunds.py loaded')" || exit 1
python3 -c "from shopee_agent.remediation import RemediationEngine, RemediationAction; print('✓ remediation.py loaded')" || exit 1
echo "✓ All modules loaded successfully"

# Test 2: CLI help commands
echo ""
echo "[Test 2] Testing CLI help commands..."
python3 -m shopee_agent.cli refunds --help > /dev/null && echo "✓ refunds --help" || exit 1
python3 -m shopee_agent.cli refunds stats --help > /dev/null && echo "✓ refunds stats --help" || exit 1
python3 -m shopee_agent.cli refunds list --help > /dev/null && echo "✓ refunds list --help" || exit 1
python3 -m shopee_agent.cli refunds approve --help > /dev/null && echo "✓ refunds approve --help" || exit 1
python3 -m shopee_agent.cli refunds reject --help > /dev/null && echo "✓ refunds reject --help" || exit 1
python3 -m shopee_agent.cli refunds auto-evaluate --help > /dev/null && echo "✓ refunds auto-evaluate --help" || exit 1

# Test 3: Stats command (no data expected yet)
echo ""
echo "[Test 3] Testing stats command..."
output=$(python3 -m shopee_agent.cli refunds stats 2>&1 | grep -E "total_refunds|approval_rate_pct|estimated_loss_usd")
if [[ ! -z "$output" ]]; then
    echo "✓ Stats command returned expected fields"
    echo "  Output: $output"
else
    echo "✗ Stats command did not return expected output"
    exit 1
fi

# Test 4: Dry-run approve
echo ""
echo "[Test 4] Testing dry-run approve..."
output=$(python3 -m shopee_agent.cli refunds approve --return-sn test123 --dry-run 2>&1 | grep "DRY RUN")
if [[ ! -z "$output" ]]; then
    echo "✓ Dry-run approve works"
    echo "  Output: $output"
else
    echo "✗ Dry-run approve failed"
    exit 1
fi

# Test 5: Dry-run reject
echo ""
echo "[Test 5] Testing dry-run reject..."
output=$(python3 -m shopee_agent.cli refunds reject --return-sn test123 --dry-run 2>&1 | grep "DRY RUN")
if [[ ! -z "$output" ]]; then
    echo "✓ Dry-run reject works"
    echo "  Output: $output"
else
    echo "✗ Dry-run reject failed"
    exit 1
fi

# Test 6: Dry-run auto-evaluate
echo ""
echo "[Test 6] Testing dry-run auto-evaluate..."
output=$(python3 -m shopee_agent.cli refunds auto-evaluate --dry-run 2>&1 | grep -E "DRY RUN|Auto-evaluated")
if [[ ! -z "$output" ]]; then
    echo "✓ Dry-run auto-evaluate works"
    echo "  Output: $output"
else
    echo "✗ Dry-run auto-evaluate failed"
    exit 1
fi

# Test 7: Refund Manager instantiation
echo ""
echo "[Test 7] Testing RefundManager..."
python3 << 'PYEOF'
from shopee_agent.refunds import create_refund_manager, RefundStatus, RefundReason
manager = create_refund_manager()
stats = manager.get_refund_stats(days=30)
print(f"✓ RefundManager created")
print(f"  Total refunds: {stats.total_refunds}")
print(f"  Pending: {stats.pending_count}")
print(f"  Approval rate: {stats.approval_rate:.1f}%")
PYEOF
[ $? -eq 0 ] || exit 1

# Test 8: RemediationEngine instantiation
echo ""
echo "[Test 8] Testing RemediationEngine..."
python3 << 'PYEOF'
from shopee_agent.refunds import create_refund_manager
from shopee_agent.remediation import create_remediation_engine
manager = create_refund_manager()
engine = create_remediation_engine(manager)
cases = engine.evaluate_and_remediate({
    "high_refund_products": [],
    "damage_in_transit_rate_pct": 0,
    "defective_rate_pct": 0,
})
print(f"✓ RemediationEngine created")
print(f"  Cases evaluated: {len(cases)}")
PYEOF
[ $? -eq 0 ] || exit 1

# Test 9: Verify API client has refund endpoints
echo ""
echo "[Test 9] Testing API client endpoints..."
python3 << 'PYEOF'
from shopee_agent.client import ShopeeClient
from shopee_agent.config import ShopeeConfig
config = ShopeeConfig(
    base_url="https://partner.shopeemobile.com",
    redirect_url="https://localhost:8000/auth/callback",
    partner_id=1,
    partner_key="test",
    default_access_token="test",
    default_shop_id=123,
)
client = ShopeeClient(config)
# Check that refund methods exist
assert hasattr(client, 'get_return_list'), "Missing get_return_list"
assert hasattr(client, 'get_return_detail'), "Missing get_return_detail"
assert hasattr(client, 'confirm_return'), "Missing confirm_return"
assert hasattr(client, 'dispute_return'), "Missing dispute_return"
print("✓ ShopeeClient has all refund endpoints")
PYEOF
[ $? -eq 0 ] || exit 1

echo ""
echo "=========================================="
echo "✓ All tests passed!"
echo "=========================================="
echo ""
echo "Refund management system is operational:"
echo "  • RefundManager: Tracks and evaluates refunds"
echo "  • RemediationEngine: Auto-remediates issues"
echo "  • API Integration: get/approve/reject refunds"
echo "  • CLI Commands: list/stats/approve/reject/auto-evaluate"
