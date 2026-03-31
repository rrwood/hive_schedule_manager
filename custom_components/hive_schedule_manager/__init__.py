"""The Hive Schedule Manager integration."""
import logging
from datetime import timedelta
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval, async_call_later

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_ID_TOKEN,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    CONF_HOME_ID,
    CONF_DEVICE_KEY,
    CONF_DEVICE_GROUP_KEY,
    CONF_DEVICE_PASSWORD,
    SERVICE_SET_DAY_SCHEDULE,
    SERVICE_REFRESH_TOKEN,
    DAYS_OF_WEEK,
    DEFAULT_PROFILES,
)
from .hive_api import HiveAPI, HiveAPIError

_LOGGER = logging.getLogger(__name__)

# Service schemas
SERVICE_SET_DAY_SCHEDULE_SCHEMA = vol.Schema({
    vol.Required("node_id"): cv.string,
    vol.Required("day"): vol.In(list(DAYS_OF_WEEK.keys())),
    vol.Optional("profile"): vol.In(list(DEFAULT_PROFILES.keys())),
    vol.Optional("schedule"): vol.All(
        cv.ensure_list,
        [
            vol.Schema({
                vol.Required("time"): cv.string,
                vol.Required("temp"): vol.Coerce(float),
            })
        ]
    ),
})

