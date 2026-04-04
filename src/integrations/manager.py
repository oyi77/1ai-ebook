from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

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
            except Exception:
                self._integrations = {}

    def _save(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(ig) for ig in self._integrations.values()]
        self.config_file.write_text(json.dumps(data, indent=2))

    def list(self) -> list[Integration]:
        return list(self._integrations.values())

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
