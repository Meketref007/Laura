"""Enhanced federated learning — secure aggregation, differential privacy, cross-store sharing."""

from __future__ import annotations

import json
import math
import random
import statistics
import threading
import time
from pathlib import Path
from typing import Any

from shopee_agent.paths import FEDERATED_LEARNING, SHARED_MODELS

from .federated_learning import FederatedLearningCoordinator


class SecureAggregationProtocol:
    """Placeholder for homomorphic encryption & secure multi-party aggregation.

    In production this would wrap a library like PySyft or TenSEAL.
    Here we document the protocol and simulate the interface.
    """

    def encrypt_gradient(self, gradient: dict[str, Any], public_key: str) -> dict[str, Any]:
        """Placeholder: encrypt each numeric value using the provided public key.

        In a real implementation this would serialise the gradient dict,
        encrypt each float with HE (e.g. CKKS), and return an opaque map.
        """
        encrypted: dict[str, Any] = {}
        for key, value in gradient.items():
            if isinstance(value, (int, float)):
                encrypted[key] = {
                    "__encrypted__": True,
                    "ciphertext": f"HE({value})",
                    "public_key_fingerprint": public_key[:16] if public_key else "",
                }
            elif isinstance(value, dict):
                encrypted[key] = self.encrypt_gradient(value, public_key)
            else:
                encrypted[key] = value
        return encrypted

    def aggregate_secure(self, reports: list[dict[str, Any]]) -> dict[str, Any]:
        """Secure multi-party aggregation — simple mean of shared numeric keys."""
        from collections import defaultdict

        numeric_values: dict[str, list[float]] = defaultdict(list)

        def _collect(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (int, float)):
                        numeric_values[k].append(float(v))
                    elif isinstance(v, dict) and v.get("__encrypted__"):
                        raw = v.get("ciphertext", "")
                        try:
                            num_str = raw.replace("HE(", "").replace(")", "")
                            numeric_values[k].append(float(num_str))
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(v, dict):
                        _collect(v)

        for r in reports:
            if isinstance(r, dict):
                _collect(r)

        return {k: round(statistics.mean(v), 6) for k, v in numeric_values.items() if v}


