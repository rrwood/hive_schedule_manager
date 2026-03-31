"""Config flow for Hive Schedule Manager integration."""
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from pycognito.exceptions import SoftwareTokenMFAChallengeException, SMSMFAChallengeException

from .const import (
    DOMAIN,
    CONF_ID_TOKEN,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    CONF_HOME_ID,
    CONF_DEVICE_KEY,
    CONF_DEVICE_GROUP_KEY,
    CONF_DEVICE_PASSWORD,
)
from .hive_api import HiveAPI, HiveAuthenticationError

_LOGGER = logging.getLogger(__name__)


class HiveScheduleManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hive Schedule Manager."""

    VERSION = 2

    def __init__(self):
        """Initialize the config flow."""
        self._email = None
        self._password = None
        self._api = None
        self._mfa_required = False

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            # Prevent duplicate entries for the same account
            await self.async_set_unique_id(self._email.lower())
            self._abort_if_unique_id_configured()

            # Initialize API
            self._api = HiveAPI(email=self._email, password=self._password)
            
            try:
                # Attempt authentication
                tokens = await self._api.async_authenticate()
                
                # Authentication successful, get home ID
                home_id = await self._get_home_id()
                
                # Create entry
                return self.async_create_entry(
                    title=f"Hive ({self._email})",
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_ID_TOKEN: tokens["id_token"],
                        CONF_ACCESS_TOKEN: tokens["access_token"],
                        CONF_REFRESH_TOKEN: tokens["refresh_token"],
                        CONF_USER_ID: tokens["user_id"],
                        CONF_HOME_ID: home_id,
                    }
                )
                
            except (SoftwareTokenMFAChallengeException, SMSMFAChallengeException):
                # MFA required, go to MFA step
                self._mfa_required = True
                return await self.async_step_mfa()
                
            except HiveAuthenticationError as err:
                _LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
                
            except Exception as err:
                _LOGGER.exception("Unexpected error during authentication: %s", err)
                errors["base"] = "unknown"

        # Show form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
            description_placeholders={
                "note": "Enter your Hive account credentials (same as Hive app)"
            }
        )

    async def async_step_mfa(self, user_input=None):
        """Handle MFA verification step."""
        errors = {}

        if user_input is not None:
            mfa_code = user_input.get("mfa_code")
            
            try:
                # Complete MFA authentication
                tokens = await self._api.async_authenticate(mfa_code=mfa_code)

                # Get home ID
                home_id = await self._get_home_id()

                # Build entry data — include device credentials if ConfirmDevice succeeded
                entry_data = {
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_ID_TOKEN: tokens["id_token"],
                    CONF_ACCESS_TOKEN: tokens["access_token"],
                    CONF_REFRESH_TOKEN: tokens["refresh_token"],
                    CONF_USER_ID: tokens["user_id"],
                    CONF_HOME_ID: home_id,
                }
                if tokens.get("device_key"):
                    entry_data[CONF_DEVICE_KEY] = tokens["device_key"]
                if tokens.get("device_group_key"):
                    entry_data[CONF_DEVICE_GROUP_KEY] = tokens["device_group_key"]
                if tokens.get("device_password"):
                    entry_data[CONF_DEVICE_PASSWORD] = tokens["device_password"]

                return self.async_create_entry(
                    title=f"Hive ({self._email})",
                    data=entry_data,
                )
                
            except HiveAuthenticationError as err:
                _LOGGER.error("MFA verification failed: %s", err)
                errors["base"] = "invalid_mfa"
                
            except Exception as err:
                _LOGGER.exception("Unexpected error during MFA: %s", err)
                errors["base"] = "unknown"

        # Show MFA form
        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({
                vol.Required("mfa_code"): str,
            }),
            errors=errors,
            description_placeholders={
                "note": "Enter the code sent to your phone via SMS"
            }
        )

    async def _get_home_id(self) -> str:
        """Get the user's home ID by fetching all nodes and extracting homeId."""
        try:
            nodes = await self._api.async_get_nodes("")
            for node in nodes:
                home_id = node.get("homeId")
                if home_id:
                    _LOGGER.info("Discovered home ID: %s", home_id)
                    return home_id
            _LOGGER.warning("Could not automatically determine home ID from %d nodes", len(nodes))
            return ""
        except Exception as err:
            _LOGGER.error("Error getting home ID: %s", err)
            return ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Hive Schedule Manager."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options or {}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_HOME_ID,
                    default=opts.get(CONF_HOME_ID) or self.config_entry.data.get(CONF_HOME_ID, ""),
                ): str,
                vol.Optional(
                    CONF_DEVICE_KEY,
                    default=opts.get(CONF_DEVICE_KEY) or self.config_entry.data.get(CONF_DEVICE_KEY, ""),
                ): str,
                vol.Optional(
                    CONF_DEVICE_GROUP_KEY,
                    default=opts.get(CONF_DEVICE_GROUP_KEY) or self.config_entry.data.get(CONF_DEVICE_GROUP_KEY, ""),
                ): str,
                vol.Optional(
                    CONF_DEVICE_PASSWORD,
                    default=opts.get(CONF_DEVICE_PASSWORD) or self.config_entry.data.get(CONF_DEVICE_PASSWORD, ""),
                ): str,
                vol.Optional(
                    CONF_REFRESH_TOKEN,
                    default=opts.get(CONF_REFRESH_TOKEN, ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)),
            }),
            description_placeholders={
                "note": (
                    "These fields are for emergency use only. Under normal operation all values "
                    "are set automatically during the setup flow and do not need to be changed. "
                    "Use these only if automatic token refresh has stopped working and you need "
                    "to inject credentials manually (e.g. from an iOS MMKV backup)."
                )
            },
        )
