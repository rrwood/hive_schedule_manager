"""Hive API client with AWS Cognito authentication."""
import asyncio
import base64
import hashlib
import logging
import os
from typing import Dict, List, Optional
import requests
import jwt
from pycognito import Cognito
from pycognito.exceptions import SoftwareTokenMFAChallengeException, SMSMFAChallengeException

from .const import (
    API_BASE_URL,
    API_KEY,
    API_VERSION,
    API_CLIENT,
    API_USER_AGENT,
    COGNITO_USER_POOL_ID,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
)

_LOGGER = logging.getLogger(__name__)

def _make_cognito_client():
    """Return a boto3 cognito-idp client that sends AWS Amplify-matching headers.

    The Hive iOS app uses AWS Amplify 5.0.4. Sending matching x-amz-user-agent
    and User-Agent headers may be required for ConfirmDevice and device SRP calls
    to succeed against Hive's Cognito pool configuration.
    """
    import boto3
    client = boto3.client("cognito-idp", region_name=COGNITO_REGION)

    def _inject_amplify_headers(request, **kwargs):
        request.headers["x-amz-user-agent"] = "aws-amplify/5.0.4"
        request.headers["User-Agent"] = "Hive/13 CFNetwork/3826.600.41.2.1 Darwin/24.6.0"

    client.meta.events.register("before-send.cognito-idp.*", _inject_amplify_headers)
    return client


# RFC 3526 / Cognito 2048-bit SRP prime (same N used for user SRP auth)
_SRP_N = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64"
    "ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6B"
    "F12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB31"
    "43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF",
    16,
)
_SRP_g = 2


def _pad_unsigned(b: bytes) -> bytes:
    """Prepend 0x00 if the high bit is set so Cognito reads the value as positive."""
    return (b"\x00" + b) if b[0] & 0x80 else b


