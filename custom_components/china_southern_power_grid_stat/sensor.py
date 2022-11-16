"""Sensors for the China Southern Power Grid Statistics integration."""
from __future__ import annotations
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_PASSWORD, ENERGY_KILO_WATT_HOUR
from homeassistant.core import HomeAssistant
from .csg_client import CSGClient
from .const import DOMAIN, CONF_ACCOUNT_NUMBER, CONF_LOGIN_TYPE, CONF_AUTH_TOKEN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    # sensors = [GitHubRepoSensor(github, repo) for repo in config[CONF_REPOS]]
    # async_add_entities(sensors, update_before_add=True)


class CSGSensor(SensorEntity, CoordinatorEntity):
    """"""

    def __init__(self, coordinator: DataUpdateCoordinator, account_number: str):
        SensorEntity.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._coordinator = coordinator
        self._account_number = account_number

    @property
    def name(self):
        # friendly name
        return ""


class CSGEnergySensor(SensorEntity):
    """Representation of a CSG Energy Sensor."""

    _attr_native_unit_of_measurement = ENERGY_KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL

    def update(self) -> None:
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        self._attr_native_value = 23


class CSGCostSensor(SensorEntity):
    """Representation of a CSG Cost Sensor."""

    _attr_native_unit_of_measurement = "CNY"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def update(self) -> None:
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        self._attr_native_value = 23


class CSGHistorySensor(SensorEntity):
    """Representation of a CSG History Sensor."""

    _attr_state_class = SensorStateClass.TOTAL

    def update(self) -> None:
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        self._attr_native_value = 23
