from datetime import datetime, timezone
import json
import sys
import os
import time
from dotenv import load_dotenv
import logging
import argparse
import traceback

# Automatically find the project root and add it to sys.path
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root_path)

from core.utils import utils

# Import APIEngine class
from api_engine import APIEngine

if not os.getenv('CI_PIPELINE'):  # GitLab CI/CD sets the CI environment variable
    print("Local environment detected. Loading variables from .env file...")
    # Load configuration from the .env file
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
else:
    print("CI/CD environment detected. Using CI/CD provided variables...")

# Get the environment from the variable (from .env for local or directly from CI/CD)
environment = os.getenv("ENVIRONMENT")

if environment:
    print(f"Using environment-specific variables for: {environment}")
else:
    print("No specific environment set, assuming CI/CD environment variables are provided...")


def main(application, endpoints, filename_pattern, test_case_key, topic, method):
    try:
        for endpoint in endpoints:
            overall_start_time = time.time()
            start_time = datetime.now(timezone.utc).isoformat()

            engine = APIEngine(
                application=application,
                method=method.upper(),
                endpoints=[endpoint],
                filename_pattern=filename_pattern,
                test_case_key =test_case_key,
                current_dir=os.path.dirname(os.path.abspath(__file__)),
                start_time=start_time
            )

            pass_rate = engine.process_endpoints(topic)

            process_status = utils.calculate_process_status(pass_rate)
            engine.create_summary_overall(overall_start_time)

            print(f"\n{method} Operation Completed Successfully")

            if process_status.get("status") == "success":
                print(process_status)
                sys.exit(0)
            else:
                print(process_status)
                sys.exit(1)
        
    except Exception as e:
        error_message = f"An error occurred: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)  # Exit as failure if exception occurs

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Process test files in parallel.")
        parser.add_argument('application', type=str, nargs='?', default='restful', help='Application folder name')
        parser.add_argument('end_points', type=str, nargs='?', default='objects', help='API endpoints or "all" for all endpoints')
        parser.add_argument('method', type=str, nargs='?', default='Get', help='API request method')
        parser.add_argument('filename_pattern', type=str, nargs='?', default='response_POST.json', help='Files with filename pattern to be picked up')
        parser.add_argument('test_case_key', type=str, nargs='?', default='all', help='Test key to execute')
        parser.add_argument('topic', type=str, nargs='?', default='', help='Topic name')

        args = parser.parse_args()
        application = args.application
        endpoints = [args.end_points]
        filename_pattern = args.filename_pattern
        test_case_key = args.test_case_key
        topic = args.topic
        method = args.method

        main(application, endpoints, filename_pattern, test_case_key, topic, method)
        
    except Exception as e:
            tb = traceback.extract_tb(sys.exc_info()[2])[-1]
            error_message = (
                f"Exception occurred in script {__file__}, line {tb.lineno}, in {tb.name}: {str(e)}"
            )
            logging.error(error_message)
            print(json.dumps({
                "status": "failed",
                "message": error_message
            }, indent=2))
            sys.exit(1)

