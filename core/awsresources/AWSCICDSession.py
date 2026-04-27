import json
import boto3
import os
import sys
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root_path)

# Import custom modules
from utils import utils
# from utils.config import aws_account, role_arn, region, profile_name

# Automatically reload environment variables when .env file changes
load_dotenv(dotenv_path=".env", verbose=True, override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

class AWSCICDSession:
    """
        Initializes the AWS CI/CD session.

        - Loads the default AWS region from the 'REGION' environment variable.
        - Sets session duration and expiry tracking.
        - Initializes threading lock and refresh thread control.
        - Immediately calls `assume_role()` to establish the initial session.
    """
    def __init__(self):
        self.session = None
        self.credentials = None
        self.region = os.getenv('REGION', 'eu-central-1')
        self.session_expiry = None
        self.stop_event = threading.Event()
        self.refresh_thread = None
        self.session_duration = 3600  # 1 hour session duration
        self.lock = threading.Lock()
        self.assume_role()

    def assume_role(self):
        """
        Assume an IAM role and establish a boto3 session using temporary credentials.

        This method performs the following:
        - Reads required AWS identity parameters (account ID, role name, external ID, session name) from environment variables.
        - Uses AWS STS (Security Token Service) to assume the specified IAM role.
        - Stores the returned temporary credentials and calculates the session expiry time.
        - Initializes a boto3 session using these credentials, scoped to the configured region.

        Environment Variables Required:
            - AWS_ACCOUNT_ID: Target AWS account number.
            - AWS_DEPLOYMENT_ROLE: IAM role name to assume in the target account.
            - AWS_ACCOUNT_NAME: Used as a session name (for tracking/debugging in AWS).
            - AWS_EXTERNAL_ID: External ID used for cross-account role assumption.
            - REGION (optional): Defaults to 'eu-central-1' if not set.

        Returns:
            boto3.Session | None: Returns a boto3 session object if successful, otherwise None.
        """
        aws_account_id = os.getenv('AWS_ACCOUNT_ID')
        aws_account_name = os.getenv('AWS_ACCOUNT_NAME')
        role_name = os.getenv('AWS_DEPLOYMENT_ROLE')
        external_id = os.getenv('AWS_EXTERNAL_ID')
        role_arn = f"arn:aws:iam::{aws_account_id}:role/{role_name}"

        try:
            sts_client = boto3.client('sts', region_name=self.region)
            response = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName=aws_account_name,
                ExternalId=external_id,
                DurationSeconds=self.session_duration
            )

            self.credentials = response['Credentials']
            self.session_expiry = datetime.now(timezone.utc) + timedelta(seconds=self.session_duration)

            # Create a session using the assumed role credentials
            self.session = boto3.Session(
                aws_access_key_id=self.credentials['AccessKeyId'],
                aws_secret_access_key=self.credentials['SecretAccessKey'],
                aws_session_token=self.credentials['SessionToken'],
                region_name=self.region
            )
            logging.info("[PASS] Session assumed successfully.")
            return self.session
        except Exception as e:
            logging.error(f"[FAIL] Error assuming role: {e}")
            return None
       

    def list_buckets(self):
        """
        List all Amazon S3 buckets accessible via the current AWS session.

        This method uses the boto3 S3 client to retrieve and log the names
        of all buckets under the account associated with the assumed role.

        Requirements:
            - A valid AWS session must have been successfully established via `assume_role`.

        Logs:
            - A list of all S3 bucket names if successful.
            - An error message if the session is invalid or the API call fails.
        """
        try:
            s3_client = self.session.client('s3')
            response = s3_client.list_buckets()
            logging.info("Buckets in the account:")
            for bucket in response['Buckets']:
                logging.info(f"  - {bucket['Name']}")
        except Exception as e:
            logging.error(f"Error listing buckets: {e}")
            

    def refresh_session(self):
        """
        Refresh the AWS session by re-assuming the IAM role.

        This method ensures continued access by renewing temporary credentials
        before they expire. It is thread-safe and acquires a lock to prevent
        simultaneous refreshes in multithreaded environments.

        Actions:
            - Acquires a thread lock.
            - Logs the refresh operation.
            - Calls `assume_role()` to get new temporary credentials.

        Note:
            - This should be invoked before session expiration.
            - Assumes that `assume_role()` handles errors gracefully.

        Returns:
            None
        """
        with self.lock:
            logging.info("Refreshing session.")
            self.assume_role()
            

    def start_auto_refresh(self):
        """
        Start a background daemon thread to automatically refresh the AWS session.

        This method launches a background thread that:
            - Calculates how long to wait before the session is about to expire.
            - Waits until 5 minutes before expiry (55 minutes into a 60-minute session).
            - Calls `refresh_session()` to refresh credentials.
            - Repeats the cycle until `stop_event` is triggered.

        The thread uses `self.stop_event` to check for cancellation, and runs as a
        daemon so it does not block program exit.

        Important:
            - Make sure `self.session_expiry` is set correctly by `assume_role()`.
            - Use `stop_auto_refresh()` to stop the background thread gracefully.

        Returns:
            None
        """
        def refresh_loop():
            while not self.stop_event.is_set():
                time_to_wait = (self.session_expiry - timedelta(minutes=55) - datetime.now(timezone.utc)).total_seconds()
                if time_to_wait > 0:
                    if self.stop_event.wait(timeout=time_to_wait):
                        break
                self.refresh_session()

        self.refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        self.refresh_thread.start()
        logging.info("Auto-refresh thread started.")
        

    def stop_auto_refresh(self):
        """
        Stop the background thread responsible for auto-refreshing the AWS session.

        This method:
            - Signals the `stop_event` to request the thread to stop.
            - Waits for the background thread to terminate using `join()`.
            - Logs the shutdown of the auto-refresh process.

        Usage:
            Call this method before the program exits or when auto-refresh is no longer needed
            to ensure graceful termination of the thread and cleanup of resources.

        Returns:
            None
        """
        if self.refresh_thread:
            self.stop_event.set()
            self.refresh_thread.join()
            logging.info("Auto-refresh thread stopped.")
    
    
    def get_credentials(self):
        """
        Returns the AWS credentials associated with the current session.

        Returns:
            botocore.credentials.Credentials: The current session's credentials object,
            or None if the session is not properly initialized.
        """
        return self.session.get_credentials()


    def get_session(self):    
        """
        Returns the current boto3 session object.

        Returns:
            boto3.Session: The active session assumed via STS,
            or None if the session hasn't been initialized.
        """
        return self.session

