import os
import sys
import logging
import json
import time
import threading
from dotenv import load_dotenv
import boto3

# Load configuration from .env
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root_path)

# Import custom modules
from utils import utils

# Check if running in a CI/CD pipeline
is_ci_cd = os.getenv('CI_PIPELINE') == 'true'

if not is_ci_cd:
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
    from awsresources.AWSSSOSession import AWSSSOSession
else:
    from awsresources.AWSCICDSession import AWSCICDSession

# from utils.config import profile_name

class IVRTester:
    def __init__(self):  
        """
        Initialize the IVR Tester.
        This constructor sets up:
            - Logging configuration.
            - A threading lock for thread-safe operations.
            - The AWS Connect client.
            - The AWS Lambda client.
        Attributes:
            lock (threading.Lock): Ensures thread-safe access to shared resources.
            connect_client (boto3.Client): Client used to interact with Amazon Connect.
            lambda_client (boto3.Client): Client used to invoke AWS Lambda functions.
        """
        self._setup_logging()
        self.lock = threading.Lock()
        self.connect_client = self._initialize_connect_client()
        self.lambda_client = self._initialize_lambda_client()
    
    def _setup_logging(self):
        """
        Configure logging for the IVR Tester.

        Uses utility function `configure_logging_api` to:
        - Set the log file name using `param_key`.
        - Store logs in the current directory.
        - Append current date to the log file name for organized logging.
        """
        param_key = "ivr_tester.log"
        current_dir = os.path.dirname(os.path.abspath(__file__))
        utils.configure_logging_api(param_key, utils.current_date, current_dir)
    
    def _initialize_connect_client(self):
        """
        Initialize and return the AWS Connect client.

        - Chooses the session source based on the environment:
            - If running in CI/CD (`is_ci_cd`), use `AWSCICDSession`.
            - Otherwise, use `AWSSSOSession` with a given profile.
        - Connect client is created for the specified AWS region.

        Returns:
            botocore.client.Connect: A low-level client to interact with Amazon Connect.
        """
        session = AWSSSOSession(os.getenv("profile_name")).get_session() if not is_ci_cd else AWSCICDSession().get_session()
        aws_region = os.getenv("AWS_REGION", "us-east-1")
        return session.client("connect", region_name=aws_region)

    def _initialize_lambda_client(self):
        """
        Initialize and return the AWS Lambda client.

        - Selects session source based on execution environment:
            - Uses `AWSSSOSession` with a named profile for local use.
            - Uses `AWSCICDSession` for CI/CD pipelines.
        - Connects to the specified AWS region (defaults to 'us-east-1').

        Returns:
            botocore.client.Lambda: A low-level client to interact with AWS Lambda.
        """
        session = AWSSSOSession(os.getenv("profile_name")).get_session() if not is_ci_cd else AWSCICDSession().get_session()
        aws_region = os.getenv("AWS_REGION", "us-east-1")
        return session.client("lambda", region_name=aws_region)
    
def start_ivr_test_case(self, instance_id, contact_flow_id, hotline_number, input_sequence, expected_responses):
    """
        Initiates and validates an IVR (Interactive Voice Response) test case on AWS Connect.

        This method starts a test call through AWS Connect using a specified contact flow.
        It simulates user input (e.g., DTMF tones) and compares the responses from a
        Lambda function to expected values for each step.

        Args:
            instance_id (str): AWS Connect Instance ID.
            contact_flow_id (str): The Contact Flow ID associated with the IVR test.
            hotline_number (str): The virtual number used to initiate the call.
            input_sequence (List[str]): List of simulated keypad inputs (DTMF tones).
            expected_responses (List[str]): List of expected IVR responses for each input.

        Returns:
            bool: `True` if all steps passed successfully; `False` if any mismatch or error occurred.

        Behavior:
            - Initiates a task contact via AWS Connect.
            - Sends inputs to a Lambda function (`get-dtmf-ivr-data-v3`) simulating IVR interaction.
            - Logs and reports mismatches between expected and actual responses.
            - Prints and logs the final result (pass/fail).

        Notes:
            - The test stops at the first failure.
            - Lambda responses are expected to contain a 'ResponseText' field.

        Logging:
            - Logs contact ID, each test step, any mismatches, and final results.
            - Prints a summary JSON for CLI or subprocess consumption.
        """
    failures = []
    try:
        response = self.connect_client.start_task_contact(
            InstanceId=instance_id,
            ContactFlowId=contact_flow_id,
            Attributes={"PhoneNumber": hotline_number}
        )
        contact_id = response.get("ContactId")
        logging.info(f"Started IVR test. Contact ID: {contact_id}")
        time.sleep(5)

        for step, (input_value, expected) in enumerate(zip(input_sequence, expected_responses), 1):
            lambda_response = self.lambda_client.invoke(
                FunctionName="get-dtmf-ivr-data-v3",
                InvocationType="RequestResponse",
                Payload=json.dumps({"input": input_value})
            )
            actual_response = json.loads(lambda_response["Payload"].read())
            logging.info(f"Step {step}: Sent '{input_value}', Expected: '{expected}', Received: '{actual_response}'")
            
            if actual_response.get("ResponseText") != expected:
                error_msg = f"Mismatch at step {step}: Expected '{expected}', but got '{actual_response.get('ResponseText')}'"
                logging.error(error_msg)
                failures.append({"step": step, "error": error_msg})
                break

            time.sleep(2)
    except Exception as e:
        error_msg = f"Exception occurred during test: {e}"
        logging.error(error_msg)
        failures.append({"step": "initialization", "error": error_msg})

    result = {
        "status": "passed" if not failures else "failed",
        "message": "IVR test case passed successfully." if not failures else f"IVR test case failed: {failures[0]['error']}",
        "failures": failures
    }

    logging.info(json.dumps(result, indent=2))
    print(json.dumps({"status": result["status"], "message": result["message"]}, indent=2))
    return result["status"] == "passed"


if __name__ == "__main__":
    ivr_tester = IVRTester()
    test_case = {
        "instance_id": "your-instance-id",
        "contact_flow_id": "your-contact-flow-id",
        "hotline_number": "+16662647439",
        "input_sequence": ["2", "BOOKING_ID", "2", "1", "1", "CUSTOMER_INTENT", "1"],
        "expected_responses": [
            "Existing Service Menu", "Provide Booking ID", "Online Agent Menu",
            "Change 3PF Menu", "Holiday Change", "Provide Customer Intent", "Connecting to Agent"
        ]
    }
    ivr_tester.start_ivr_test_case(**test_case)
