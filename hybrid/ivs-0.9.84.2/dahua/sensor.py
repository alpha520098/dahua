"""Event-driven ANPR sensor for the Dahua hybrid integration."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from custom_components.dahua import DahuaDataUpdateCoordinator

from .const import DOMAIN
from .entity import DahuaBaseEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_devices):
    """Set up Dahua sensors."""
    coordinator: DahuaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_devices([DahuaLicensePlateSensor(coordinator, entry)])


class DahuaLicensePlateSensor(DahuaBaseEntity, SensorEntity):
    """Show the most recently recognized license plate."""

    def __init__(self, coordinator: DahuaDataUpdateCoordinator, entry):
        DahuaBaseEntity.__init__(self, coordinator, entry)
        SensorEntity.__init__(self)
        self._attr_icon = "mdi:car-back"
        self._unique_id = f"{coordinator.get_serial_number()}_license_plate"

    @property
    def name(self):
        return f"{self._coordinator.get_device_name()} License Plate"

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def native_value(self):
        value = self._coordinator.get_last_plate()
        return value if value != "unknown" else None

    @property
    def extra_state_attributes(self):
        return self._coordinator.get_last_plate_data()

    async def async_added_to_hass(self):
        self._coordinator.add_plate_listener(self.schedule_update_ha_state)

    @property
    def should_poll(self) -> bool:
        return False
