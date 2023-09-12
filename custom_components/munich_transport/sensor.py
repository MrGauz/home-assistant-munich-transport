"""Munich public transport (MVG) integration."""
from __future__ import annotations
import logging
from typing import Optional

from mvg import MvgApi, MvgApiError
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import PLATFORM_SCHEMA
from .const import (
    DOMAIN,  # noqa
    SCAN_INTERVAL,  # noqa
    CONF_DEPARTURES,
    CONF_DEPARTURES_WALKING_TIME,
    CONF_TYPE_BUS,
    CONF_TYPE_SUBURBAN,
    CONF_TYPE_SUBWAY,
    CONF_TYPE_TRAM,
    CONF_DEPARTURES_NAME,
    CONF_DEPARTURES_DIRECTIONS,
    CONF_DEPARTURES_LINES,
    DEFAULT_ICON,
)
from .departure import Departure

_LOGGER = logging.getLogger(__name__)

TRANSPORT_TYPES_SCHEMA = {
    vol.Optional(CONF_TYPE_SUBURBAN, default=True): bool,
    vol.Optional(CONF_TYPE_SUBWAY, default=True): bool,
    vol.Optional(CONF_TYPE_TRAM, default=True): bool,
    vol.Optional(CONF_TYPE_BUS, default=True): bool,
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEPARTURES): [
            {
                vol.Required(CONF_DEPARTURES_NAME): str,
                vol.Optional(CONF_DEPARTURES_WALKING_TIME, default=1): int,
                vol.Optional(CONF_DEPARTURES_LINES, default=[]): [str],
                vol.Optional(CONF_DEPARTURES_DIRECTIONS): [str],
                **TRANSPORT_TYPES_SCHEMA,
            }
        ]
    }
)


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        add_entities: AddEntitiesCallback,
        _: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform."""
    if CONF_DEPARTURES in config:
        for departure in config[CONF_DEPARTURES]:
            add_entities([TransportSensor(hass, departure)])


class TransportSensor(SensorEntity):
    departures: list[Departure] = []

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass: HomeAssistant = hass
        self.config: dict = config
        self.station_name: str = config.get(CONF_DEPARTURES_NAME)
        # we add +1 minute anyway to delete the "just gone" transport
        self.walking_time: int = config.get(CONF_DEPARTURES_WALKING_TIME) or 1
        # If configured allow only the specified line, else allow all lines
        self.lines: str = config.get(CONF_DEPARTURES_LINES) or []
        # If configured allow only the specified directions, else allow all directions
        self.directions: str = config.get(CONF_DEPARTURES_DIRECTIONS) or None

    @property
    def name(self) -> str:
        return self.station_name

    @property
    def icon(self) -> str:
        next_departure = self.next_departure()
        if next_departure:
            return next_departure.icon
        return DEFAULT_ICON

    @property
    def unique_id(self) -> str:
        return f"stop_{self.station_name}_departures"

    @property
    def state(self) -> str:
        next_departure = self.next_departure()
        if next_departure:
                return f"Next {next_departure.line_name}, {next_departure.direction} at {next_departure.time}"
        return "N/A"

    @property
    def extra_state_attributes(self):
        return {
            "departures": [departure.to_dict() for departure in self.departures or []]
        }

    def update(self):
        self.departures = self.fetch_departures()

    def fetch_departures(self) -> Optional[list[Departure]]:
        try:
            station = MvgApi.station(self.station_name)
        except MvgApiError as e:
            _LOGGER.error("Could not find %s: %s" % (self.station_name, e))
            return None

        _LOGGER.debug(f"OK: station ID for {self.station_name}: {station}")

        mvg_api = MvgApi(station['id'])
        departures = mvg_api.departures(
            limit=30,
            offset=self.walking_time,
        )
        departures = list(filter(lambda d: not bool(d['cancelled']), departures))

        _LOGGER.debug(f"OK: departures for {station['name']}: {departures}")

        # Convert API data into objects
        unsorted = [Departure.from_dict(departure) for departure in departures]

        # Filter departures based on line and direction
        filtered_departures = []
        for departure in unsorted:
            if (
                (not self.lines or departure.line_name in self.lines) and
                (not self.directions or departure.direction in self.directions)
            ):
                filtered_departures.append(departure)

        return sorted(filtered_departures, key=lambda d: d.timestamp)


    def next_departure(self):
        if self.departures and isinstance(self.departures, list):
            return self.departures[0]
        return None
