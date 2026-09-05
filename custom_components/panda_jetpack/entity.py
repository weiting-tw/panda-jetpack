"""Shared base for every entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import JetpackCoordinator
from .util import device_mac


class JetpackEntity(CoordinatorEntity[JetpackCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: JetpackCoordinator, entry_id: str, key: str) -> None:
        super().__init__(coordinator)
        identifier = device_mac(coordinator.data or {}) or entry_id
        self._attr_unique_id = f"{identifier}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer="BIGTREETECH",
            model="Panda Jetpack V2",
            name=(coordinator.data or {}).get("sta", {}).get("hostname") or "Panda Jetpack",
            sw_version=coordinator.settings.get("fw_version"),
            configuration_url=f"http://{coordinator.host}/",
        )
