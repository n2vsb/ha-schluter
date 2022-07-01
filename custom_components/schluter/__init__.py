"""The schluter integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any
from dataclasses import dataclass

from aioschluter import (
    SchluterApi,
    ApiError,
    InvalidUserPasswordError,
    InvalidSessionIdError,
)

import async_timeout
from aiohttp.client_exceptions import ClientConnectorError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up schluter from a config entry."""

    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]

    _LOGGER.debug("Using username %s to connect to Schluter Api", username)

    websession = async_get_clientsession(hass)
    api = SchluterApi(websession)

    coordinator = SchluterDataUpdateCoordinator(hass, api, username, password)
    await coordinator.async_config_entry_first_refresh()

    schluter_data = SchluterData(api, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = schluter_data
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        _LOGGER.debug("Unloading configuration entry %s", entry.entry_id)
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    _LOGGER.debug("Update Listener for entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


class SchluterDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Schluter temerature data from API"""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SchluterApi,
        username: str,
        password: str,
    ) -> None:
        """Initialize."""
        self._username = username
        self._password = password
        self._api = api
        self._sessionid = None

        update_interval = timedelta(minutes=1)
        _LOGGER.debug("Data will be update every %s", update_interval)

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via schluter library"""

        try:
            async with async_timeout.timeout(10):
                if self._sessionid is None:
                    self._sessionid = await self._api.async_get_sessionid(
                        self._username, self._password
                    )
                return await self._api.async_get_current_thermostats(self._sessionid)
        except InvalidSessionIdError as err:
            # if we get a 401 UNAUTHENTICATED the aio library raises the INvalidSessionIdError
            # and we need to get a new sessionid
            try:
                self._sessionid = await self._api.async_get_sessionid(
                    self._username, self._password
                )
            except InvalidUserPasswordError as err:
                raise ConfigEntryAuthFailed from err
            except (ApiError, ClientConnectorError) as err:
                raise UpdateFailed(err) from err
        except InvalidUserPasswordError as err:
            raise ConfigEntryAuthFailed from err
        except (ApiError, ClientConnectorError) as err:
            raise UpdateFailed(err) from err


@dataclass
class SchluterData:
    """Data for the schluter integration."""

    api: SchluterApi
    coordinator: SchluterDataUpdateCoordinator