SERVICE_REFRESH_TOKEN_SCHEMA = vol.Schema({})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hive Schedule Manager from a config entry."""
    
    # Device credentials are populated automatically during initial setup (ConfirmDevice
    # + UpdateDeviceStatus called immediately after SMS MFA). Options values act as
    # emergency overrides and take priority over entry data.
    opts = entry.options or {}
    device_key = opts.get(CONF_DEVICE_KEY) or entry.data.get(CONF_DEVICE_KEY)
    device_group_key = opts.get(CONF_DEVICE_GROUP_KEY) or entry.data.get(CONF_DEVICE_GROUP_KEY)
    device_password = opts.get(CONF_DEVICE_PASSWORD) or entry.data.get(CONF_DEVICE_PASSWORD)
    refresh_token = opts.get(CONF_REFRESH_TOKEN) or entry.data.get(CONF_REFRESH_TOKEN)

    if device_key:
        _LOGGER.info(
            "Device credentials loaded — key=%s group=%s password_len=%d",
            device_key, device_group_key, len(device_password) if device_password else 0,
        )
    else:
        _LOGGER.warning(
            "No device credentials found — token refresh will fail after ~1 hour. "
            "Re-add the integration to re-run the setup flow."
        )

    if opts.get(CONF_REFRESH_TOKEN):
        _LOGGER.info("Refresh token: using options override (len=%d)", len(refresh_token))
    else:
        _LOGGER.info(
            "Refresh token: from auth session (len=%d)",
            len(refresh_token) if refresh_token else 0,
        )

    # Initialize API client
    api = HiveAPI(
        email=entry.data[CONF_EMAIL],
        password=entry.data.get(CONF_PASSWORD),
        id_token=entry.data.get(CONF_ID_TOKEN),
        access_token=entry.data.get(CONF_ACCESS_TOKEN),
        refresh_token=refresh_token,
        user_id=entry.data.get(CONF_USER_ID),
        device_key=device_key,
        device_group_key=device_group_key,
        device_password=device_password,
    )
    
    # Store in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "home_id": entry.data.get(CONF_HOME_ID),
    }
    
    async def async_handle_set_day_schedule(call: ServiceCall) -> None:
        """Handle set_day_schedule service call."""
        node_id = call.data["node_id"]
        day = call.data["day"]
        profile = call.data.get("profile")
        custom_schedule = call.data.get("schedule")
        
        try:
            # Get the API instance
            api = hass.data[DOMAIN][entry.entry_id]["api"]
            home_id = hass.data[DOMAIN][entry.entry_id]["home_id"]
            
            # Get current schedule
            _LOGGER.debug("Fetching schedule for node_id=%r with home_id=%r", node_id, home_id)
            current_schedule = await api.async_get_schedule(home_id, node_id)
            if not current_schedule:
                _LOGGER.error("Could not retrieve current schedule for node %s", node_id)
                return
            
            # Determine which schedule to use
            if custom_schedule:
                new_day_schedule = custom_schedule
            elif profile:
                new_day_schedule = DEFAULT_PROFILES.get(profile, [])
            else:
                _LOGGER.error("Either 'profile' or 'schedule' must be provided")
                return
            
            # Get the day index
            day_index = DAYS_OF_WEEK[day]
            
            # Remove existing setpoints for this day
            updated_setpoints = [
                sp for sp in current_schedule.get("setpoints", [])
                if sp["dayIndex"] != day_index
            ]
            
            # Add new setpoints for this day
            for slot in new_day_schedule:
                setpoint = api.create_setpoint(
                    day_index=day_index,
                    time=slot["time"],
                    temperature=slot["temp"]
                )
                updated_setpoints.append(setpoint)
            
            # Sort setpoints by day and time
            updated_setpoints.sort(key=lambda x: (x["dayIndex"], x["time"]))
            
            # Create new schedule
            new_schedule = api.create_schedule(updated_setpoints)
            
            # Update the schedule
            await api.async_update_schedule(node_id, new_schedule)
            
            applied = f"profile '{profile}'" if profile else "custom schedule"
            _LOGGER.info(
                "Successfully updated %s schedule for node %s using %s",
                day, node_id, applied
            )
            
        except HiveAPIError as err:
            _LOGGER.error("Failed to update schedule: %s", err)
        except Exception as err:
            _LOGGER.error("Unexpected error updating schedule: %s", err)
    
    async def async_handle_refresh_token(call: ServiceCall) -> None:
        """Handle refresh_token service call."""
        try:
            api = hass.data[DOMAIN][entry.entry_id]["api"]
            tokens = await api.async_refresh_tokens()
            
            # Update config entry with new tokens
            new_data = {**entry.data}
            new_data[CONF_ID_TOKEN] = tokens["id_token"]
            new_data[CONF_ACCESS_TOKEN] = tokens["access_token"]
            new_data[CONF_REFRESH_TOKEN] = tokens["refresh_token"]
            
            hass.config_entries.async_update_entry(entry, data=new_data)
            
            _LOGGER.info("Successfully refreshed authentication tokens")
            
        except Exception as err:
            _LOGGER.error("Failed to refresh tokens: %s", err)
    
    async def async_periodic_token_refresh(now=None) -> None:
        """Refresh tokens periodically and persist to config entry."""
        try:
            tokens = await api.async_refresh_tokens()
            new_data = {**entry.data}
            new_data[CONF_ID_TOKEN] = tokens["id_token"]
            new_data[CONF_ACCESS_TOKEN] = tokens["access_token"]
            new_data[CONF_REFRESH_TOKEN] = tokens["refresh_token"]
            hass.config_entries.async_update_entry(entry, data=new_data)
            _LOGGER.info("Periodic token refresh succeeded")
        except Exception as err:
            _LOGGER.error("Periodic token refresh failed: %s", err)

    # Refresh once 60 s after load to confirm the stored token is live.
    async def _early_refresh(now=None) -> None:
        await async_periodic_token_refresh()

    async_call_later(hass, 60, _early_refresh)

    # Refresh every 45 minutes — Cognito access tokens expire after 60 minutes.
    cancel_refresh = async_track_time_interval(
        hass, async_periodic_token_refresh, timedelta(minutes=45)
    )
    hass.data[DOMAIN][entry.entry_id]["cancel_refresh"] = cancel_refresh

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DAY_SCHEDULE,
        async_handle_set_day_schedule,
        schema=SERVICE_SET_DAY_SCHEDULE_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_TOKEN,
        async_handle_refresh_token,
        schema=SERVICE_REFRESH_TOKEN_SCHEMA,
    )
    
    _LOGGER.info("Hive Schedule Manager integration loaded successfully")
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    
    # Cancel periodic token refresh
    cancel_refresh = hass.data[DOMAIN][entry.entry_id].get("cancel_refresh")
    if cancel_refresh:
        cancel_refresh()

    # Remove from hass.data
    hass.data[DOMAIN].pop(entry.entry_id)
    
    # Unregister services if this is the last entry
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SET_DAY_SCHEDULE)
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH_TOKEN)
    
    return True