if __name__ == "__main__":

    # Configure logging
    current_dir = os.path.dirname(os.path.abspath(__file__))
    param_key = f"AWS_CICD.log"
    log_file_path = utils.configure_logging_api(param_key, utils.current_date, current_dir)
    
    failures = []
    output_summary = {
        "status": "passed",
        "message": "Program executed successfully.",
        "failures": []
    }

    
    logging.info("Starting AWSCICDSession.")
    try:
        session_handler = AWSCICDSession()
        if not session_handler.session:
            raise Exception("Failed to create AWS session.")
    except Exception as e:
        error_msg = str(e)
        logging.error(f"[FAIL] Failed to initialize session: {error_msg}")
        failures.append({"file": "session_init", "error": error_msg})

    if not failures:
        try:
            session_handler.start_auto_refresh()
        except Exception as e:
            error_msg = str(e)
            logging.error(f"[FAIL] Failed to start auto-refresh thread: {error_msg}")
            failures.append({"file": "auto_refresh", "error": error_msg})

    try:
        session_handler.list_buckets()
        time.sleep(10)  # Adjust as needed
    except Exception as e:
        error_msg = str(e)
        failures.append({"file": "list_buckets", "error": error_msg})
    except KeyboardInterrupt:
        logging.warning("Process interrupted by user.")
    finally:
        session_handler.stop_auto_refresh()

    # Final Output
    if failures:
        output_summary["status"] = "failed"
        output_summary["message"] = "Program failed: " + "; ".join(f["error"] for f in failures)
        output_summary["failures"] = failures

    # Log full output to file
    logging.info(json.dumps(output_summary, indent=2))

