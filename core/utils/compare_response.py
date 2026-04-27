import os
import sys
import re

project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root_path)

from core.utils import compare_functions, compare_utils, utils

def choose_validators(endpoint, response_data, method):
    """
    Selects appropriate validation functions based on response content and method type.

    If the response is empty or missing, it defaults to status code-only validation.
    Otherwise, it uses the default field comparison validator.
    Additionally, for SNS-related methods (excluding 'snsgigyacustomer'), 
    a booking status validator is also added.

    Args:
        endpoint (str): The API endpoint under test.
        response_data (dict or None): The response received from the API call.
        method (str): HTTP method or logical method type (e.g., 'sns').

    Returns:
        list: A list of validator functions to be executed for the given scenario.
    """
    validator = []

    if not response_data or (isinstance(response_data, dict) and not response_data):
        validator.append(compare_functions.compare_status_code_only)
    else:
        validator.append(compare_functions.compare_default)

    # If SNS and method is 'sns', add status check
    if method.lower() == "sns":
        validator.append(compare_functions.check_booking_status_validator)

    return validator

def compare_response(
    test_case_name,
    thread_id,
    payload,
    application,
    endpoint,
    response_data,
    additional_fields,
    expected_status_code,
    actual_status_code,
    file_logger,
    test_key,
    method,
    topic = None
):
    """
    Executes all applicable response validators for the given test case.

    Based on the endpoint, method, and response content, selects the necessary
    validators (e.g., status code check, payload comparison, booking status validation),
    runs them sequentially, and aggregates their results.

    Args:
        test_case_name (str): Identifier for the test case.
        thread_id (int): Identifier for parallel test thread.
        payload (dict): Payload used in the API request.
        application (str): Application name to resolve test parameters.
        endpoint (str): API endpoint under test.
        response_data (dict): Actual response returned from the API.
        additional_fields (dict): Fields to dynamically add or check in the payload.
        expected_status_code (int): Expected HTTP response code.
        actual_status_code (int): Actual HTTP response code received.
        file_logger (logging.Logger): Logger instance for tracking test execution.
        test_key (str): Unique key for identifying test data or history.
        method (str): HTTP method or logical action type (e.g., 'sns').
        topic (str, optional): Kafka topic or other domain-specific tag used for extra checks.

    Returns:
        tuple:
            - overall_success (bool): True if all validators pass.
            - all_exact_matches (list): Flattened keys that exactly matched.
            - all_partial_matches (list): Flattened keys matched via partial logic.
            - all_unmatched_attributes (list): Keys or attributes that failed validation.
    """

    file_logger.info(f"Starting comparison for test case: {test_case_name}")

    validators = choose_validators(endpoint, response_data, method)

    overall_success = True
    all_exact_matches = []
    all_partial_matches = []
    all_unmatched_attributes = []

    for validator in validators:
        success, exact_matches, partial_matches, unmatched_attributes = validator(
            test_case_name,
            thread_id,
            payload,
            application,
            endpoint,
            response_data,
            additional_fields,
            expected_status_code,
            actual_status_code,
            file_logger,
            test_key,
            method, 
            topic
        )
        overall_success = overall_success and success
        all_exact_matches.extend(exact_matches)
        all_partial_matches.extend(partial_matches)
        all_unmatched_attributes.extend(unmatched_attributes)

    return overall_success, all_exact_matches, all_partial_matches, all_unmatched_attributes
