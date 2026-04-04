from __future__ import annotations

import hmac
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from src.logger import get_logger

logger = get_logger(__name__)

INTEGRATIONS_FILE = Path("config/integrations.json")

IntegrationType = Literal["bk_hub", "adforge", "webhook", "custom"]


@dataclass
class Integration:
    id: str
    name: str
    type: IntegrationType
    url: str
    api_key: str = ""
    enabled: bool = True
    meta: dict = field(default_factory=dict)  # extra type-specific fields


class IntegrationManager:
    def __init__(self, config_file: Path = INTEGRATIONS_FILE):
        self.config_file = config_file
        self._integrations: dict[str, Integration] = {}
        self._load()

    def _load(self) -> None:
        if self.config_file.exists():
            try:
                raw = json.loads(self.config_file.read_text())
                for item in raw:
                    ig = Integration(**item)
                    self._integrations[ig.id] = ig
            except Exception as e:
                logger.info("Failed to load integrations config, resetting", error=str(e))
                self._integrations = {}

    def _save(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(ig) for ig in self._integrations.values()]
        self.config_file.write_text(json.dumps(data, indent=2))

    def list(self) -> list[Integration]:
        return list(self._integrations.values())

    def list_integrations(self) -> list[dict]:
        """Return integrations as list of dicts (for webhook dispatch)."""
        return [asdict(ig) for ig in self._integrations.values()]

    def get(self, integration_id: str) -> Integration | None:
        return self._integrations.get(integration_id)

    def get_by_type(self, type_: IntegrationType) -> Integration | None:
        for ig in self._integrations.values():
            if ig.type == type_ and ig.enabled:
                return ig
        return None

    def add(self, integration: Integration) -> None:
        self._integrations[integration.id] = integration
        self._save()

    def update(self, integration_id: str, **kwargs) -> Integration | None:
        ig = self._integrations.get(integration_id)
        if not ig:
            return None
        for k, v in kwargs.items():
            if hasattr(ig, k):
                setattr(ig, k, v)
        self._save()
        return ig

    def delete(self, integration_id: str) -> bool:
        if integration_id not in self._integrations:
            return False
        del self._integrations[integration_id]
        self._save()
        return True

    def ensure_defaults(self) -> None:
        """Seed default integrations if config is empty."""
        import os
        if not self._integrations:
            defaults = [
                Integration(
                    id="bk_hub",
                    name="BerkahKarya Hub",
                    type="bk_hub",
                    url=os.environ.get("BK_HUB_URL", "http://localhost:9099"),
                    api_key="",
                    enabled=True,
                    meta={"company": "berkahkarya"},
                ),
                Integration(
                    id="adforge",
                    name="adforge",
                    type="adforge",
                    url=os.environ.get("ADFORGE_URL", "http://localhost:3000"),
                    api_key=os.environ.get("ADFORGE_API_KEY", ""),
                    enabled=True,
                    meta={},
                ),
            ]
            for d in defaults:
                self._integrations[d.id] = d
            self._save()

    def invoke_webhook(self, integration_id: str, event: str, payload: dict) -> None:
        """Fire webhook in background thread — non-blocking."""
        thread = threading.Thread(
            target=self._invoke_webhook_sync,
            args=(integration_id, event, payload),
            daemon=True,
        )
        thread.start()

    def _invoke_webhook_sync(self, integration_id: str, event: str, payload: dict) -> None:
        """Synchronous webhook invocation with circuit breaker."""
        import httpx

        integration = self._get_integration(integration_id)
        if not integration:
            logger.warning("Webhook integration not found", integration_id=integration_id)
            return

        url = integration.get("url", "")
        secret = integration.get("secret", "") or integration.get("api_key", "")
        if not url:
            return

        # Circuit breaker check
        if self._is_circuit_open(integration_id):
            logger.info("Webhook circuit open, skipping", integration_id=integration_id, event=event)
            self._log_attempt(integration_id, event, "skipped", None, "circuit open")
            return

        body = json.dumps(payload, default=str)
        signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest() if secret else ""

        headers = {
            "Content-Type": "application/json",
            "X-Event": event,
            "X-Signature-SHA256": f"sha256={signature}",
        }

        last_error = None
        http_status = None
        for attempt in range(2):  # 2 attempts within the call
            try:
                response = httpx.post(url, content=body, headers=headers, timeout=10.0)
                response.raise_for_status()
                self._log_attempt(integration_id, event, "success", response.status_code, None)
                self._reset_circuit(integration_id)
                logger.info("Webhook delivered", integration_id=integration_id, event=event, status=response.status_code)
                return
            except Exception as e:
                last_error = str(e)
                http_status = getattr(getattr(e, "response", None), "status_code", None)
                if attempt < 1:
                    time.sleep(2 ** attempt)

        # All attempts failed
        self._log_attempt(integration_id, event, "failed", http_status, last_error)
        self._increment_failures(integration_id)
        logger.warning("Webhook delivery failed", integration_id=integration_id, event=event, error=last_error)

    def _get_integration(self, integration_id: str) -> dict | None:
        """Get integration by id from loaded integrations."""
        ig = self._integrations.get(integration_id)
        if ig:
            return asdict(ig)
        # Fallback: match by name
        for integ in self._integrations.values():
            if integ.name == integration_id:
                return asdict(integ)
        return None

    def _is_circuit_open(self, integration_id: str) -> bool:
        """Check if circuit breaker is open for this integration."""
        try:
            from src.db.database import DatabaseManager
            db = DatabaseManager()
            with db._get_connection() as conn:
                row = conn.execute(
                    "SELECT circuit_open, circuit_open_until FROM integration_logs WHERE integration_id=? ORDER BY id DESC LIMIT 1",
                    (integration_id,)
                ).fetchone()
                if row and row[0]:
                    until = row[1]
                    if until and datetime.fromisoformat(until) > datetime.utcnow():
                        return True
                    # Cooldown expired — auto-reset
                    self._reset_circuit(integration_id)
        except Exception:
            pass
        return False

    def _increment_failures(self, integration_id: str) -> None:
        """Increment consecutive failure count; trip circuit after 2."""
        try:
            from src.db.database import DatabaseManager
            db = DatabaseManager()
            with db._get_connection() as conn:
                row = conn.execute(
                    "SELECT consecutive_failures FROM integration_logs WHERE integration_id=? ORDER BY id DESC LIMIT 1",
                    (integration_id,)
                ).fetchone()
                count = (row[0] if row else 0) + 1
                if count >= 2:
                    until = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
                    conn.execute(
                        "UPDATE integration_logs SET circuit_open=1, circuit_open_until=? WHERE integration_id=?",
                        (until, integration_id)
                    )
                    logger.warning("Circuit breaker tripped", integration_id=integration_id, cooldown_until=until)
        except Exception as e:
            logger.info("Could not update circuit state", error=str(e))

    def _reset_circuit(self, integration_id: str) -> None:
        """Reset circuit breaker after successful delivery."""
        try:
            from src.db.database import DatabaseManager
            db = DatabaseManager()
            with db._get_connection() as conn:
                conn.execute(
                    "UPDATE integration_logs SET circuit_open=0, circuit_open_until=NULL, consecutive_failures=0 WHERE integration_id=?",
                    (integration_id,)
                )
        except Exception:
            pass

    def _log_attempt(self, integration_id: str, event: str, status: str, http_status, error: str | None) -> None:
        """Write attempt to integration_logs."""
        try:
            from src.db.database import DatabaseManager
            db = DatabaseManager()
            with db._get_connection() as conn:
                conn.execute(
                    "INSERT INTO integration_logs (integration_id, event, status, http_status, error) VALUES (?,?,?,?,?)",
                    (integration_id, event, status, http_status, error)
                )
        except Exception as e:
            logger.info("Could not write integration log", error=str(e))