class DifferentialPrivacyEngine:
    """Adds calibrated Laplace noise for (ε, δ)-differential privacy."""

    def _laplace_sample(self, mu: float, b: float) -> float:
        """Sample from Laplace(mu, b) using inverse-CDF transform."""
        u = random.random()
        if u < 0.5:
            return mu + b * math.log(2.0 * u)
        return mu - b * math.log(2.0 * (1.0 - u))

    def _sensitivity(self, params: dict[str, Any]) -> float:
        """Estimate L1 sensitivity of the parameter vector (default 1.0)."""
        return 1.0

    def add_noise(
        self,
        params: dict[str, Any],
        epsilon: float = 1.0,
        delta: float = 1e-5,
    ) -> dict[str, Any]:
        """Add Laplace noise to every numeric leaf in *params*.

        Scale *b* = sensitivity / ε  (pure ε-DP when δ = 0).
        """
        sens = self._sensitivity(params)
        scale = sens / max(epsilon, 1e-12)

        def _noise_leaf(value: Any) -> Any:
            if isinstance(value, (int, float)):
                return round(value + self._laplace_sample(0.0, scale), 6)
            return value

        return self._traverse(params, _noise_leaf)

    def compute_privacy_budget(
        self, num_rounds: int, epsilon: float = 1.0
    ) -> float:
        """Total privacy spend under sequential composition: rounds × ε."""
        return round(num_rounds * epsilon, 6)

    @staticmethod
    def _traverse(
        obj: Any, leaf_fn, key_path: str = ""
    ) -> Any:
        if isinstance(obj, dict):
            return {
                k: DifferentialPrivacyEngine._traverse(v, leaf_fn, f"{key_path}.{k}")
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [
                DifferentialPrivacyEngine._traverse(i, leaf_fn, f"{key_path}[{idx}]")
                for idx, i in enumerate(obj)
            ]
        return leaf_fn(obj)


class CrossStoreModelSharing:
    """Cross-store model sharing — publish and pull models via a shared store."""

    def __init__(self, db_path: str = str(SHARED_MODELS)):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._models: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._models = data
        except Exception:
            self._models = {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._models, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def share_model(
        self,
        source_store: str,
        target_store: str,
        model_data: dict[str, Any],
    ) -> bool:
        """Publish a model from *source_store* for *target_store* to consume."""
        model_id = f"{source_store}->{target_store}"
        entry = {
            "source_store": source_store,
            "target_store": target_store,
            "model_data": model_data,
            "shared_at": time.time(),
            "received": False,
        }
        with self._lock:
            self._models[model_id] = entry
            self._save()
        return True

    def receive_model(self, store_id: str) -> dict[str, Any] | None:
        """Pull the latest model destined for *store_id* and mark it received."""
        candidates: list[str] = []
        with self._lock:
            for model_id, entry in self._models.items():
                if (
                    entry.get("target_store") == store_id
                    and not entry.get("received")
                ):
                    candidates.append(model_id)
            if not candidates:
                return None
            candidates.sort(key=lambda mid: self._models[mid].get("shared_at", 0))
            latest_id = candidates[-1]
            self._models[latest_id]["received"] = True
            self._save()
            return self._models[latest_id].get("model_data")

    def list_shared_models(self) -> list[str]:
        """Return target store IDs of all shared models."""
        with self._lock:
            return [e.get("target_store", "") for e in self._models.values()]

    def list_shared_store_ids(self) -> list[str]:
        """Return list of store IDs that have shared models."""
        return self.list_shared_models()


class FederatedLearningOrchestratorV2:
    """Composes secure aggregation + DP + cross-store sharing on top of
    the original FederatedLearningCoordinator.
    """

    def __init__(self, db_path: str = str(FEDERATED_LEARNING), epsilon: float = 1.0):
        self.coordinator = FederatedLearningCoordinator(db_path=db_path)
        self.secure_agg = SecureAggregationProtocol()
        self.dp_engine = DifferentialPrivacyEngine()
        self.sharing = CrossStoreModelSharing()
        self._epsilon = epsilon
        self._rounds_completed = 0

    def secure_round(self, reports: list[dict[str, Any]]) -> dict[str, Any]:
        """Run a full secure aggregation round with differential privacy.

        1. Securely aggregate encrypted/masked reports.
        2. Add Laplace noise to the aggregated global model.
        3. Publish the noisy model through the base coordinator.
        """
        aggregated = self.secure_agg.aggregate_secure(reports)

        noisy = self.dp_engine.add_noise(aggregated, epsilon=self._epsilon)

        self.coordinator.report(
            "__orchestrator__",
            {"cost_overrides": noisy, "base_actions": []},
        )
        self._rounds_completed += 1

        return {
            "secure_aggregation": aggregated,
            "noisy_model": noisy,
            "round": self._rounds_completed,
            "epsilon_used": self._epsilon,
            "num_stores": len(reports),
        }

    def cross_train(
        self, store_id: str, rounds: int = 3
    ) -> dict[str, Any]:
        """Cross-store training: pull a shared model, train locally, report back.

        Simulates *rounds* local training iterations by collecting the
        aggregated coordinator model and pushing it through the sharing layer.
        """
        results: list[dict[str, Any]] = []
        for rnd in range(1, rounds + 1):
            shared = self.sharing.receive_model(store_id)
            if shared is None:
                shared = {"fallback": True, "round": rnd}

            report_payload = {
                store_id: {
                    "local_model": shared,
                    "round": rnd,
                    "timestamp": time.time(),
                }
            }

            secure_result = self.secure_round([report_payload])

            self.sharing.share_model(
                store_id, "coordinator", secure_result.get("noisy_model", {})
            )

            results.append(
                {
                    "round": rnd,
                    "shared_model_pulled": shared,
                    "secure_result": secure_result,
                }
            )

        return {
            "store_id": store_id,
            "rounds_completed": rounds,
            "results": results,
        }

    def get_privacy_report(self) -> dict[str, Any]:
        """Report total privacy budget spent so far."""
        total_epsilon = self.dp_engine.compute_privacy_budget(
            self._rounds_completed, epsilon=self._epsilon
        )
        return {
            "epsilon_per_round": self._epsilon,
            "epsilon_spent": total_epsilon,
            "total_epsilon_spent": total_epsilon,
            "mechanism": "Laplace",
            "delta": 1e-5,
        }
