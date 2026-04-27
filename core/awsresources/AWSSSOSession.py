import os
import sys
import boto3
import json
from botocore.config import Config
from datetime import datetime, timedelta, timezone
import time
from os.path import expanduser
import configparser
import logging
import threading
from dotenv import load_dotenv

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root_path)

# Import custom modules
from utils import utils
#from utils.config import aws_account, role_arn, region, profile_name

# Automatically reload environment variables when .env file changes
load_dotenv(dotenv_path=".env", verbose=True, override=True)

if not os.getenv('CI_PIPELINE'):  # GitLab CI/CD sets the CI environment variable
    print("Local environment detected. Loading variables from .env file...")
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
else:
    print("CI/CD environment detected. Using CI/CD provided variables...")

# Get the environment from the variable (from .env for local or directly from CI/CD)
environment = os.getenv("ENVIRONMENT")

if environment:
    print(f"Using environment-specific variables for: {environment}")
else:
    print("No specific environment set, assuming CI/CD environment variables are provided...")

profile_name = os.getenv(f"{environment.upper()}_PROFILE_NAME")

class AWSSSOSession:
    def __init__(self, profile_name):
        """
        Initialize the AWS SSO session manager.

        Args:
            profile_name (str): The AWS CLI profile name used to create the SSO session.

        Attributes:
            profile_name (str): AWS profile used for session.
            session (boto3.Session): Active session created using the profile.
            expiry_time (datetime): Expiration time of the session credentials.
            stop_event (threading.Event): Event used to stop the auto-refresh thread.
            refresh_thread (threading.Thread): Background thread for refreshing the session.
        """
        self.profile_name = profile_name
        self.session = self.create_session()
        self.expiry_time = self.get_expiry_time()
        self.stop_event = threading.Event()
        self.refresh_thread = None

    def create_session(self):
        """
        Create a new AWS session using the provided profile name.

        Returns:
            boto3.Session: A boto3 session configured with the specified AWS profile.

        Raises:
            Exception: If session creation fails, the exception is logged and re-raised.
        """
        try:
            session = boto3.Session(profile_name=self.profile_name)
            return session
        except Exception as e:
            logging.info(f"Error creating AWS session: {e}")
            raise

    def get_expiry_time(self):
        """
        Get the expiry time of the current AWS session.

        Returns:
            datetime: A placeholder expiry time set to 1 hour from the current time.

        Notes:
            - boto3 does not provide direct access to session expiry for standard sessions.
            - This method currently assumes a fixed session duration of 1 hour.
            - In production, this should be replaced with actual expiry tracking for SSO or assumed roles.
        """
        credentials = self.session.get_credentials().get_frozen_credentials()
        # Note: boto3 does not expose session expiry directly, so this is a placeholder.
        # In a real scenario, you would handle this differently.
        return datetime.now(timezone.utc) + timedelta(hours=1)  # Placeholder expiry time

    def get_actual_expiry_time(self):
        """
        Retrieve the actual session expiry time from the cached AWS SSO token.

        Returns:
            datetime: The expiration time of the SSO session token if found;
                    otherwise, returns a fallback time set to 1 hour from now.

        Behavior:
            - Reads the cached SSO token files from ~/.aws/sso/cache/.
            - Searches for a file containing an accessToken and matching profile name.
            - Parses and returns the 'expiresAt' timestamp from the token cache.

        Notes:
            - This method is specific to AWS SSO authentication.
            - If the token file can't be found or parsed, a default expiry time is returned.
            - Ensures robust session handling by falling back gracefully on failure.
        """
        try:
            cache_dir = os.path.expanduser("~/.aws/sso/cache/")
            cache_files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir)]
            for cache_file in cache_files:
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                    if 'accessToken' in cache_data and cache_data.get('profile') == self.profile_name:
                        expiry_time_str = cache_data['expiresAt']
                        expiry_time = datetime.strptime(expiry_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        return expiry_time
        except Exception as e:
            logging.info(f"Error fetching actual session expiry time: {e}")
        return datetime.now(timezone.utc) + timedelta(hours=1)  # Fallback placeholder

    def refresh_session(self):
        """
        Refresh the AWS SSO session.

        Behavior:
            - Re-creates the boto3 session using the current profile name.
            - Updates the internal session object and its expiry time.
            - Logs the refresh activity for visibility.

        Notes:
            - Used to extend the session before expiry in long-running operations.
            - Relies on the local SSO token cache to authenticate again.
        """
        logging.info(f"Refreshing session for profile: {self.profile_name}")
        self.session = self.create_session()
        self.expiry_time = self.get_expiry_time()
        logging.info(f"Refreshing session expiry_time: {self.expiry_time}")

    def get_credentials(self):
        """Get the AWS credentials for the session."""
        return self.session.get_credentials()

    def get_session(self):
        """Get the boto3 session."""
        return self.session

    def get_sso_session(self, profile_name):
        """Utility function to get an AWS SSO session."""
        return AWSSSOSession(profile_name)

    def start_auto_refresh(self):
        """
        Start a background thread that automatically refreshes the AWS session
        10 minutes before it expires.

        Behavior:
            - Spawns a daemon thread that waits until 10 minutes before session expiry.
            - Calls `refresh_session()` to renew the AWS session.
            - Continues this loop until `stop_event` is set.

        Notes:
            - Ensures long-running scripts or applications maintain valid AWS credentials.
            - Thread is marked as daemon, so it won't block program exit.
            - Uses a `threading.Event` (`stop_event`) to gracefully terminate the loop.
        """
        def refresh_loop():
            while not self.stop_event.is_set():
                time_to_refresh = self.expiry_time - timedelta(minutes=10)
                time_to_wait = (time_to_refresh - datetime.now(timezone.utc)).total_seconds()
                if time_to_wait > 0:
                    if self.stop_event.wait(timeout=time_to_wait):
                        break  # Exit loop if stop_event is set
                self.refresh_session()
        
        self.refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        self.refresh_thread.start()

    def stop_auto_refresh(self):  
        """
    Stop the background auto-refresh thread that keeps the AWS session active.

    Behavior:
        - Signals the refresh loop to terminate using the `stop_event`.
        - Waits for the refresh thread to exit cleanly using `join()`.
        - Logs the shutdown status.

    Notes:
        - Should be called during graceful shutdown or cleanup to avoid dangling threads.
        - Has no effect if the auto-refresh thread was never started.
    """
        if self.refresh_thread is not None:
            self.stop_event.set()
            self.refresh_thread.join()  # Wait for the thread to finish
            logging.info("Auto-refresh thread stopped.")

def main():   
    """
    Main function to test AWS SSO session management for a specific profile.

    This method initializes an `AWSSSOSession` object for the given profile and runs 
    several key operations to verify the session lifecycle and credential validity.

    Key operations performed:
    - Creates an AWS session for the provided profile.
    - Fetches the initial session expiry time and logs it.
    - Retrieves and logs the current AWS credentials.
    - Simulates a wait (sleep) to represent elapsed time.
    - Refreshes the session explicitly and checks that updated credentials and expiry time are valid.
    - Collects and logs status of the entire session lifecycle testing process.

    Logs are generated at each stage for visibility and traceability.
    Any failure is logged and captured in a structured `results` object.

    Output:
        - Logs the status of each step to help debug or verify correctness.
        - Prints structured JSON to indicate success or failure.

    Notes:
        - The `profile_name` variable must be defined in the outer scope or passed to this method.
        - `AWSSSOSession` is assumed to be a custom session wrapper class with methods:
            - `get_session()`
            - `get_expiry_time()`
            - `get_credentials()`
            - `refresh_session()`
    """
    # Prepare status tracking
    results = {
        "status": "passed",
        "message": "All files processed successfully.",
        "failures": []
    }

    logging.info(f"\nTesting AWS session for profile: {profile_name}")
    session_handler = AWSSSOSession(profile_name)

    try:
        # Test session creation
        session = session_handler.get_session()
        logging.info(f"Session created successfully for profile: {profile_name}")

        # Test getting expiry time
        expiry_time = session_handler.get_expiry_time()
        logging.info(f"Session expiry time for profile {profile_name}: {expiry_time}")

        # Test credentials retrieval
        credentials = session_handler.get_credentials()
        logging.info(f"Credentials for profile {profile_name}: {credentials}")

        # Simulate session refresh after some time
        time.sleep(60)  # Simulating wait
        session_handler.refresh_session()
        logging.info(f"Session refreshed successfully for profile: {profile_name}")

        # Test expiry time after refresh
        expiry_time = session_handler.get_expiry_time()
        logging.info(f"Session expiry time for profile {profile_name} after refresh: {expiry_time}")

        # Test credentials after refresh
        credentials = session_handler.get_credentials()
        logging.info(f"Credentials for profile {profile_name} after refresh: {credentials}")

    except Exception as e:
        results["status"] = "failed"
        results["message"] = "One or more files failed to process."
        failure_message = f"Error processing session for profile {profile_name}: {e}"
        results["failures"].append({
            "file": f"{profile_name}.json",
            "error": failure_message
        })
        logging.error(failure_message)  # Log the failure details with error message


    # Prepare final output JSON
    if results["status"] == "failed" and len(results["failures"]) > 0:
        logging.error(json.dumps(results, indent=2))  # Log the failure details as structured JSON
    else:
        logging.info(json.dumps(results, indent=2))  # Log the success message

if __name__ == "__main__":
    # Configure logging
    current_dir = os.path.dirname(os.path.abspath(__file__))
    param_key = f"AWS_SSO.log"
    log_file_path = utils.configure_logging_api(param_key, utils.current_date, current_dir)

    main()