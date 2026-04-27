import os
import requests
from dotenv import load_dotenv
import threading
import logging
from datetime import datetime, timezone
import time
import sys

load_dotenv(dotenv_path=".env", verbose=True, override=True)

if not os.getenv('CI_PIPELINE'):
    load_dotenv(dotenv_path=".env", verbose=True, override=True)

project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root_path)

from core.utils import utils


class Auth:
    def __init__(self, access_token_key, auth_type, logger=None):
        """
        Initialize Auth class.

        Args:
            access_token_key (str): Prefix for env var lookup (e.g., "API").
            auth_type (str): "oauth" or "none".
            logger: Optional logger instance.
        """
        self.access_token_key = access_token_key.upper()
        self.logger = logger or logging.getLogger(__name__)
        self.auth_type = auth_type.lower()
        self.token = None
        self.expires_in = None
        self.token_issue_time = None
        self.stop_event = threading.Event()
        self.refresh_thread = None
        self.token_lock = threading.Lock()
        self.environment = os.getenv("ENVIRONMENT") or "TEST"

        if self.environment is None:
            raise ValueError("ENVIRONMENT variable is not set in your environment or .env file")

    def load_param_data(self):
        """Load configuration parameters from core/api_engine/param.json."""
        return utils.load_params(param_file_name='param.json', base_folder='core/api_engine')

    def generate_token(self):
        """
        Generate and store an access token based on the configured auth type.

        Returns:
            tuple: (access_token, expires_in) or (None, None) on failure.
        """
        with self.token_lock:
            try:
                if self.auth_type == "none":
                    return None, None
                elif self.auth_type == "oauth":
                    access_token, expires_in = self._generate_oauth_token()
                else:
                    logging.warning(f"Unsupported auth_type: {self.auth_type}")
                    return None, None

                if access_token and expires_in:
                    self.token = access_token
                    self.expires_in = expires_in
                    self.token_issue_time = datetime.now(timezone.utc)
                    logging.info("Token generated successfully")

                return access_token, expires_in

            except Exception as e:
                logging.warning(f"Warning generating token: {e}")
                return None, None

    def _generate_oauth_token(self):
        """
        Generate an OAuth token using client_credentials grant with Basic auth.

        Env vars used (resolved by access_token_key prefix, falling back to API_ prefix):
            - {KEY}_OAUTH_TOKEN_TEST  / API_OAUTH_TOKEN_TEST   — token endpoint URL
            - {KEY}_GRANT_TYPE_TOKEN_TEST / API_GRANT_TYPE_TOKEN_TEST — grant type
            - {KEY}_KEY_TOKEN_TEST / API_KEY_TOKEN_TEST — Basic auth header value

        Returns:
            tuple: (access_token, expires_in) or (None, None).
        """
        url = os.getenv(f"{self.access_token_key}_OAUTH_TOKEN_TEST") or os.getenv("API_OAUTH_TOKEN_TEST")
        grant_type = os.getenv(f"{self.access_token_key}_GRANT_TYPE_TOKEN_TEST") or os.getenv("API_GRANT_TYPE_TOKEN_TEST")
        api_key = os.getenv(f"{self.access_token_key}_KEY_TOKEN_TEST") or os.getenv("API_KEY_TOKEN_TEST")

        if not all([url, grant_type, api_key]):
            logging.error("OAuth credentials missing.")
            return None, None

        payload = f'grant_type={grant_type}'
        headers = {
            'Authorization': api_key,
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        return self._request_token(url, headers, payload)

    def _request_token(self, url, headers, payload):
        """
        Send a POST request to retrieve an access token.

        Args:
            url (str): Token endpoint URL.
            headers (dict): Request headers.
            payload (str): Form-encoded request body.

        Returns:
            tuple: (access_token, expires_in) or (None, None).
        """
        try:
            response = requests.post(url, headers=headers, data=payload)
            response.raise_for_status()

            json_response = response.json()
            access_token = json_response.get("access_token")
            expires_in = json_response.get("expires_in")

            if not access_token:
                logging.error("Access token not found in the response")
                return None, None

            logging.info(f"New token generated with expiry: {expires_in}s")
            return access_token, expires_in

        except requests.exceptions.RequestException as e:
            logging.error(f"Token request failed: {e}")
            return None, None

    def get_token_status(self):
        """
        Check the current token's validity and remaining time until expiry.

        Returns:
            tuple: (token, seconds_until_expiry, is_valid)
        """
        try:
            if not self.token_issue_time or not self.expires_in:
                return None, None, False

            elapsed = (datetime.now(timezone.utc) - self.token_issue_time).total_seconds()
            time_until_expiry = max(0, self.expires_in - elapsed)
            return self.token, time_until_expiry, True

        except Exception as e:
            logging.error(f"Error checking token status: {e}")
            return None, None, False

    def refresh_token(self):
        """
        Refresh the token if it is near expiry.

        Returns:
            tuple: (token, expires_in)
        """
        if self.auth_type == "none":
            return None, None

        with self.token_lock:
            try:
                param_data = self.load_param_data()
                threshold = param_data["auth_refresh_interval_min"] * 60

                _, time_until_expiry, status = self.get_token_status()

                if not status:
                    return self.generate_token()

                if time_until_expiry <= threshold:
                    return self.generate_token()

                return self.token, self.expires_in

            except Exception as e:
                logging.error(f"Error in refresh_token: {e}")
                return None, None

    def start_auto_refresh(self):
        """Start a background thread to automatically refresh the token before expiry."""
        if self.auth_type == "none":
            return

        param_data = self.load_param_data()
        auth_refresh_interval = param_data["auth_refresh_interval_min"] * 60
        interval_seconds = param_data["auth_think_time_min"] * 60

        def refresh_loop():
            while not self.stop_event.is_set():
                try:
                    if not self.token_issue_time or not self.expires_in:
                        time.sleep(interval_seconds)
                        continue

                    _, time_until_expiry, status = self.get_token_status()
                    if status and time_until_expiry <= auth_refresh_interval:
                        self.token, self.expires_in = self.generate_token()

                    if self.stop_event.wait(timeout=interval_seconds):
                        break

                except Exception as e:
                    logging.error(f"Error in refresh loop: {e}")
                    time.sleep(interval_seconds)

        self.refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        self.refresh_thread.start()
        logging.info("Token auto-refresh thread started")

    def stop_auto_refresh(self):
        """Stop the background auto-refresh thread."""
        if self.refresh_thread is not None:
            self.stop_event.set()
            self.refresh_thread.join()
            logging.info("Token auto-refresh thread stopped")
