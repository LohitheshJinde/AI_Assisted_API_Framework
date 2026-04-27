from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib
import inspect
import os
import sys
import json
import logging
import traceback
from typing import Any, Callable, Dict, List
from dotenv import dotenv_values
import requests
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv

project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root_path)

from core.utils import utils, compare_response
import Auth
from Auth import Auth

# Automatically reload environment variables when .env file changes
load_dotenv(dotenv_path=".env", verbose=True, override=True)

if not os.getenv("CI_PIPELINE"):  # GitLab CI/CD sets the CI environment variable
    print("Local environment detected. Loading variables from .env file...")
    # Load configuration from the .env file
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
else:
    print("CI/CD environment detected. Using CI/CD provided variables...")

# Get the environment from the variable (from .env for local or directly from CI/CD)
environment = os.getenv("ENVIRONMENT") or "TEST"

if environment:
    print(f"Using environment-specific variables for: {environment}")
else:
    print(
        "No specific environment set, assuming CI/CD environment variables are provided..."
    )

class APIEngine:
    def __init__(self, application: str, method: str, endpoints: List[str], filename_pattern: str, test_case_key: str, current_dir: str, start_time:str, access_token: str = ""):
        self.application = application
        self.method = method.upper()
        self.endpoints = endpoints
        self.filename_pattern = filename_pattern
        self.test_case_key = test_case_key
        self.access_token = access_token
        self.current_dir = current_dir
        self.project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.summary = {'passed': 0, 'failed': 0}
        self.lock = threading.Lock()
        self.collected_responses = []
        self.collected_summary = {}
        self.start_time = start_time
        self.avg_req_time = 0
        self.avg_test_time = 0
        
        # Initialize Auth handler and get initial token
        param = self.load_param_data(self.method, self.application, self.endpoints[0])
        self.auth_handler = Auth(param["access_token_key"], param["auth_type"], logging.getLogger())
        # Get initial token and start auto refresh (skip for auth_type "none")
        if param["auth_type"] != "none":
            initial_token, expires_in = self.auth_handler.generate_token()
            if initial_token:
                self.auth_handler.start_auto_refresh()
            else:
                logging.info(f"ENVIRONMENT: {os.getenv('ENVIRONMENT')}")
                logging.info(f"BASE_URL: {os.getenv('TEST_BASE_URL')}")
                logging.error("Failed to get initial access token")

    def get_function_params(self, func):
        """
        Get the parameter names of a given function.
        
        Parameters:
        ----------
        func : function
            The function whose parameters are to be inspected.
        
        Returns:
        -------
        list
            A list of parameter names required by the function.
        """
        signature = inspect.signature(func)
        return list(signature.parameters.keys())
    
    def prepare_arguments(self, func, local_vars):
        """
        Prepares a list of arguments for a function based on its parameter names.
    
        Parameters:
        ----------
        func : function
            The function to be called.
        local_vars : dict
            A dictionary of local variables.
    
        Returns:
        -------
        list
            A list of arguments to pass to the function.
        """
        param_names = self.get_function_params(func)
        return [local_vars.get(param) for param in param_names]
    
    def load_param_data(self, method, application, endpoint):
        """
        Loads and combines API parameter data from default, application-specific, and endpoint-specific configurations.

        Parameters:
        ----------
        method : str
            The HTTP method (e.g., 'GET', 'POST') for the API request. Case-insensitive, converted to uppercase.
        application : str
            The name of the application, used to locate the application's parameter file.
        endpoint : str
            The API endpoint whose parameters need to be retrieved.

        Returns:
        -------
        dict
            A dictionary containing merged parameter values, defaulting to None if keys are not found.
        """
        # Load parameters from files
        default_params = utils.load_params(param_file_name='param.json', base_folder='core/api_engine')
        param_file_app = utils.load_params(param_file_name="param.json", base_folder=application)
        endpoint_params = param_file_app.get(endpoint, {})

        # Normalize HTTP method to uppercase
        method = method.upper()
        method_params = endpoint_params.get(method, {})

        base_url_env = os.getenv(f"{environment}_BASE_URL") or os.getenv("TEST_BASE_URL") or "TEST"
        
        # Handle URL replacement logic
        url = method_params.get("url", "")
        if "{base_url}" in url and "{app_url}" in url:
            url = url.replace("{base_url}", os.getenv(f"{environment}_BASE_URL"))
        elif "{base_url}" in url:
            url = url.replace("{base_url}", os.getenv(f"{environment}_BASE_URL"))
        elif "{app_url}" in url:
            url = url.replace("{app_url}", base_url_env)
        
        # Build parameter dictionary with None as the default for missing keys
        param_data = {
            "base_folder": default_params.get("testdata_path", None),
            "access_token": endpoint_params.get("access_token", None),
            "access_token_key" : endpoint_params.get("access_token_key","api"),
            "auth_type" : endpoint_params.get("auth_type", "oauth"),  # Default to OAuth if not specified
            "think_time": default_params.get("think_time", None),
            "max_retries": default_params.get("max_retries", None),
            "backoff_factor": default_params.get("request_delay", None),
            "max_retries_m": method_params.get("max_retries", None),
            "backoff_factor_m": method_params.get("request_delay", None),
            "response_threshold_time": method_params.get("response_threshold_time", None),
            "file_process_count": default_params.get("file_process_count", None),
            "max_threads": default_params.get("thread_count", None),
            "excluded_folders": default_params.get("excluded_folders", None),
            "log_message_template": default_params.get("log_message_template", None),
            "summary_log_template": default_params.get("summary_log_template", None),
            "expected_non_empty_keys": method_params.get("expected_non_empty_keys", None),
            "url": url,
			# "url": method_params.get("url", ""),
            "headers": method_params.get("headers", None),
            "header_key": method_params.get("header_key", None),
            "payload_key": method_params.get("payload_key", None),
            "expected_status_code_key": method_params.get("expected_status_code_key", None),
            "test_case_name_key": method_params.get("test_case_name_key", None),
            "expected_status_code_success": method_params.get("expected_status_code_success", None),
            "primary_key": method_params.get("primary_key", None),
            "secondary_key": method_params.get("secondary_key", None),
            "primary_value": method_params.get("primary_value", None),       
            "testdata_path": method_params.get("testdata_path", None),
            "response_path": method_params.get("response_path", None),
            "get_param": method_params.get("get_param", None),
            "response_filename": method_params.get("response_filename", None),
            "test_description": method_params.get("test_description", None),
            "certificate_name": method_params.get("certificate_name", None),
			"pagination": method_params.get("pagination", None),
            "pagination_debug_key": method_params.get("pagination_debug_key", None),
            "pagination_pages": method_params.get("pagination_pages", None),
            "contract_testing_schema_path":method_params.get("contract_testing_schema_path",None),
            "has_payload": method_params.get("has_payload", False),
            "payload_filename": method_params.get("payload_filename", None)
        }

        return param_data

    def setup_file_logger(self, json_file, log_filename, current_dir, endpoint):
        """
        Sets up a file logger and a console logger for a given JSON file and directory.

        Parameters:
        ----------
        json_file : str
            The name or path of the JSON file, used to uniquely identify the logger.
        log_filename : str
            The name of the log file to be created.
        current_dir : str
            The current directory where the logging process is initiated.

        Returns:
        -------
        tuple
            A tuple containing:
            - file_logger (logging.Logger): The configured logger instance.
            - file_handler (logging.FileHandler): The file handler attached to the logger.

        Functionality:
        --------------
        1. Creates a logger uniquely identified by the basename of the `json_file`.
        2. Sets the logging level to INFO and prevents propagation to the root logger.
        3. Computes a relative path from `project_root_path` to `current_dir`:
           - Handles scenarios where the paths might reside on different drives.
        4. Defines a logging directory structure under `project_root_path/logs/`:
           - Includes the current date (`utils.current_date`) and relative path to `current_dir`.
        5. Ensures the log directory exists; handles exceptions if directory creation fails.
        6. Sets up:
           - A **file handler** for logging messages to the specified log file.
           - A **console handler** for logging error messages to the console.
        7. Adds handlers to the logger only if they haven’t been added previously to avoid duplicates.

        Notes:
        ------
        - The `utils.current_date` is expected to return a string representing the current date.
        - The `project_root_path` should be defined globally in the script or module.
        """
        # Get logger by JSON file name
        file_logger = logging.getLogger(f'logger_{os.path.basename(json_file)}')
        file_logger.setLevel(logging.INFO)
        file_logger.propagate = False

        # Calculate relative path from project_root_path to current_dir
        try:
            relative_path = os.path.relpath(current_dir, self.project_root_path)
        except ValueError:
            # Handle case where paths are on different drives
            relative_path = os.path.basename(current_dir)

        # Define the log directory and log file path
        log_dir = os.path.join(self.project_root_path, "logs", utils.current_date, relative_path, endpoint)

        # Ensure the logs directory exists
        try:
            os.makedirs(log_dir, exist_ok=True)  # Allow existing directories
        except OSError as e:
            print(f"Error creating log directory: {e}")
            raise
        
        log_filepath = os.path.join(log_dir, log_filename)

        # Set up the file handler for logging to file
        file_handler = logging.FileHandler(log_filepath)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

        # Set up the stream handler for logging to console
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.ERROR)  # Log only errors to the console
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

        # Avoid adding duplicate handlers
        if not file_logger.hasHandlers():
            file_logger.addHandler(file_handler)
            file_logger.addHandler(console_handler)

        return file_logger, file_handler, log_dir

    def process_endpoints(self, topic = None):
        """
        Processes API endpoints by executing test cases defined in JSON files.

        Parameters:
        ----------
        config : ProcessConfig
            A configuration object containing the following attributes:
            - `method` (str): The HTTP method (e.g., 'GET', 'POST').
            - `application` (str): The name of the application being tested.
            - `current_dir` (str): The current working directory.
            - `endpoints` (str | list[str]): List of endpoints to process, or 'all' to process all available endpoints.

        Functionality:
        --------------
        1. Configures logging with a dynamic log file name based on the HTTP method and current date.
        2. If `config.endpoints` is set to 'all', retrieves all valid subdirectories (endpoints) under the application's path.
        3. For each endpoint:
           - Loads parameter data using `load_param_data`.
           - Retrieves matching JSON files using `utils.get_json_files_new`.
           - Processes each JSON file using a `ThreadPoolExecutor` to handle concurrent execution.
        4. Aggregates test results:
           - Counts passed and failed test cases.
           - Logs errors encountered during execution.
        5. Creates a summary for each endpoint by calling `create_summary_endpoint`.

        Error Handling:
        ---------------
        - Catches and logs exceptions for both endpoint processing and individual JSON file execution.
        - Logs errors encountered during the processing of test cases to aid debugging.

        Notes:
        ------
        - The `ProcessConfig` class must be defined with the expected attributes.
        - Global variables `project_root_path` and `utils.current_date` are assumed to be properly set.
        - The `process_json_file` function processes individual JSON files and returns a boolean indicating test success.
        """
        try:
            log_file_name = f"execute_test_cases_{self.method}"
            parent_dir = os.path.abspath(os.path.join(self.current_dir, os.pardir))
            parent_dir = self.current_dir if parent_dir == self.project_root_path else parent_dir
            utils.configure_logging_api(log_file_name, utils.current_date, parent_dir)
            if self.endpoints == 'all':
                app_path = os.path.join(self.project_root_path, self.application)
                self.endpoints = [
                    folder for folder in os.listdir(app_path) 
                    if os.path.isdir(os.path.join(app_path, folder)) 
                    and folder not in {"logs", "__pycache__"}
                ]
            for subfolder in self.endpoints:
                start_time_endpoint = time.time()
                param_data = self.load_param_data(self.method, self.application, subfolder)
                if topic: 
                    param_data["topic"] = topic
                if param_data.get("testdata_path"):
                    json_files = utils.get_json_files(
                        base_folder = param_data.get("base_folder"), subfolder = param_data.get("testdata_path"), filename_pattern = self.filename_pattern
                    )
                else:
                    json_files = utils.get_json_files_api(
                        param_data.get("base_folder"), self.application, subfolder, self.filename_pattern
                    )

                result = {'passed': 0, 'failed': 0}
                logging.info(f"Processing JSON files for endpoint '{subfolder}': {json_files}")

                # Use ThreadPoolExecutor to control the number of concurrent tasks
                with ThreadPoolExecutor(max_workers = param_data.get("file_process_count")) as executor:
                    futures = [
                        executor.submit(
                            self.process_json_file, json_file, subfolder, result, param_data
                        ) for json_file in json_files
                    ]
                    for future in as_completed(futures):
                        try:
                            result_data = future.result()
                            if result_data:
                                test_case_passed = result_data
                                if test_case_passed:
                                    result['passed'] += 1
                                else:
                                    result['failed'] += 1
                        except Exception as e:
                            logging.error(f"Error processing endpoint: {e}")
                pass_rate = self.create_summary_endpoint(result, start_time_endpoint, param_data, subfolder)
                self.generate_json_report(param_data)
				#self.generate_json_report()
                return pass_rate
        except Exception as e:
            logging.error(f"Error processing file: {e}")

    def process_json_file(self, json_file, endpoint, endpoint_summary, param_data):
        """
        Processes a single JSON file containing API test cases and logs the results.

        Parameters:
        ----------
        json_file : str
            Path to the JSON file containing test cases.
        endpoint : str
            The API endpoint associated with the test cases.
        endpoint_summary : dict
            A dictionary tracking the cumulative summary for the endpoint (passed and failed test cases).
        param_data : dict
            Configuration parameters specific to the endpoint and HTTP method.
        config : ProcessConfig
            A configuration object containing test execution parameters such as `method` and `current_dir`.

        Functionality:
        --------------
        1. Initializes logging for the JSON file:
           - Creates a unique log file for each test case file.
        2. Reads the JSON file and extracts test cases.
        3. Generates a response file to store results.
        4. Processes test cases concurrently using a `ThreadPoolExecutor`:
           - Calls `process_test_case` for each test case.
           - Collects response data and updates file-specific pass/fail counts.
        5. Writes the collected responses to a response JSON file.
        6. Updates the endpoint summary with the file-specific test results.
        7. Logs a summary for the processed file, including pass rate and elapsed time.
        8. Cleans up by removing the file handler to prevent duplicate logging in future runs.

        Returns:
        -------
        None

        Notes:
        ------
        - Uses multithreading to speed up test case execution.
        - A thread-safe lock ensures consistency when updating shared data (e.g., response files, summaries).
        - The response file is saved alongside the original JSON file with a modified filename.
        - Requires `param_data` to include keys like:
            - `filename_pattern`: Pattern to identify test case files.
            - `max_threads`: Max concurrent threads for processing.
            - `summary_log_template`: Template for log summary messages.
        """
        try:
            start_time_file = time.time()  # Start time for processing the file

            # Set up the log file using config parameters
            try:
                log_filename = f"{self.method}_{endpoint}_{os.path.basename(json_file).replace('.json', '_log')}.log"
                parent_dir = os.path.abspath(os.path.join(self.current_dir, os.pardir))
                parent_dir = self.current_dir if parent_dir == self.project_root_path else parent_dir
                file_logger, file_handler, log_dir = self.setup_file_logger(json_file, log_filename, parent_dir, endpoint)
            except Exception as e:
                logging.error(f"Failed to set up logging for file {json_file}: {e}")
                return  # Skip processing this file

            file_logger.info(f"Processing file: {json_file}")

            # Read test cases from JSON file
            try:
                with open(json_file, 'r') as file:
                    test_cases = json.load(file)
            except Exception as e:
                file_logger.error(f"Error reading JSON file {json_file}: {e}")
                return  # Skip further processing

            if param_data.get("response_filename"):
                response_filename = param_data["response_filename"]
            else:    
                response_filename = os.path.basename(json_file).replace(
                    self.filename_pattern,
                    f"response_{self.method}.json"
                )
                

            # Response file stored in testdata folder
            if param_data.get("response_path"):
                folder_path = os.path.join(self.project_root_path, param_data.get("response_path"))
                # Create the folder if it doesn't exist
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)
                response_filepath = os.path.join(folder_path, response_filename)
            else:
                response_filepath = os.path.join(os.path.dirname(json_file), response_filename)        

            
            responses = []
            file_summary = {"passed": 0, "failed": 0}  # File-specific summary
            json_filename = os.path.basename(json_file)
            
            if self.test_case_key:
                if self.test_case_key != "all":
                    test_cases = [
                        tc for tc in test_cases
                        if tc.get("test_key", "").startswith(self.test_case_key)
                    ]

            # Multithreading for processing requests concurrently
            try:
                with ThreadPoolExecutor(max_workers=param_data.get("max_threads")) as executor:
                    futures = [
                        executor.submit(
                            self.process_test_case, json_filename, test_case, file_logger, param_data
                        )
                        for test_case in test_cases
                    ]
                    for future in as_completed(futures):
                        try:
                            test_case_passed, analytics_data, results_data = future.result()  # Unpack the tuple
                            if analytics_data:
                                with self.lock:
                                    responses.append(analytics_data)
                                    self.collected_responses.append(results_data)
                                    if test_case_passed:
                                        file_summary['passed'] += 1
                                    else:
                                        file_summary['failed'] += 1
                        except Exception as e:
                            file_logger.error(f"Error processing test case: {e}")
            except Exception as e:
                file_logger.error(f"Error during multithreaded test case execution: {e}")

            # Writing responses to file
            try:
                with self.lock:
                    with open(response_filepath, 'w') as response_file:
                        json.dump(responses, response_file, indent=4)
                    # Update endpoint-specific summary
                    endpoint_summary["passed"] += file_summary["passed"]
                    endpoint_summary["failed"] += file_summary["failed"]
            except Exception as e:
                file_logger.error(f"Error writing response file {response_filepath}: {e}")

            # Calculate file-specific pass rate
            try:
                total_file_tests = file_summary['passed'] + file_summary['failed']
                file_pass_rate = (
                    (file_summary['passed'] / total_file_tests) * 100
                    if total_file_tests > 0 else 0
                )

                # End time for processing the file
                elapsed_time_file = time.time() - start_time_file

                file_logger.propagate = True

                file_logger.info(f"Responses saves to file: {response_filepath}")

                # Log file-specific summary and pass rate
                file_logger.info(param_data.get("summary_log_template").format(
                    context=f"File {response_filename}",
                    total_req=total_file_tests,
                    passed=file_summary['passed'],
                    failed=file_summary['failed'],
                    rate=f"{file_pass_rate:.2f}%",
                    elapsed_time=f"{elapsed_time_file:.2f}"
                ))
            except Exception as e:
                logging.error(f"An unexpected error occurred while processing file {json_file}: {e}")
        finally:
            # Clean up: remove file handler to prevent duplicate logs in future runs
            if 'file_logger' in locals() and 'file_handler' in locals():
                file_logger.removeHandler(file_handler)
                file_handler.close()

    def process_test_case(self, json_filename, test_case, file_logger, param_data):
        """
        Processes an individual test case by sending an API request and comparing the response to expected results.

        Parameters:
        ----------
        test_case : dict
            The test case data, including payload, expected status code, and test case name.
        file_logger : logging.Logger
            Logger instance for logging details specific to the test case.
        config : ProcessConfig
            Configuration object containing test execution parameters such as HTTP method, current directory, and access token.
        param_data : dict
            Endpoint-specific configuration parameters, including URL, headers, and payload structure.

        Returns:
        -------
        tuple
            (bool, dict or None):
            - `True` if the test case passed, `False` otherwise.
            - A dictionary containing analytics data for the test case if available, `None` otherwise.

        Functionality:
        --------------
        1. Prepares the request:
           - Builds the URL, including dynamic replacements for `customer_id` if applicable.
           - Loads the SSL certificate if specified.
        2. Executes the API request using `request_logic`.
        3. Logs request details and response data.
        4. Compares the actual response with the expected result:
           - Uses `config.compare_json_response` for validation.
        5. Collects and returns analytics data including test case status, response time, and payload.
        6. Updates the summary of passed and failed test cases in a thread-safe manner.

        Error Handling:
        ---------------
        - Skips test cases with missing or invalid customer IDs, logging a warning without marking them as failed.
        - Handles failed requests by updating the failure count and skipping response validation.

        Notes:
        ------
        - `request_logic` handles the actual API request and returns the response data.
        - Requires a `lock` to ensure thread-safe updates to shared summary data.
        - The `compare_json_response` method validates the response based on the request type (GET, POST, PATCH).

        """  
        try:
            test_start_time = datetime.now(timezone.utc).isoformat()
            application = self.application
            endpoint = self.endpoints[0]
            method = self.method
            contract_testing_schema_path = param_data.get("contract_testing_schema_path","")
            url = param_data.get("url")
            headers = param_data.get("headers", {})
            
            if param_data.get("header_key"):
                header_key = param_data.get("header_key")
                for key, value_path in header_key.items():
                    header_value = self.get_nested_value(test_case, value_path)
                    if not header_value:
                        payload_key = param_data.get("payload_key")
                        header_value = self.get_nested_value(test_case.get(payload_key, {}), value_path)
                        if not header_value:
                            file_logger.warning(f"Skipping test case '{test_case_name}' due to missing value for '{key}'.")
                            return (False, None, None)
            
                    if key in headers:
                        headers[key] = headers[key].format(header_value=header_value)

            if param_data.get("topic"):
                topic = param_data.get("topic")

            # Get current token from auth handler - skip for auth_type "none"
            token = None
            if self.auth_handler.auth_type != "none":
                token, time_until_expiry, status = self.auth_handler.get_token_status()
                if status and token and "Authorization" in headers:
                    headers["Authorization"] = headers["Authorization"].format(access_token=token)
                elif self.access_token and "Authorization" in headers:
                    headers["Authorization"] = self.access_token
                elif "Authorization" in headers:
                    file_logger.warning("No valid token available")
            think_time = param_data.get("think_time")
            if param_data.get("max_retries_m"):
                max_retries = param_data.get("max_retries_m")
            else:
                max_retries = param_data.get("max_retries")
            if param_data.get("backoff_factor_m"):
                backoff_factor = param_data.get("backoff_factor_m")
            else:
                backoff_factor = param_data.get("backoff_factor")
            response_threshold_time = param_data.get("response_threshold_time","")
            payload_key = param_data.get("payload_key", "")
            expected_status_code = 200  # Default value
            if param_data.get("expected_status_code_key"):
                expected_status_code = test_case.get(param_data.get("expected_status_code_key"), 200)
            elif param_data.get("expected_status_code_success"):
                expected_status_code = param_data.get("expected_status_code_success")
            
            # Ensure expected_status_code is never None
            if expected_status_code is None:
                expected_status_code = 200
            
            # Handle payload loading for DELETE requests with separate payload file
            if method == "DELETE" and param_data.get("has_payload", False) and param_data.get("payload_filename"):
                # Load payload from separate file for DELETE requests
                try:
                    # Match payload filename with the pattern of the file being processed
                    base_filename = os.path.basename(json_filename)
                    if "regression" in base_filename:
                        payload_filename = f"{self.endpoints[0]}_regression_{param_data.get('payload_filename')}"
                    elif "smoke" in base_filename:
                        payload_filename = f"{self.endpoints[0]}_smoke_{param_data.get('payload_filename')}"
                    else:
                        payload_filename = f"{self.endpoints[0]}_{param_data.get('payload_filename')}"
                    
                    if param_data.get("testdata_path"):
                        # Replace forward slashes with proper path separators
                        testdata_path = param_data.get("testdata_path").replace("/", os.sep)
                        payload_file_path = os.path.join(
                            self.project_root_path, 
                            "testdata", 
                            testdata_path,
                            payload_filename
                        )
                    else:
                        payload_file_path = os.path.join(
                            self.project_root_path, 
                            "testdata", 
                            self.application,
                            self.endpoints[0],
                            payload_filename
                        )
                    with open(payload_file_path, 'r') as payload_file:
                        payload_data = json.load(payload_file)
                        # Use the first test case's payload from the payload file
                        if payload_data and len(payload_data) > 0:
                            payload = payload_data[0].get(payload_key, {})
                        else:
                            payload = {}
                            file_logger.warning(f"No payload data found in {payload_file_path}")
                except Exception as e:
                    file_logger.error(f"Error loading payload file {payload_file_path}: {e}")
                    payload = {}
            else:
                payload = test_case.get(payload_key, {})
            
            test_case_name = test_case["test_case_name"]
            test_key = test_case["test_key"]

            if test_case.get("expected_response"):
                expected_response = test_case.get("expected_response")

            # Import the certificate
            if param_data.get("certificate_name") is not None:
                cert_file_path = os.path.join(
                    os.path.abspath(self.application), self.endpoints[0], param_data.get("certificate_name")
                )

                if not os.path.exists(cert_file_path):
                    cert_file_path = None  # Set to None if file doesn't exist
            else:
                cert_file_path = None  # Ensure it's None if no certificate name is provided
            
            primary_value = None 
            secondary_value = None
   
            if method in ["PATCH", "PUT"]:
                try:
                    primary_value = test_case.get("id")
                    secondary_value = None

                    if not primary_value:
                        file_logger.warning(
                            f"Skipping test case '{test_case_name}' due to missing or invalid customer ID."
                        )
                        return (False, None, None)  # Skip without marking as failed
                    if test_case.get("secondary_id"):
                        secondary_value = test_case.get("secondary_id","")
                        url = url.format(
                            primary_key=primary_value,
                            secondary_key=secondary_value,
                        )
                    else:
                        url = url.format(primary_key=primary_value)

                except KeyError as e:
                    file_logger.error(
                        f"KeyError processing primary_key in test case '{test_case_name}': {e}"
                    )
                    return (False, None, None)
                except Exception as e:
                    file_logger.error(
                        f"Unexpected error processing primary_key in test case '{test_case_name}': {e}"
                    )
                    return (False, None, None)

            elif method in ["GET", "DELETE", "SNS"] or param_data.get("primary_key"):
                try:
                    primary_key = param_data.get("primary_key", "")
                    secondary_key = param_data.get("secondary_key", "")
                    get_params = param_data.get("get_param", {})

                    if not primary_key and not get_params:
                        raise ValueError("Missing 'primary_key' or 'get_param' in param.json configuration.")

                    # Append GET parameters dynamically
                    if get_params:
                        for param, path in get_params.items():
                            value = self.get_nested_value(test_case, path)
                            if value:
                                placeholder = f"{{{param}}}"
                                if placeholder in url:
                                    url = url.replace(placeholder, str(value))
                    else:
                        if param_data.get("primary_value"):
                            primary_value = param_data.get("primary_value")
                        else:
                            primary_value = self.get_nested_value(test_case, primary_key)
                            if not primary_value:
                                primary_value = self.get_nested_value(test_case.get(param_data.get("payload_key")), primary_key)
                                if not primary_value:
                                    file_logger.warning(f"Skipping test case '{test_case_name}' due to missing value for '{primary_key}'.")
                                    return (False, None, None)

                        if os.getenv("ENVIRONMENT") == "test" and method == "SNS":
                            primary_value = "T" + primary_value

                        secondary_value = None
                        if secondary_key:
                            secondary_value = self.get_nested_value(test_case, secondary_key)
                            if not secondary_value:
                                secondary_value = self.get_nested_value(test_case.get(param_data.get("payload_key")), secondary_key)
                                if not secondary_value:
                                    file_logger.warning(f"Skipping test case '{test_case_name}' due to missing value for '{secondary_key}'.")
                                    return (False, None, None)

                        # Construct the base URL with primary and secondary keys
                        if secondary_key:
                            url = url.format(primary_key=primary_value, secondary_key=secondary_value)
                        else:
                            url = url.format(primary_key=primary_value)

                except KeyError as e:
                    file_logger.error(f"KeyError processing dynamic key in test case '{test_case_name}': {e}")
                    return (False, None, None)
                except Exception as e:
                    file_logger.error(f"Unexpected error processing dynamic key in test case '{test_case_name}': {e}")
                    return (False, None, None)

            # Handle pagination if configured
            pagination_key = param_data.get("pagination")
            
            if pagination_key:
                all_responses = []
                next_token = ""
                page_count = 0
                
                # Get pagination pages configuration
                pagination_pages = param_data.get("pagination_pages", 1)
                if pagination_pages == "all":
                    max_pages = float('inf')  # Unlimited pages
                else:
                    max_pages = int(pagination_pages)
                
                file_logger.info(f"Pagination key: {pagination_key}")
                file_logger.info(f"Max pages configured: {pagination_pages}")
                
                while page_count < max_pages and (pagination_pages == "all" or page_count < max_pages):
                    # Create a copy of payload and update token for pagination
                    current_payload = payload.copy()
                    if pagination_key in current_payload:
                        current_payload[pagination_key] = next_token
                        file_logger.info(f"Page {page_count + 1}: Updated token for pagination: '{next_token}'")
                        file_logger.info(f"Page {page_count + 1}: Sending payload: {current_payload}")
                        file_logger.info(f"Page {page_count + 1}: Request URL: {url}")
                        file_logger.info(f"Page {page_count + 1}: Request Headers: {headers}")
                    
                    # Perform the API request
                    start_time_test = time.time()

                    response, response_data, actual_status_code, elapsed_time_req, attempt, error_message = self.request_logic(
                        url, headers, current_payload, think_time, method, file_logger, max_retries, 
                        backoff_factor, response_threshold_time, param_data, expected_status_code, token, cert_file_path
                    )
                    
                    page_count += 1
                    
                    # Handle pagination response
                    if response_data and isinstance(response_data, dict):
                        all_responses.append(response_data)
                        next_token = response_data.get(pagination_key)
                        file_logger.info(f"Page {page_count}: Found nextToken: '{next_token}'")
                        file_logger.info(f"Page {page_count}: Received response with {len(response_data)} keys")
                        
                        # Debug: Log first and last items from each page if configured
                        if param_data.get("pagination_debug_key"):
                            debug_key = param_data.get("pagination_debug_key")
                            # Try to find an array in the response to debug
                            for key, value in response_data.items():
                                if isinstance(value, list) and value:
                                    file_logger.info(f"Page {page_count}: {key} array has {len(value)} items")
                                    file_logger.info(f"Page {page_count}: First {debug_key}: {value[0].get(debug_key, 'N/A')}")
                                    file_logger.info(f"Page {page_count}: Last {debug_key}: {value[-1].get(debug_key, 'N/A')}")
                                    break
                        
                        # Stop pagination if no nextToken or reached max pages
                        if not next_token or next_token == "" or pagination_key not in response_data:
                            file_logger.info(f"No more pages - stopping pagination at page {page_count}")
                            break
                    else:
                        break
                
                # Store all paginated responses as array
                if len(all_responses) >= 1:
                    response_data = all_responses
                    file_logger.info(f"Collected {len(all_responses)} paginated responses as array")
                    
                    # Debug: Count total items across all pages if debug key is configured
                    if param_data.get("pagination_debug_key"):
                        debug_key = param_data.get("pagination_debug_key")
                        total_items = 0
                        all_debug_refs = []
                        
                        for page_response in all_responses:
                            for key, value in page_response.items():
                                if isinstance(value, list):
                                    total_items += len(value)
                                    all_debug_refs.extend([item.get(debug_key) for item in value if isinstance(item, dict)])
                        
                        unique_debug_refs = set(all_debug_refs)
                        file_logger.info(f"Total items across all pages: {total_items}")
                        file_logger.info(f"Total {debug_key}: {len(all_debug_refs)}, Unique: {len(unique_debug_refs)}")
                        if len(all_debug_refs) != len(unique_debug_refs):
                            file_logger.warning(f"Duplicate {debug_key} detected across pages!")

            else:
                # No pagination - single request
                start_time_test = time.time()
                response, response_data, actual_status_code, elapsed_time_req, attempt, error_message = self.request_logic(
                    url, headers, payload, think_time, method, file_logger, max_retries, 
                    backoff_factor, response_threshold_time, param_data, expected_status_code, token, cert_file_path
                )
            if method == "POST":
                try:
                    primary_key = param_data.get("primary_key", "")
                    secondary_key = param_data.get("secondary_key", "")

                    if not primary_key:
                        primary_value = ""
                    else:   
                        primary_value = self.get_nested_value(response_data, primary_key)
                        if not primary_value:
                            primary_value = self.get_nested_value(response_data.get(param_data.get("response_payload")), primary_key)
                            if not primary_value:
                                file_logger.warning(f"Skipping test case '{test_case_name}' due to missing value for '{primary_key}'.")
                                primary_value = ""

                        secondary_value = None
                        if secondary_key:
                            secondary_value = self.get_nested_value(response_data, secondary_key)
                            if not secondary_value:
                                secondary_value = self.get_nested_value(response_data.get(param_data.get("response_payload")), secondary_key)
                                if not secondary_value:
                                    file_logger.warning(f"Skipping test case '{test_case_name}' due to missing value for '{secondary_key}'.")
                                    secondary_value = ""
                except KeyError as e:
                    file_logger.error(f"KeyError processing dynamic key in test case '{test_case_name}': {e}")
                    return (False, None, None)
                except Exception as e:
                    file_logger.error(f"Unexpected error processing dynamic key in test case '{test_case_name}': {e}")
                    return (False, None, None)
                    
            self.avg_req_time += elapsed_time_req
          # Log request and response with thread-safety
            thread_id = threading.get_ident()
            with self.lock:
                file_logger.info(f"Thread-{thread_id}: Test Case '{test_case_name}'")
                file_logger.info(f"Thread-{thread_id}: Elapsed time for request: {elapsed_time_req:.2f} seconds")

            # Dynamically prepare arguments for comparison function
            local_vars = locals()
            contract_result = {}
            
            # Determine API test status based on status code match
            api_test_passed = (expected_status_code == actual_status_code)
            
            if error_message:
                file_logger.info(f"API test failed: {error_message}")
            elif api_test_passed and (isinstance(response_data, dict) and response_data.get("error")):
                file_logger.info(f"API test passed with error response: {response_data.get('error')}")
            
            # Always run contract testing for contract_data_post.json
            if self.filename_pattern == "contract_data_post.json":
                try:
                    args_contract = self.prepare_arguments(self.compare_contract, local_vars)
                    with self.lock:
                        contract_result = self.compare_contract(*args_contract)
                        if not hasattr(self, 'contract_results'):
                            self.contract_results = []
                        self.contract_results.append(contract_result)
                        
                        contract_test_passed = contract_result.get('contractStatus') == 'passed'
                        if not contract_test_passed:
                            file_logger.warning(f"Contract validation failed for test case '{test_case_name}': {contract_result}")
                        else:
                            file_logger.info(f"Contract validation passed for test case '{test_case_name}'")
                except Exception as e:
                    file_logger.error(f"Error in contract testing for test case '{test_case_name}': {e}")
                    contract_result = {"testKey": test_key, "contractStatus": "error", "error": str(e)}
                    contract_test_passed = False
                
                # Overall test passes only if both API and contract tests pass
                comparison_passed = api_test_passed and contract_test_passed
                exact_matches = []
                partial_matches = []
                unmatched_attributes = []
            else:
                # Non-contract testing flow
                if error_message:
                    unmatched_attributes = [error_message]
                    comparison_passed = False
                    exact_matches = []
                    partial_matches = []
                elif api_test_passed and (isinstance(response_data, dict) and response_data.get("error")):
                    unmatched_attributes = [response_data.get("error")]
                    comparison_passed = True
                    exact_matches = []
                    partial_matches = []
                else:
                    try:
                        args = self.prepare_arguments(compare_response.compare_response, local_vars)
                        with self.lock:
                            result = compare_response.compare_response(*args)
                            if result is None:
                                file_logger.error(f"Comparison function returned None for test case '{test_case_name}'")
                                comparison_passed, exact_matches, partial_matches, unmatched_attributes = False, [], [], ["Comparison failed"]
                            else:
                                comparison_passed, exact_matches, partial_matches, unmatched_attributes = result
                    except Exception as e:
                        file_logger.error(f"Error comparing JSON response for test case '{test_case_name}': {e}")
                        comparison_passed, exact_matches, partial_matches, unmatched_attributes = False, [], [], [str(e)]
                        with self.lock:
                            self.summary['failed'] += 1
                        return (False, None, None)

            end_time_test = time.time()
            test_end_time = datetime.now(timezone.utc).isoformat()
            elapsed_time_cmp = end_time_test - start_time_test
            self.avg_test_time += elapsed_time_cmp

            with self.lock:
                file_logger.info(f"Thread-{thread_id}: Elapsed time for test case: {elapsed_time_cmp:.2f} seconds\n")

            if param_data["test_description"]:
                test_description = param_data["test_description"]
                test_description = test_description.format(test = test_case_name)
            else:
                test_description = test_case["test_description"]
            
            # Create analytics data
            analytics_data = self.create_analytics_data(
                test_case_name=test_case_name,
                test_key = test_key,
              # ownerentityid = ownerentityid,
                test_description = test_description,
                status="passed" if comparison_passed else "failed",
                actual_status_code=actual_status_code,
                attempt = attempt + 1,
                request_url = url,
                primary_id = primary_value if primary_value else "",
                secondary_id = secondary_value if secondary_value else "",
                request_payload = payload,
                response_payload=response_data,
                elapsed_time_req=elapsed_time_req,
                elapsed_time_test=elapsed_time_cmp,
            )

            if self.filename_pattern == "contract_data_post.json":
                results_data = self.create_analytics_data(
                    testKey=test_key,
                    testCaseName=test_case_name,
                    testDescription=test_description,
                    endpointMethod=f"{self.endpoints[0]}-{self.method.lower()}",
                    attempt=attempt + 1,
                    startDate=test_start_time,
                    finishDate=test_end_time,
                    responseTime=elapsed_time_req,
                    testCaseTime=elapsed_time_cmp,
                    payload=payload,
                    response=response_data,
                    # status="passed" if api_test_passed else "failed",
                    contractTestResult=contract_result,
                    overallStatus="passed" if comparison_passed else "failed"
                )
            else:
                results_data = self.create_analytics_data(
                    testKey =  test_key,
                    testCaseName = test_case_name,
                    testDescription = test_description,
                    endpointMethod = f"{self.endpoints[0]}-{self.method.lower()}",
                    attempt = attempt + 1,
                    startDate = test_start_time,
                    finishDate = test_end_time,    
                    responseTime = elapsed_time_req,
                    testCaseTime = elapsed_time_cmp,
                    payload = payload,
                    response = response_data,
                    exactMatches = len(exact_matches),
                    exactMatchesAttributes = exact_matches,
                    partialMatches = len(partial_matches),
                    partialMatchesAttributes = partial_matches,
                    unmatched = len(unmatched_attributes),
                    unmatchedAttributes = unmatched_attributes,
                    status = "passed" if comparison_passed else "failed"
                )

            # Update summary counts
            with self.lock:
                if comparison_passed:
                    self.summary['passed'] += 1
                    return (True, analytics_data, results_data)
                else:
                    self.summary['failed'] += 1
                    return (False, analytics_data, results_data)

        except Exception as e:
            file_logger.error(f"Unexpected error processing test case '{test_case_name}': {e}")
            file_logger.error(traceback.format_exc())
            raise
            with self.lock:
                self.summary['failed'] += 1
            return (False, None, None)

    def request_logic(self, url, headers, payload, think_time, method, file_logger, max_retries, backoff_factor, response_threshold_time, param_data, expected_status_code, token, cert_file_path=None):
        """
        Handles the request logic for any HTTP method including retries and backoff for transient errors.

        Args:
            url (str): The API endpoint URL.
            headers (dict): Headers to include in the request.
            payload (dict): The payload data to send with the request.
            think_time (float): Time to wait before sending the request.
            method (str): HTTP method for the request ('POST', 'GET', 'PUT', 'PATCH', 'DELETE').
            cert_file_path (str, optional): Path to the certificate file for certificate-based authentication.
            max_retries (int): Maximum number of retries for transient errors.
            backoff_factor (int): Multiplier for exponential backoff delay.
            response_threshold_time (int): Timeout threshold to determine failure.

        Returns:
            tuple: (response object, response data, status code, elapsed request time, last attempt number)
        """

        print(url)  # Debug log to confirm the URL
        payload_str = json.dumps(payload) if payload else None
        file_logger.info(f"Raw request - URL: {url}")
        file_logger.info(f"Raw request - Headers: {headers}")
        file_logger.info(f"Raw request - Payload string: {payload_str}")
        thread_id = threading.get_ident()
        expected_non_empty_keys = param_data.get("expected_non_empty_keys", [])

        # Delay for the configured think time
        time.sleep(think_time)

        response, response_data, actual_status_code, elapsed_time_req, error_message = None, None, None, 0, None  # Default values

        for attempt in range(max_retries):
            try:
                # Try to refresh token if needed
                if token:
                    ref_token, expires_in = self.auth_handler.refresh_token()
                    if not ref_token:
                        error_message = "Failed to refresh token"
                        file_logger.error(f"Thread-{thread_id}: {error_message}")
                        return None, None, None, 0, attempt, error_message

                    # Update Authorization header with fresh token
                    # headers["Authorization"] = headers["Authorization"].format(access_token=ref_token)
                    headers["Authorization"] = f"Bearer {ref_token}"
                
                # Record the request start time
                start_time_req = time.time()

                # Prepare request arguments
                cert_path = cert_file_path if cert_file_path else False
                request_args = {
                    'url': url,
                    'headers': headers,
                    'data': payload_str if payload_str is not None else None,
                    'verify': cert_path,
                }
                safe_headers = {k: ('****' if 'authorization' in k.lower() else v) for k, v in headers.items()}
                file_logger.info(f"Thread-{thread_id}: Sending {method} request to URL: {url}")
                file_logger.info(f"Thread-{thread_id}: Headers: {json.dumps(safe_headers, indent=2)}")
                if payload_str:
                    file_logger.info(
                        f"Thread-{thread_id}: Request Payload: {json.dumps(json.loads(payload_str), indent=2)}")
                # Send the appropriate HTTP request
                if method.upper() == 'POST':
                    response = requests.post(**request_args)
                elif method.upper() == 'GET':
                    del request_args['data']  # Remove data for GET requests
                    response = requests.get(**request_args)
                elif method.upper() == 'SNS':
                    del request_args['data']  # Remove data for SNS requests
                    response = requests.get(**request_args)
                elif method.upper() == 'PUT':
                    response = requests.put(**request_args)
                elif method.upper() == 'PATCH':
                    response = requests.patch(**request_args)
                elif method.upper() == 'DELETE':
                    # Only remove data if DELETE doesn't have payload
                    if not param_data.get("has_payload", False):
                        del request_args['data']  # Remove data for DELETE requests without payload
                    response = requests.delete(**request_args)
                else:
                    error_message = f"Unsupported HTTP method: {method}"
                    file_logger.error(f"Thread-{thread_id}: {error_message}")
                    return None, None, None, 0, attempt, error_message

                # Record the request end time
                end_time_req = time.time()
                elapsed_time_req = end_time_req - start_time_req

                # Attempt to parse the response as JSON
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = response.text

                actual_status_code = response.status_code

                # Check if request took longer than threshold
                if param_data.get("response_threshold_time"):
                    if elapsed_time_req > response_threshold_time:
                        actual_status_code = 408  # Marking it as a timeout failure
                        error_message = f"Request exceeded threshold time ({elapsed_time_req:.2f}s > {response_threshold_time}s)"
                        file_logger.error(f"Test Failed: {error_message}")
                        return response, response_data, actual_status_code, elapsed_time_req, attempt, error_message

                # Call is_response_empty to check if response is considered empty
                if expected_non_empty_keys and self.is_response_empty(response_data, expected_non_empty_keys):
                    actual_status_code = 204  # Treat as empty response
                    error_message = f"Response is empty but status code is pass."
                    file_logger.warning(f"Thread-{thread_id}: {error_message}")

                # Log and handle successful responses
                if actual_status_code == expected_status_code:
                    file_logger.info(f"Thread-{thread_id}: Request succeeded on attempt {attempt + 1}.")
                    return response, response_data, actual_status_code, elapsed_time_req, attempt, error_message
                else:
                    file_logger.warning(f"Thread-{thread_id}: Attempt {attempt + 1} failed with status {actual_status_code}, Expecting {expected_status_code}.")

            except requests.RequestException as e:
                error_message = f"{e}"
                file_logger.error(f"Thread-{thread_id}: Attempt {attempt + 1} encountered an error: {error_message}")

            # Apply exponential backoff before retrying
            if attempt < max_retries - 1:
                file_logger.info(f"Thread-{thread_id}: Retrying after {backoff_factor} seconds...")
                time.sleep(backoff_factor)

        # If all retries fail, log and return failure
        error_message = f"Test failed with status {actual_status_code}, Expecting {expected_status_code}"
        file_logger.error(f"Thread-{thread_id}: All attempts failed within {max_retries} attempts for URL: {url}.")
        return response, response_data, actual_status_code, elapsed_time_req, attempt, error_message

    def is_response_empty(self, response_data, expected_non_empty_keys):
        """
        Checks if the response data is empty based on expected keys.

        Args:
            response_data (dict): The API response payload.
            expected_non_empty_keys (list): List of keys expected to be non-empty.

        Returns:
            bool: True if response is considered empty, False otherwise.
        """
        # If "response" is in expected_non_empty_keys, check the entire response
        if "response" in expected_non_empty_keys:
            if not isinstance(response_data, dict) or not response_data:
                return True  # Response is explicitly expected but empty or invalid

        # Check individual keys
        for key in expected_non_empty_keys:
            value = self.get_nested_value(response_data, key)
            if value:  # If any expected key has a value, response is not empty
                return False 

        return True  # All expected keys are empty

    def create_analytics_data(self, **params):
        """
        Creates structured analytics data for a test case with dynamic parameters.

        Parameters:
        - **params: All key-value pairs for test case analytics, including both required and dynamic parameters.

        Returns:
        - dict: Structured analytics data.
        """
        analytics_data = {}

        # Loop through all the provided parameters
        for key, value in params.items():
            analytics_data[key] = value

        return analytics_data

    def create_summary_endpoint(self, result, start_time_endpoint, param_data, subfolder):    
        """
        Generates and logs a summary for a specific API endpoint after all test cases have been processed.

        Parameters:
        ----------
        result : dict
            Dictionary containing test case results for the endpoint:
            - `passed` (int): Number of passed test cases.
            - `failed` (int): Number of failed test cases.
        start_time_endpoint : float
            Timestamp marking the start time of the endpoint processing.
        param_data : dict
            Dictionary containing configuration parameters, including the log template.
        subfolder : str
            The name of the endpoint or subfolder being processed.

        Functionality:
        --------------
        - Calculates total tests, pass rate, and elapsed time for the endpoint.
        - Logs a summary message based on the `summary_log_template` from `param_data`.

        Notes:
        ------
        - Pass rate is calculated as `(passed / total) * 100`, rounded to two decimal places.
        - Elapsed time is logged in seconds.
        """
        total_tests = result['passed'] + result['failed']
        pass_rate = (result['passed'] / total_tests) * 100 if total_tests > 0 else 0
        elapsed_time_endpoint = time.time() - start_time_endpoint

        logging.info(param_data.get("summary_log_template").format(
            context=f"Endpoint {subfolder}",
            total_req=total_tests,
            passed=result['passed'],
            failed=result['failed'],
            rate=f"{pass_rate:.2f}%",
            elapsed_time=f"{elapsed_time_endpoint:.2f}"
        ))
        
        try:
            self.collected_summary = {
                "endpoint": self.endpoints[0],
                "method": self.method.lower(),
                "passed": result['passed'],
                "failed": result['failed'],
                "total": total_tests,
                "pass rate %": f"{pass_rate:.2f}%",
                "average_response_time": self.avg_req_time/total_tests,
                "average_test_case_time": self.avg_test_time/total_tests
            }
            return pass_rate
        except ZeroDivisionError:
            logging.error("Divide by zero error")

    def create_summary_overall(self, overall_start_time): 
        """
        Generates and logs an overall summary of all test cases after processing all endpoints.

        Parameters:
        ----------
        summary : dict
            Dictionary containing cumulative test results:
            - `passed` (int): Total number of passed test cases.
            - `failed` (int): Total number of failed test cases.
        overall_start_time : float
            Timestamp marking the start time of the overall processing.

        Functionality:
        --------------
        - Calculates total tests, overall pass rate, and total elapsed time.
        - Logs a summary message with cumulative results and overall performance metrics.

        Notes:
        ------
        - Pass rate is calculated as `(passed / total) * 100`, rounded to two decimal places.
        - Elapsed time is logged in seconds.
        """
        total_tests = self.summary['passed'] + self.summary['failed']
        overall_pass_rate = (self.summary['passed'] / total_tests) * 100 if total_tests > 0 else 0
        elapsed_time_overall = time.time() - overall_start_time

        log_message = f"Summary for Overall:\nOverall Total Requests: {total_tests}\nOverall Test Cases Passed: {self.summary['passed']}\nOverall Test Cases Failed: {self.summary['failed']}\nPass Rate Percentage: {overall_pass_rate:.2f}%\nElapsed Time for Overall: {elapsed_time_overall:.2f} seconds\n"
        logging.info(log_message)

    # Recursive function to fetch nested values, including handling list indices
    def get_nested_value(self, data, key_path):
        """
        Recursively retrieves a nested value from a dictionary or list structure using a dotted key path.

        Supports navigation through both dictionaries and lists. If any key or index is invalid, 
        or if the path leads to a non-traversable type, the function returns None.

        Parameters:
        ----------
        data : dict | list
            The nested data structure (dictionary or list) to extract values from.
        
        key_path : str
            The path to the desired value using dot notation. For example, 'user.address.city' 
            or 'users.0.name' to access list indices.

        Returns:
        -------
        any | None
            The value found at the nested location, or None if the key path is invalid.
        """
        keys = key_path.split('.')  # Split keys by a delimiter (e.g., '.')
        for key in keys:
            try:
                # Check if key refers to a list index
                if isinstance(data, list) and key.isdigit():
                    index = int(key)
                    if index < len(data):
                        data = data[index]
                    else:
                        return None  # Index out of range
                elif isinstance(data, dict):
                    data = data.get(key, {})
                else:
                    return None  # Stop if key doesn't exist or data is neither dict nor list
            except (KeyError, IndexError, TypeError):
                return None  # Handle unexpected errors gracefully
        return data
    
    def generate_json_report(self, param_data):
        """
        Generates a JSON report directory structure for a given API execution context.

        This function constructs a file path based on the project root, application name, 
        endpoint, and HTTP method. It then ensures the appropriate output folder exists 
        for storing the report data.

        The file itself is not written here — this function only prepares the path 
        and folder for future report writing.

        Side Effects:
        -------------
        - Creates a directory under `results/<application>/<endpoint>_<method>/`
        if it does not already exist.

        Attributes Used:
        ----------------
        self.application : str
            The name of the application being tested.
        self.endpoints : list
            A list of endpoint strings; only the first one is used in naming.
        self.method : str
            HTTP method (e.g., 'GET', 'POST') used to determine folder and filename.

        Returns:
        --------
        None
        """
        # Define the output folder and file
        end_time = datetime.now(timezone.utc).isoformat()
        if self.filename_pattern== "contract_data_post.json":
            output_folder = os.path.join(
                self.project_root_path,
                "results",
                f"contract_testing",
                self.application,
                f"{self.endpoints[0]}_{self.method.lower()}"
            )
            output_file = os.path.join(output_folder, f"{self.endpoints[0]}_{self.method.lower()}_report_data.json")
        else:
            output_folder = os.path.join(
                self.project_root_path,
                "results",
                self.application,
                f"{self.endpoints[0]}_{self.method.lower()}"
            )
            
            output_file = os.path.join(output_folder, f"{self.endpoints[0]}_{self.method.lower()}_report_data.json")

        # Create the folder structure if it doesn't exist
        try:
            os.makedirs(output_folder, exist_ok=True)  # This ensures intermediate folders are created
        except Exception as e:
            logging.error(f"Failed to create directory {output_folder}: {e}")
            return

        # Create the JSON report
        data = {}
        try:
            data["info"] = {
                "testSuite": "SmartTest API",
                "summary": f"Test Report for {self.application} - {self.endpoints[0]} {self.method.lower()}",
                #"jira_user": self.env_file["JIRA_USER"],
                "jira_user" : os.getenv("JIRA_USER"),
                "startDate": self.start_time,
                "finishDate": end_time,
                "duration": self.cal_duration(self.start_time, end_time),
                "testPlanKey": os.getenv("TEST_PLAN_KEY"),
                "testExecutionKey": os.getenv("TEST_EXECUTION_KEY"),
                "project": os.getenv("JIRA_PROJECT_KEY"),
                "testExecutionId": os.getenv("TEST_EXECUTION_ID"),
                "CI_JOB_ID": os.getenv("CI_JOB_ID"),
                "CI_JOB_URL": os.getenv("CI_JOB_URL"),
                "environment": os.getenv("ENVIRONMENT"),
                "results": self.collected_summary
            }
            data["tests"] = self.collected_responses

            # Write the data to a JSON file
            with open(output_file, 'w') as json_file:
                json.dump(data, json_file, indent=4)

            logging.info(f"Report generated successfully: {output_file}")
        except Exception as e:
            logging.error(f"Failed to generate JSON report: {e}")
            
    def cal_duration(self, start_time, end_time):
        """
        Calculates the duration between two ISO-formatted timestamps and returns it as a human-readable string.

        Parameters:
        -----------
        start_time : str
            The start time in ISO 8601 format (e.g., "2025-06-11T12:00:00+00:00").
        
        end_time : str
            The end time in ISO 8601 format (e.g., "2025-06-11T12:45:30+00:00").

        Returns:
        --------
        str
            A formatted string representing the duration in hours, minutes, and seconds.
            Format: "Xh Ym Zs"

        Example:
        --------
        >>> cal_duration("2025-06-11T12:00:00+00:00", "2025-06-11T13:30:45+00:00")
        '1h 30m 45s'
        """
        # Parse the timestamps
        start_time = datetime.fromisoformat(start_time)
        end_time = datetime.fromisoformat(end_time)

        # Calculate the duration as a timedelta
        duration = end_time - start_time

        # Extract hours, minutes, and seconds from the duration
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Format the duration as "1h 10m 10s"
        formatted_duration = f"{hours}h {minutes}m {seconds}s"
    
        return formatted_duration