def _compute_device_verifier(
    device_group_key: str, device_key: str, device_password: str
) -> tuple[str, str]:
    """Compute Cognito device SRP verifier.

    Returns:
        (salt_b64, verifier_b64) both standard base64-encoded.

    The algorithm mirrors what the Hive iOS app (AWS Amplify 5) sends in
    ConfirmDevice.DeviceSecretVerifierConfig.

    inner = SHA256(device_group_key + device_key + ":" + device_password)
    x     = SHA256(salt_bytes + inner)
    v     = g^x mod N

    Both salt and verifier must represent positive big-endian integers.
    Cognito's Java backend uses BigInteger to decode them — if the high bit is
    set the value is treated as negative and the call is rejected.
    Prepend 0x00 when needed (the iPhone's Amplify SDK does this too; a
    specific test sample happened to have a salt with high bit clear, which
    is why it appeared as raw bytes — but it IS BigInteger-encoded).
    """
    salt_bytes = os.urandom(16)
    inner = hashlib.sha256(
        (device_group_key + device_key + ":" + device_password).encode("utf-8")
    ).digest()
    x_bytes = hashlib.sha256(salt_bytes + inner).digest()
    x = int.from_bytes(x_bytes, "big")
    verifier = pow(_SRP_g, x, _SRP_N)
    verifier_bytes = verifier.to_bytes((verifier.bit_length() + 7) // 8, "big")
    return (
        base64.b64encode(_pad_unsigned(salt_bytes)).decode(),
        base64.b64encode(_pad_unsigned(verifier_bytes)).decode(),
    )


class HiveAPIError(Exception):
    """Base exception for Hive API errors."""


class HiveAuthenticationError(HiveAPIError):
    """Authentication error."""


class HiveAPI:
    """Hive API client."""

    def __init__(
        self,
        email: str,
        password: Optional[str] = None,
        id_token: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        user_id: Optional[str] = None,
        device_key: Optional[str] = None,
        device_group_key: Optional[str] = None,
        device_password: Optional[str] = None,
    ):
        """Initialize the Hive API client."""
        self.email = email
        self.password = password
        self.id_token = id_token
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_id = user_id
        self.home_id = None
        self._cognito = None
        self._mfa_challenge = None
        self._device_key = device_key
        self._device_group_key = device_group_key
        self._device_password = device_password
        self._device_confirmed = bool(device_key and device_group_key and device_password)

    def _get_cognito(self) -> Cognito:
        """Get or create Cognito instance (blocking — must be called in executor)."""
        if self._cognito is None:
            self._cognito = Cognito(
                user_pool_id=COGNITO_USER_POOL_ID,
                client_id=COGNITO_CLIENT_ID,
                username=self.email,
                user_pool_region=COGNITO_REGION,
                id_token=self.id_token,
                access_token=self.access_token,
                refresh_token=self.refresh_token,
            )
        return self._cognito

    def _sync_confirm_and_remember_device(
        self, access_token: str, device_key: str, device_group_key: str
    ) -> None:
        """Confirm a newly-issued device and mark it as remembered.

        Called immediately after RespondToAuthChallenge(SMS_MFA) returns
        NewDeviceMetadata.  Generates a fresh device_password, computes the SRP
        verifier, calls ConfirmDevice, then UpdateDeviceStatus("remembered").

        On success, updates self._device_key / _device_group_key / _device_password
        so the caller can persist them for future REFRESH_TOKEN_AUTH sessions.
        """
        device_password = base64.b64encode(os.urandom(40)).decode()
        salt_b64, verifier_b64 = _compute_device_verifier(
            device_group_key, device_key, device_password
        )
        client = _make_cognito_client()

        try:
            client.confirm_device(
                AccessToken=access_token,
                DeviceKey=device_key,
                DeviceName="Home Assistant",
                DeviceSecretVerifierConfig={
                    "Salt": salt_b64,
                    "PasswordVerifier": verifier_b64,
                },
            )
            _LOGGER.info("ConfirmDevice succeeded for device_key=%s", device_key)
        except Exception as err:
            _LOGGER.error("ConfirmDevice failed: %s — device tracking unavailable", err)
            return

        try:
            client.update_device_status(
                AccessToken=access_token,
                DeviceKey=device_key,
                DeviceRememberedStatus="remembered",
            )
            _LOGGER.info("UpdateDeviceStatus(remembered) succeeded for device_key=%s", device_key)
        except Exception as err:
            _LOGGER.warning("UpdateDeviceStatus failed (%s)", err)

        # Persist the new device credentials so REFRESH_TOKEN_AUTH can use them
        self._device_key = device_key
        self._device_group_key = device_group_key
        self._device_password = device_password
        self._device_confirmed = True

    def _sync_try_remember_existing_device(self, access_token: str) -> None:
        """Re-mark an existing (Options-configured) device as remembered in Cognito.

        Called after SMS MFA auth using the fresh access_token. If the user has
        previously configured iOS device credentials in Options, this call re-activates
        that device so the next USER_SRP_AUTH + DEVICE_KEY will return DEVICE_SRP_AUTH
        instead of SMS_MFA — eliminating the need for another SMS code.
        """
        if not (self._device_key and self._device_group_key and self._device_password):
            return
        try:
            client = _make_cognito_client()
            client.update_device_status(
                AccessToken=access_token,
                DeviceKey=self._device_key,
                DeviceRememberedStatus="remembered",
            )
            _LOGGER.info(
                "UpdateDeviceStatus(remembered) succeeded for existing device key=%s — "
                "next re-auth will use DEVICE_SRP_AUTH (no SMS MFA)",
                self._device_key,
            )
        except Exception as err:
            _LOGGER.warning("UpdateDeviceStatus on existing device failed (%s)", err)

    def _sync_authenticate(self, mfa_code: Optional[str] = None) -> Dict[str, str]:
        """Blocking authentication — run in executor."""
        if mfa_code and self._mfa_challenge:
            # Handle SMS_MFA code submission.
            # iPhone's Amplify SDK does NOT send ClientMetadata in the SMS_MFA step.
            # The iPhone uses the UUID (from ChallengeParameters["USERNAME"] of the
            # PASSWORD_VERIFIER response) as USERNAME here — NOT the email address.
            # Using email instead may prevent Cognito from creating a device record.
            # Use the UUID stashed from process_challenge() — matches what iOS sends as USERNAME
            # in SMS_MFA (Cognito's internal UUID, not the user's email address).
            _srp_username = self._mfa_challenge.get("_srp_username", self.email)
            _amplify_client = _make_cognito_client()
            response = _amplify_client.respond_to_auth_challenge(
                ClientId=COGNITO_CLIENT_ID,
                ChallengeName="SMS_MFA",
                Session=self._mfa_challenge["Session"],
                ChallengeResponses={
                    "SMS_MFA_CODE": mfa_code,
                    "USERNAME": _srp_username,
                },
            )
            auth_result = response["AuthenticationResult"]
            self.id_token = auth_result["IdToken"]
            self.access_token = auth_result["AccessToken"]
            self.refresh_token = auth_result["RefreshToken"]
            self._mfa_challenge = None

            # ConfirmDevice must be called IMMEDIATELY after receiving NewDeviceMetadata
            # from the SMS_MFA response — the device key is only confirmable in the same
            # auth session. Calling it later (even minutes after) returns
            # "Invalid device key given". Once confirmed + remembered the resulting
            # refresh token supports REFRESH_TOKEN_AUTH + DEVICE_KEY indefinitely.
            new_device = auth_result.get("NewDeviceMetadata")
            if new_device:
                self._sync_confirm_and_remember_device(
                    self.access_token,
                    new_device["DeviceKey"],
                    new_device["DeviceGroupKey"],
                )
            else:
                # No new device issued — fall back to re-marking the existing device
                # (Options-configured iOS credentials) so REFRESH_TOKEN_AUTH keeps working.
                self._sync_try_remember_existing_device(self.access_token)
        else:
            # Use pycognito's AWSSRP class for SRP math but call InitiateAuth and
            # RespondToAuthChallenge(PASSWORD_VERIFIER) directly via boto3 so we
            # control each request body exactly.  Specifically, we include
            # ClientMetadata: {} in InitiateAuth (exactly as the Hive iOS app via
            # AWS Amplify 5 does) and omit it from PASSWORD_VERIFIER (also matching
            # the iPhone).  pycognito.authenticate() never adds ClientMetadata to
            # initiate_auth() regardless of what client_metadata is passed.
            from pycognito.aws_srp import AWSSRP
            _srp_client = _make_cognito_client()
            srp = AWSSRP(
                username=self.email,
                password=self.password,
                pool_id=COGNITO_USER_POOL_ID,
                client_id=COGNITO_CLIENT_ID,
                client=_srp_client,
            )
            auth_params = srp.get_auth_params()

            # Step 1: InitiateAuth — ClientMetadata: {} required for Hive's
            # Lambda Pre-Authentication trigger to enable device tracking.
            initiate_resp = _srp_client.initiate_auth(
                AuthFlow="USER_SRP_AUTH",
                AuthParameters=auth_params,
                ClientId=COGNITO_CLIENT_ID,
                ClientMetadata={},
            )
            if initiate_resp.get("ChallengeName") != "PASSWORD_VERIFIER":
                raise HiveAuthenticationError(
                    f"Unexpected InitiateAuth challenge: {initiate_resp.get('ChallengeName')}"
                )

            # Step 2: RespondToAuthChallenge (PASSWORD_VERIFIER) — no ClientMetadata
            challenge_responses = srp.process_challenge(
                initiate_resp["ChallengeParameters"], auth_params
            )
            verifier_resp = _srp_client.respond_to_auth_challenge(
                ClientId=COGNITO_CLIENT_ID,
                ChallengeName="PASSWORD_VERIFIER",
                ChallengeResponses=challenge_responses,
            )

            if verifier_resp.get("ChallengeName") == "SMS_MFA":
                # Stash the UUID resolved by Cognito's SRP exchange so we can pass it
                # as USERNAME in the SMS_MFA ChallengeResponses (matching what iOS does).
                # The UUID is in challenge_responses["USERNAME"] (set by process_challenge
                # from the PASSWORD_VERIFIER ChallengeParameters["USERNAME"] field).
                # Using the email here prevents Cognito from creating the pending device
                # record, causing ConfirmDevice to always fail with "Invalid device key".
                verifier_resp["_srp_username"] = challenge_responses.get("USERNAME", self.email)
                self._mfa_challenge = verifier_resp
                raise SMSMFAChallengeException("Do SMS MFA", verifier_resp)

            # No MFA required (shouldn't happen for this pool)
            _auth = verifier_resp.get("AuthenticationResult", {})
            self.id_token = _auth.get("IdToken")
            self.access_token = _auth.get("AccessToken")
            self.refresh_token = _auth.get("RefreshToken")

        decoded = jwt.decode(self.id_token, options={"verify_signature": False})
        self.user_id = decoded.get("cognito:username")

        return {
            "id_token": self.id_token,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
            "device_key": self._device_key,
            "device_group_key": self._device_group_key,
            "device_password": self._device_password,
        }

    async def async_authenticate(self, mfa_code: Optional[str] = None) -> Dict[str, str]:
        """Authenticate with AWS Cognito.

        Raises:
            HiveAuthenticationError: If authentication fails
            SMSMFAChallengeException: If MFA code is required
        """
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._sync_authenticate, mfa_code)
            _LOGGER.info("Successfully authenticated with Hive API")
            return result
        except (SoftwareTokenMFAChallengeException, SMSMFAChallengeException):
            _LOGGER.info("MFA code required")
            raise
        except Exception as err:
            _LOGGER.error("Authentication failed: %s", err)
            raise HiveAuthenticationError(f"Authentication failed: {err}")

    def _sync_refresh_tokens(self) -> Dict[str, str]:
        """Blocking token refresh via REFRESH_TOKEN_AUTH."""
        client = _make_cognito_client()

        auth_params = {"REFRESH_TOKEN": self.refresh_token}
        if self._device_key:
            auth_params["DEVICE_KEY"] = self._device_key

        response = client.initiate_auth(
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters=auth_params,
            ClientId=COGNITO_CLIENT_ID,
        )

        auth_result = response["AuthenticationResult"]
        self.id_token = auth_result["IdToken"]
        self.access_token = auth_result["AccessToken"]
        # AWS does not rotate the refresh token — keep the existing one
        self._cognito = None
        return {
            "id_token": self.id_token,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
        }

    async def async_refresh_tokens(self) -> Dict[str, str]:
        """Refresh authentication tokens via REFRESH_TOKEN_AUTH.

        Raises:
            HiveAuthenticationError: If token refresh fails
        """
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._sync_refresh_tokens)
            _LOGGER.info("Tokens refreshed successfully")
            return result
        except Exception as err:
            _LOGGER.error("Token refresh failed: %s", err)
            raise HiveAuthenticationError(f"Token refresh failed: {err}")

    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers."""
        return {
            "Authorization": f"Bearer {self.id_token}",
            "Content-Type": "application/json",
            "Accept": API_VERSION,
            "X-API-Key": API_KEY,
            "X-Omnia-Client": API_CLIENT,
            "User-Agent": API_USER_AGENT,
        }

    def _sync_refresh_if_needed(self) -> None:
        """Refresh access token via REFRESH_TOKEN_AUTH — call before retrying a 401."""
        tokens = self._sync_refresh_tokens()
        self.id_token = tokens["id_token"]
        self.access_token = tokens["access_token"]
        _LOGGER.info("Tokens refreshed after 401")

    def _sync_get_nodes(self, home_id: str) -> List[Dict]:
        """Blocking get nodes — run in executor."""
        url = f"{API_BASE_URL}/omnia/nodes/"
        params = {"homeId": home_id} if home_id else {}
        response = requests.get(url, params=params, headers=self._get_headers(), timeout=30)
        if response.status_code == 401:
            self._sync_refresh_if_needed()
            response = requests.get(url, params=params, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json().get("nodes", [])

    async def async_get_nodes(self, home_id: str) -> List[Dict]:
        """Get all nodes for a home."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._sync_get_nodes, home_id)
        except Exception as err:
            _LOGGER.error("Failed to get nodes: %s", err)
            raise HiveAPIError(f"Failed to get nodes: {err}")

    def _sync_get_node(self, node_id: str) -> Optional[Dict]:
        """Fetch a single node with full feature data using API version 6.5.0."""
        url = f"{API_BASE_URL}/omnia/nodes/{node_id}"
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        if response.status_code == 401:
            self._sync_refresh_if_needed()
            response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        nodes = response.json().get("nodes", [])
        return nodes[0] if nodes else None

    async def async_get_thermostat_node(self, home_id: str, node_id: str) -> Optional[Dict]:
        """Get a specific thermostat node with full feature data."""
        try:
            loop = asyncio.get_running_loop()
            node = await loop.run_in_executor(None, self._sync_get_node, node_id)
            if node:
                # Store home_id if we don't have it yet
                if not self.home_id and node.get("homeId"):
                    self.home_id = node["homeId"]
                return node
            _LOGGER.error("Node %s not found via direct fetch", node_id)
            return None
        except Exception as err:
            _LOGGER.error("Failed to fetch node %s: %s", node_id, err)
            return None

    async def async_get_schedule(self, home_id: str, node_id: str) -> Optional[Dict]:
        """Get heating schedule for a thermostat."""
        node = await self.async_get_thermostat_node(home_id, node_id)
        if not node:
            return None
        try:
            return node["features"]["heating_thermostat_v1"]["heatSchedule"]["reportedValue"]
        except KeyError:
            _LOGGER.error("Schedule key path not found for node %s", node_id)
            return None

    def _sync_update_schedule(self, node_id: str, schedule: Dict) -> bool:
        """Blocking update schedule — run in executor."""
        url = f"{API_BASE_URL}/omnia/nodes/{node_id}"
        payload = {
            "nodes": [{
                "features": {
                    "heating_thermostat_v1": {
                        "heatSchedule": {
                            "targetValue": schedule
                        }
                    }
                }
            }]
        }
        response = requests.put(url, headers=self._get_headers(), json=payload, timeout=30)
        if response.status_code == 401:
            self._sync_refresh_if_needed()
            response = requests.put(url, headers=self._get_headers(), json=payload, timeout=30)
        if response.status_code == 405:
            # Some versions require PUT to the specific feature endpoint
            url = f"{API_BASE_URL}/omnia/nodes/{node_id}/features/heating_thermostat_v1"
            payload = {"heatSchedule": {"targetValue": schedule}}
            response = requests.put(url, headers=self._get_headers(), json=payload, timeout=30)
            if response.status_code == 401:
                self._sync_refresh_if_needed()
                response = requests.put(url, headers=self._get_headers(), json=payload, timeout=30)
        response.raise_for_status()
        return True

    async def async_update_schedule(self, node_id: str, schedule: Dict) -> bool:
        """Update heating schedule."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_update_schedule, node_id, schedule)
            _LOGGER.info("Successfully updated schedule for node %s", node_id)
            return True
        except Exception as err:
            _LOGGER.error("Failed to update schedule: %s", err)
            raise HiveAPIError(f"Failed to update schedule: {err}")

    def create_setpoint(self, day_index: int, time: str, temperature: float) -> Dict:
        """Create a schedule setpoint.
        
        Args:
            day_index: Day of week (1=Monday, 7=Sunday)
            time: Time in HH:MM format
            temperature: Temperature in Celsius
            
        Returns:
            Setpoint dictionary
        """
        return {
            "dayIndex": day_index,
            "offset": 0,
            "time": time,
            "actions": [{
                "actionType": "http://alertme.com/schema/json/configuration/configuration.device.action.generic.v1.json#",
                "featureType": "http://alertme.com/schema/json/feature/node.feature.heating_thermostat.v1.json#",
                "attribute": "targetHeatTemperature",
                "value": str(temperature),
            }]
        }

    def create_schedule(self, setpoints: List[Dict]) -> Dict:
        """Create a complete schedule.
        
        Args:
            setpoints: List of setpoint dictionaries
            
        Returns:
            Complete schedule dictionary
        """
        return {
            "scheduleType": "http://alertme.com/schema/json/configuration/configuration.device.schedule.weekly.v1.json#",
            "maxNumSetpointsPerDay": 6.0,
            "setpoints": setpoints,
        }
