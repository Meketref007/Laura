#!/usr/bin/env python3
"""
laura_health_check.sh equivalent in Python
Periodic health check that writes status and triggers alerts
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shopee_agent.monitoring import get_monitor, initialize_monitoring
from shopee_agent.rate_limit import initialize_default_limits, get_limiter
from shopee_agent.circuit_breaker import initialize_default_circuit_breakers, get_circuit_breaker_manager


def run_health_check():
    """Run comprehensive health check"""
    
    # Initialize monitoring systems
    initialize_monitoring()
    initialize_default_limits()
    initialize_default_circuit_breakers()
    
    # Get status from all systems
    monitor = get_monitor()
    rate_limiter = get_limiter()
    circuit_breaker_manager = get_circuit_breaker_manager()
    
    # Generate health report
    health = monitor.check_health()
    
    # Add additional system metrics
    health["systems"] = {
        "rate_limiter": {
            "endpoints_monitored": len(rate_limiter.get_status()),
            "endpoints": rate_limiter.get_status(),
        },
        "circuit_breaker": {
            "endpoints_monitored": len(circuit_breaker_manager.get_status()),
            "open_circuits": sum(
                1 for breaker in circuit_breaker_manager.get_status().values()
                if breaker["state"] == "OPEN"
            ),
            "endpoints": circuit_breaker_manager.get_status(),
        },
    }
    
    # Save report
    report_file = Path("reports/laura_health_latest.json")
    report_file.parent.mkdir(exist_ok=True)
    report_file.write_text(json.dumps(health, indent=2, ensure_ascii=False))
    
    # Print summary
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": health["overall_status"],
        "alerts_count": len(health["alerts"]),
        "alerts": health["alerts"][:3],  # Top 3 alerts
        "report_saved": str(report_file),
    }, indent=2))
    
    # Exit code based on status
    if health["overall_status"] == "CRITICAL":
        return 1
    elif health["overall_status"] == "DEGRADED":
        return 0  # Still healthy but degraded
    else:
        return 0


if __name__ == "__main__":
    sys.exit(run_health_check())
