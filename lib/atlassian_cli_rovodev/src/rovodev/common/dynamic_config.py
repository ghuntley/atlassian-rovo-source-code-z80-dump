"""Per User Dynamic Configuration."""

import dataclasses
import random
import threading
import time

import requests
from loguru import logger


@dataclasses.dataclass(frozen=True)
class DynamicConfigData:
    model_id: list[str] = dataclasses.field(default_factory=list)
    is_internal: bool = False
    enable_efficient_agent: bool = False
    banned: bool = False


class DynamicConfiguration:

    def __init__(self, user_id: str, interval: int = 60):
        self._user_id = user_id # Kept for now, but Statsig is removed
        # self._interval = interval # Not needed as refresh is disabled
        # self._config = self._get_config() # Statsig call removed
        # self._lock = threading.Lock() # Not needed for static config
        # thread = threading.Thread(target=self._refresh_config, daemon=True) # Refresh thread removed
        # thread.start()
        logger.info("DynamicConfiguration: Statsig integration has been removed. Returning static default config.")

    def config(self) -> DynamicConfigData:
        # Return a static, default configuration as Statsig has been removed.
        # The is_internal flag is now effectively controlled by IS_INTERNAL_USER in __init__.py
        # For the purpose of this class, if it were to be used independently,
        # it would need its own generic way to determine this.
        # Here, we default to False as the Atlassian-specific check is removed.
        return DynamicConfigData(
            model_id=[ # Default model list
                "anthropic:claude-sonnet-4@20250514",
                "bedrock:anthropic.claude-3-7-sonnet-20250219-v1:0",
                "anthropic:claude-3-5-sonnet-v2@20241022",
                "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0",
            ],
            is_internal=False, # Was: self._user_id.endswith("@atlassian.com")
            enable_efficient_agent=False, # Defaulting to False
            banned=False # Defaulting to False
        )

    def _refresh_config(self):
        # This is now a no-op as Statsig integration is removed.
        # while True:
        #     time.sleep(self._interval)
        #     config = self._get_config()
        #     with self._lock:
        #         self._config = config
        pass

    def _get_config(
        self,
        url: str = "", # Was: "https://api.statsig.com/v1/get_config",
        api_key: str = "", # Was: "client-K86FOx7CB7wxvmrFeFOrGj7iRG2t7pC0EjBd5VUwi9Q",
        config_name: str = "", # Was: "rovo_dev_cli_client_config",
        max_retries: int = 0, # Was: 5
        base_delay: float = 1.0, # Unused
        max_delay: float = 10.0,
    ) -> dict | None:
        headers = {"statsig-api-key": api_key, "Content-Type": "application/json"}
        payload = {"user": {"userID": self._user_id}, "configName": config_name}

        attempt = 0

        while attempt <= max_retries:
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code not in [429, 500, 502, 503, 504]:
                    response.raise_for_status()  # non-retryable error
            except requests.exceptions.RequestException as e:
                pass

            delay = min(max_delay, base_delay * (2**attempt)) + random.uniform(0, 1)
            time.sleep(delay)
            attempt += 1

        logger.error("Failed to retrieve dynamic user config after multiple retries.")


# DO_NOT_REMOVE: Manual test.
if __name__ == "__main__":
    dc = DynamicConfiguration("foo@bar.com", interval=4)
    while True:
        print(dc.config())
        time.sleep(5)
