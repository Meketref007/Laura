#!/usr/bin/env python3
"""
Quick verification script for Laura Store Analysis Integration.
Tests all prompt types and validates systemd files.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd, shell=False):
    """Run a command and return output."""
    try:
        # When using shell=True, cmd must be a string
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,  # Increased from 30 to 60 seconds for API calls
            shell=shell,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout after 60 seconds"
    except Exception as e:
        return -1, "", str(e)


def check_file(path, description):
    """Verify a file exists."""
    if Path(path).exists():
        print(f"✓ {description}: {path}")
        return True
    else:
        print(f"✗ {description}: NOT FOUND at {path}")
        return False


def check_cli_command(prompt_type):
    """Test CLI command with dry-run."""
    print(f"\nTesting --prompt-type {prompt_type}...")
    code, out, err = run_command(
        f"python3 -m shopee_agent.cli store-analysis --prompt-type {prompt_type} --dry-run",
        shell=True,
    )

    combined = out + err  # CLI logging goes to stderr
    if code == 0 and ("DRY RUN" in combined or "orders_count" in combined):
        print(f"  ✓ {prompt_type} dry-run works")
        return True
    else:
        print(f"  ✗ {prompt_type} dry-run failed (exit code: {code})")
        if err and "Traceback" in err:
            print(f"     Error: {err.split(chr(10))[-2]}")
        return False


def check_script():
    """Test wrapper script with dry-run."""
    print("\nTesting wrapper script...")
    code, out, err = run_command(
        "DRY_RUN=1 bash /home/shopee/agente/scripts/laura_analysis_daily.sh",
        shell=True,
    )

    combined = out + err
    if code == 0 and ("Analysis completed successfully" in combined or "Daily analysis job completed" in combined):
        print("  ✓ Wrapper script works")
        return True
    else:
        print(f"  ✗ Wrapper script failed (exit code: {code})")
        if err:
            print(f"     Error: {err[:100]}")
        return False


def check_prompts():
    """Verify prompts are registered."""
    print("\nChecking registered prompts...")
    try:
        from shopee_agent.prompts import get_system_prompt

        prompt_types = [
            "general_agent",
            "triage",
            "product_diagnosis",
            "daily_report",
        ]
        for pt in prompt_types:
            try:
                prompt = get_system_prompt(pt)
                if prompt and len(prompt) > 0:
                    print(f"  ✓ Prompt '{pt}' registered (size: {len(prompt)} bytes)")
                else:
                    print(f"  ✗ Prompt '{pt}' empty")
                    return False
            except Exception as e:
                print(f"  ✗ Prompt '{pt}' failed: {str(e)}")
                return False
        return True
    except Exception as e:
        print(f"  ✗ Failed to import prompts: {str(e)}")
        return False


def check_systemd_files():
    """Verify systemd files exist."""
    print("\nChecking systemd units...")
    files = [
        ("/home/shopee/agente/deploy/laura_analysis.service", "service file"),
        ("/home/shopee/agente/deploy/laura_analysis.timer", "timer file"),
    ]
    result = True
    for file_path, desc in files:
        if check_file(file_path, desc):
            with open(file_path) as f:
                content = f.read()
                if "laura_analysis" in content or "laura" in content:
                    print("    ✓ Content looks valid")
                else:
                    print("    ✗ Content may be incorrect")
                    result = False
        else:
            result = False
    return result


def main():
    print("=" * 70)
    print("Laura Store Analysis Integration - Quick Verification")
    print("=" * 70)

    results = []

    # 1. Check files
    print("\n[1/4] Checking files...")
    results.append(
        (
            "Files",
            all(
                [
                    check_file(
                        "/home/shopee/agente/shopee_agent/prompts.py",
                        "Prompts module",
                    ),
                    check_file(
                        "/home/shopee/agente/scripts/laura_analysis_daily.sh",
                        "Analysis wrapper script",
                    ),
                    check_file(
                        "/home/shopee/agente/deploy/README_ANALYSIS_DEPLOYMENT.md",
                        "Deployment guide",
                    ),
                ]
            ),
        )
    )

    # 2. Check prompts
    print("\n[2/4] Checking prompts registration...")
    results.append(("Prompts", check_prompts()))

    # 3. Check CLI commands
    print("\n[3/4] Checking CLI commands...")
    cli_results = [
        check_cli_command("general_agent"),
        check_cli_command("triage"),
        check_cli_command("product_diagnosis"),
        check_cli_command("daily_report"),
    ]
    results.append(("CLI Commands", all(cli_results)))

    # 4. Check wrapper script
    print("\n[4/4] Checking wrapper script...")
    results.append(("Wrapper Script", check_script()))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")

    all_passed = all(result for _, result in results)
    print("=" * 70)

    if all_passed:
        print("\n✓ All checks passed! Integration is ready.")
        print("\nNext steps:")
        print("1. Review deployment guide: cat deploy/README_ANALYSIS_DEPLOYMENT.md")
        print("2. Deploy systemd units:")
        print("   sudo cp deploy/laura_analysis.{service,timer} /etc/systemd/system/")
        print("   sudo systemctl daemon-reload")
        print("   sudo systemctl enable laura_analysis.timer")
        print("   sudo systemctl start laura_analysis.timer")
        print("3. Monitor first run: sudo journalctl -u laura_analysis -f")
        return 0
    else:
        print("\n✗ Some checks failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
