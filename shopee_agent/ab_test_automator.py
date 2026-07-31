"""Automatic promotion of A/B test winners using statistical significance.

Uses only stdlib (math) for all statistical calculations — no scipy required.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from shopee_agent.skills.ab_testing import ABTestRegistry

# ---------------------------------------------------------------------------
# Statistical helpers — stdlib only
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    """Standard normal CDF via Abramowitz & Stegun approximation (max error 1.5e-7)."""
    if x < 0:
        return 1.0 - _normal_cdf(-x)
    b0 = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    t = 1.0 / (1.0 + b0 * x)
    phi = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    return 1.0 - phi * (b1 * t + b2 * t ** 2 + b3 * t ** 3 + b4 * t ** 4 + b5 * t ** 5)


def two_proportion_z_test(
    successes_a: int, n_a: int,
    successes_b: int, n_b: int,
) -> tuple[float, float]:
    """Two-proportion z-test.

    Returns (z_score, p_value) for the one-sided test H0: p_a >= p_b
    (i.e. a positive z means variant B has a higher rate than control A).
    """
    if n_a == 0 or n_b == 0:
        return 0.0, 1.0
    p_a = successes_a / n_a
    p_b = successes_b / n_b
    p_pool = (successes_a + successes_b) / (n_a + n_b)
    if p_pool == 0.0 or p_pool == 1.0:
        return 0.0, 1.0
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
    if se == 0.0:
        return 0.0, 1.0
    z = (p_b - p_a) / se
    p_value = 1.0 - _normal_cdf(z)
    return z, p_value


# ---------------------------------------------------------------------------
# Automator
# ---------------------------------------------------------------------------

class ABTestAutomator:
    """Evaluates A/B tests and promotes winning variants automatically.

    Parameters
    ----------
    registry : ABTestRegistry
        The shared A/B test registry instance (from skills/ab_testing.py).
    """

    def __init__(self, registry: ABTestRegistry) -> None:
        self._registry = registry
        self._loop_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_and_promote(
        self,
        test_id: str,
        min_confidence: float = 0.95,
        min_samples: int = 30,
    ) -> dict[str, Any]:
        """Evaluate a single test and promote the variant if it wins.

        Returns
        -------
        dict with keys:
            promoted   — bool, whether a winner was promoted
            confidence — float, statistical confidence level (1 - p_value)
            winner     — 'variant', 'control', or '' if undecided
            reason     — human-readable explanation
        """
        summary = self._registry.summary()
        if test_id not in summary:
            return {
                "promoted": False,
                "confidence": 0.0,
                "winner": "",
                "reason": f"Test '{test_id}' not found in registry",
            }

        test = summary[test_id]
        outcomes = test["outcomes"]
        c = outcomes["control"]
        v = outcomes["variant"]

        if c["executions"] < min_samples or v["executions"] < min_samples:
            return {
                "promoted": False,
                "confidence": 0.0,
                "winner": "",
                "reason": (
                    f"Insufficient samples: control={c['executions']}, "
                    f"variant={v['executions']}, need ≥{min_samples} each"
                ),
            }

        z, p_value = two_proportion_z_test(
            c["successes"], c["executions"],
            v["successes"], v["executions"],
        )
        confidence = 1.0 - p_value

        if confidence >= min_confidence and z > 0:
            winner = "variant"
            reason = (
                f"Variant outperforms control with {confidence:.4%} confidence "
                f"(z={z:.3f}, control={c['successes']}/{c['executions']}="
                f"{c['successes']/c['executions']:.4f}, "
                f"variant={v['successes']}/{v['executions']}="
                f"{v['successes']/v['executions']:.4f})"
            )
            self._promote_test(test_id, winner)
        elif confidence >= min_confidence and z <= 0:
            winner = "control"
            reason = (
                f"Control outperforms variant with {confidence:.4%} confidence "
                f"(z={z:.3f})"
            )
            self._promote_test(test_id, winner)
        else:
            winner = ""
            reason = (
                f"No significant winner (confidence={confidence:.4%}, "
                f"need ≥{min_confidence:.0%}, z={z:.3f})"
            )

        return {
            "promoted": bool(winner),
            "confidence": round(confidence, 6),
            "winner": winner,
            "reason": reason,
        }

    def evaluate_all(
        self,
        min_confidence: float = 0.95,
        min_samples: int = 30,
    ) -> list[dict[str, Any]]:
        """Evaluate every active (non-promoted) test in the registry.

        Returns a list of result dicts (see *evaluate_and_promote*), each
        augmented with a ``test_id`` key.
        """
        summary = self._registry.summary()
        results: list[dict[str, Any]] = []
        for test_id in summary:
            if self._is_promoted(test_id):
                continue
            result = self.evaluate_and_promote(test_id, min_confidence, min_samples)
            result["test_id"] = test_id
            results.append(result)
        return results

    def auto_promote_loop(self, interval_seconds: float = 3600.0) -> None:
        """Start a background daemon thread that periodically evaluates all tests.

        The loop runs until *stop_loop* is called.
        """
        if self._loop_thread and self._loop_thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    results = self.evaluate_all()
                    for r in results:
                        if r["promoted"]:
                            print(
                                f"[ABTestAutomator] Promoted {r['test_id']}: "
                                f"{r['reason']}"
                            )
                except Exception as exc:
                    print(f"[ABTestAutomator] Error in evaluation loop: {exc}")
                self._stop_event.wait(interval_seconds)

        self._stop_event.clear()
        self._loop_thread = threading.Thread(
            target=_loop, daemon=True, name="ab-test-automator"
        )
        self._loop_thread.start()

    def stop_loop(self) -> None:
        """Signal the background loop to stop."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_promoted(self, test_id: str) -> bool:
        """Check whether a test has already been promoted."""
        with self._registry._lock:
            test_data = self._registry._tests.get(test_id, {})
            return bool(test_data.get("promoted_winner"))

    def _promote_test(self, test_id: str, winner: str) -> None:
        """Store promotion metadata inside the registry's test record."""
        with self._registry._lock:
            if test_id in self._registry._tests:
                self._registry._tests[test_id]["promoted_at"] = time.time()
                self._registry._tests[test_id]["promoted_winner"] = winner
                self._registry._save()
