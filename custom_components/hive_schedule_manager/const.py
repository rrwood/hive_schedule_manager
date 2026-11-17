"""Constants for the Hive Schedule Manager integration."""

DOMAIN = "hive_schedule_manager"

# AWS Cognito Configuration
COGNITO_USER_POOL_ID = "eu-west-1_SamNfoWtf"
COGNITO_CLIENT_ID = "3rl4i0ajrmtdm8sbre54p9dvd9"
COGNITO_REGION = "eu-west-1"

# Hive API Configuration
API_BASE_URL = "https://api-prod.bgchprod.info"
API_KEY = "7Y1kj281ay64CAik9YTcnaFNqdiSPksW5XP2GZ4T"
API_VERSION = "application/vnd.alertme.zoo-6.5.0+json"
API_CLIENT = "14.04.2 build 5"
API_USER_AGENT = "Hive/14.04.2 iOS/26.2.1 Apple"

# Configuration keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_ID_TOKEN = "id_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_USER_ID = "user_id"
CONF_HOME_ID = "home_id"
CONF_DEVICE_KEY = "device_key"
CONF_DEVICE_GROUP_KEY = "device_group_key"
CONF_DEVICE_PASSWORD = "device_password"

# Service names
SERVICE_SET_DAY_SCHEDULE = "set_day_schedule"
SERVICE_REFRESH_TOKEN = "refresh_token"

# Schedule profiles file (read at runtime, seeded from DEFAULT_PROFILES if missing)
PROFILES_FILE = "hive_schedule_profiles.yaml"

# Days of week mapping
DAYS_OF_WEEK = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 7,
}

# Default schedule profiles
DEFAULT_PROFILES = {
    "workday": [
        {"time": "05:20", "temp": 19.0},
        {"time": "07:30", "temp": 18.5},
        {"time": "16:30", "temp": 19.5},
        {"time": "21:45", "temp": 16.0},
    ],
    "weekend": [
        {"time": "07:30", "temp": 18.5},
        {"time": "09:00", "temp": 18.0},
        {"time": "16:00", "temp": 19.5},
        {"time": "22:00", "temp": 16.0},
    ],
    "nonworkday": [
        {"time": "06:30", "temp": 18.5},
        {"time": "08:00", "temp": 18.0},
        {"time": "16:30", "temp": 19.5},
        {"time": "22:00", "temp": 16.0},
    ],
    "holiday": [
        {"time": "00:00", "temp": 15.0},
    ],
    "all_day_comfort": [
        {"time": "00:00", "temp": 19.0},
    ],
    "wfh": [
        {"time": "06:00", "temp": 19.0},
        {"time": "09:00", "temp": 18.5},
        {"time": "12:00", "temp": 19.0},
        {"time": "17:00", "temp": 19.5},
        {"time": "22:00", "temp": 16.0},
    ],
    "custom1": [
        {"time": "05:30", "temp": 17.0},
        {"time": "08:00", "temp": 16.5},
        {"time": "12:00", "temp": 18.0},
        {"time": "17:00", "temp": 19.0},
        {"time": "22:30", "temp": 16.0},
    ],
    "custom2": [
        {"time": "06:00", "temp": 18.0},
        {"time": "09:00", "temp": 17.5},
        {"time": "13:00", "temp": 18.5},
        {"time": "18:00", "temp": 19.5},
        {"time": "23:00", "temp": 16.5},
    ],
}
