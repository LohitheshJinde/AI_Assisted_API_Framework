import re
from core.utils import compare_utils, utils

def compare_default(
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
    Compares the flattened API response with the expected payload data for test validation.

    This function handles dynamic comparison logic including additional fields,
    exclusions, and fallback payloads from related test cases based on metadata.

    Args:
        test_case_name (str): Name of the test case used for deriving test-specific values.
        thread_id (int): Identifier for the running test thread, used for logging.
        payload (dict): The original request payload used for the test.
        application (str): The application key to fetch configuration parameters.
        endpoint (str): The API endpoint under test.
        response_data (dict): The actual response received from the API.
        additional_fields (dict): Custom fields to inject or verify in the payload.
        expected_status_code (int): Expected HTTP status code.
        actual_status_code (int): Actual HTTP status code from the response.
        file_logger (logging.Logger): Logger instance for logging test progress and result.
        test_key (str): Unique key identifying the current test (used in post-response resolution).
        method (str): HTTP method (GET, POST, etc.).
        topic (str, optional): Kafka topic name if required for contextual filtering.

    Returns:
        tuple:
            - success (bool): True if test passes based on attribute and status validation.
            - exact_matches (list): List of keys that exactly match between payload and response.
            - partial_matches (list): Tuples of keys that matched via partial key matching.
            - unmatched_attributes (list): Attributes that failed validation or were missing.
    """
    param_data = utils.load_params("param.json", application)

    status_success = param_data.get(endpoint, {}).get(method, {}).get("expected_status_code_success", 200)
    status_failure = param_data.get(endpoint, {}).get(method, {}).get("expected_status_code_failure", 400)

    if status_success is None:
        status_success = param_data.get(endpoint, {}).get("expected_status_code_success")
    if status_failure is None: 
        status_failure = param_data.get(endpoint, {}).get("expected_status_code_failure")

    default_excluded_fields = {'version', 'customerversion', 'customerlevel', 'lifecyclestatus', 'category'}
    excluded_fields = param_data.get(endpoint, {}).get(method, {}).get("excluded_fields", None)
    excluded_fields = set(excluded_fields or []).union(default_excluded_fields)

    compare_endpoint = param_data.get(endpoint, {}).get(method, {}).get("compare_endpoint", {})
    compare_filepattern = param_data.get(endpoint, {}).get(method, {}).get("compare_filepattern", {})
    if compare_endpoint and compare_filepattern:
        updated_payload = utils.find_associated_payload_from_respective_post_testcases(application, test_key, compare_endpoint, compare_filepattern)
        file_logger.info(f"Using {compare_endpoint} testdata with filename pattern {compare_filepattern} for comparison")
        payload = updated_payload.get("response_payload") or updated_payload.get("payload")

    additional_fields = param_data.get(endpoint, {}).get(method, {}).get("additional_fields", {})
    if additional_fields:
        payload = utils.add_attributes_to_payload(payload, additional_fields, endpoint)

    flattened_response = {k.lower(): compare_utils.normalize_value(v) for k, v in compare_utils.flatten_json(response_data).items()}
    flattened_payload = {k.lower(): compare_utils.normalize_value(v) for k, v in compare_utils.flatten_json(payload).items()}

    flattened_response = {k: v for k, v in flattened_response.items() if k not in excluded_fields}
    flattened_payload = {k: v for k, v in flattened_payload.items() if k not in excluded_fields}

    file_logger.info(f"Thread-{thread_id}: Comparing response and payload.")
    file_logger.info(f"Flattened Payload: {flattened_payload}")
    file_logger.info(f"Flattened Response: {flattened_response}")
    file_logger.info(f"Expected Status: {expected_status_code}, Actual Status: {actual_status_code}")


    if expected_status_code != actual_status_code:
        file_logger.error(f"Status Code Mismatch: Expected {expected_status_code}, Got {actual_status_code}")
        return False, [], [], []

    exact_matches = []
    partial_matches = []
    unmatched_attributes = []
    
    # Explicitly compare resolved additional fields
    for field_key in additional_fields:
        key_lower = field_key.lower()
        expected_value = flattened_payload.get(key_lower)  # pull resolved value from updated payload
        
        # Look for exact or partial match in the flattened response
        matched_response_key = None
        for resp_key in flattened_response:
            if resp_key.endswith(f".{key_lower}") or resp_key == key_lower:
                matched_response_key = resp_key
                break
            
        if not matched_response_key:
            file_logger.warning(f"Additional field '{field_key}' not found in response.")
            unmatched_attributes.append(field_key)
        elif flattened_response[matched_response_key] != expected_value:
            file_logger.warning(f"Mismatch in additional field '{field_key}': expected '{expected_value}', got '{flattened_response[matched_response_key]}'")
            unmatched_attributes.append(field_key)

    if actual_status_code == status_success:
        for response_path, response_value in flattened_response.items():
            if response_path in flattened_payload:
                if flattened_payload[response_path] == response_value:
                    exact_matches.append(response_path)
            else:
                matched_payload_path = compare_utils.compare_partial(response_path, flattened_payload)
                if matched_payload_path and flattened_payload[matched_payload_path] == response_value:
                    partial_matches.append((response_path, matched_payload_path))

        file_logger.info(f"Exact Matches: {len(exact_matches)}")
        file_logger.info(f"Exact Matched Attributes: {exact_matches}")
        file_logger.info(f"Partial Matches: {len(partial_matches)}")
        file_logger.info(f"Partial Matched Attributes: {partial_matches}")

        if unmatched_attributes:
            file_logger.warning(f"Unmatched Attributes: {len(unmatched_attributes)}")
            file_logger.info(f"Unmatched: {unmatched_attributes}")
            file_logger.error(f"Test failed: Unmatched attributes found.")
            return False, exact_matches, partial_matches, unmatched_attributes

        file_logger.info(f"Test passed: All key attributes match.")
        return True, exact_matches, partial_matches, unmatched_attributes

    elif actual_status_code == status_failure:
        # error_message = flattened_response.get("error.message", "").lower()
        # match = re.search(r'=(.*)', test_case_name)
        # test_value = match.group(1).strip().lower() if match else ""

        # file_logger.info(f"Could not extract test value from test case name: {test_case_name} but status code matches")
        # file_logger.info(f"Test passed")
        file_logger.info(f"Test case Passed: {test_case_name}")
        return True, [], [], []


def compare_status_code_only(
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
    Validates API response based on HTTP status code only.

    This function compares the expected and actual status codes,
    and optionally accepts test failure when the actual status matches a predefined failure status.

    Args:
        test_case_name (str): Name of the test case for logging and identification.
        thread_id (int): Identifier for the current execution thread.
        payload (dict): The input payload sent to the API.
        application (str): Application identifier used to load test configuration.
        endpoint (str): API endpoint under test.
        response_data (dict): Full response returned by the API.
        additional_fields (dict): Reserved for compatibility; not used in this function.
        expected_status_code (int): Expected HTTP status code for a passing test.
        actual_status_code (int): Actual HTTP status code received from the API.
        file_logger (logging.Logger): Logger instance used for status tracking.
        test_key (str): Unique identifier for the test.
        method (str): HTTP method used for the request.
        topic (str, optional): Optional Kafka topic name (not used here).

    Returns:
        tuple:
            - success (bool): True if the status codes match expectations.
            - exact_matches (list): Always empty (not applicable).
            - partial_matches (list): Always empty (not applicable).
            - unmatched_attributes (list): Always empty (not applicable).
    """
    param_data = utils.load_params("param.json", application)

    status_success = param_data.get(endpoint, {}).get(method, {}).get("expected_status_code_success", 200)
    status_failure = param_data.get(endpoint, {}).get(method, {}).get("expected_status_code_failure", 400)

    if status_success is None:
        status_success = param_data.get(endpoint, {}).get("expected_status_code_success")
    if status_failure is None: 
        status_failure = param_data.get(endpoint, {}).get("expected_status_code_failure")

    file_logger.info(f"Thread-{thread_id}: Payload: {payload}")
    file_logger.info(f"Thread-{thread_id}: Response: {response_data}")
    file_logger.info(f"Thread-{thread_id}: Expected Status: {expected_status_code}, Actual Status: {actual_status_code}")

    if actual_status_code == status_failure:
        return True, [], [], []

    if expected_status_code != actual_status_code:
        file_logger.error(f"Thread-{thread_id}: Status Code Mismatch. Expected {expected_status_code}, got {actual_status_code}. Test FAILED.")
        return False, [], [], []

    if actual_status_code == status_success:
        file_logger.info(f"Thread-{thread_id}: Test PASSED. Status codes match.")
        return True, [], [], []
    else:
        file_logger.error(f"Thread-{thread_id}: Test FAILED. Unexpected status code.")
        return False, [], [], []

from core.utils import compare_utils

def check_booking_status_validator(
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
):
    """
    Validates the booking status in the API response based on the provided topic.

    This function uses a utility to determine if the booking status is valid
    and logs the result accordingly. The test passes only if the status is deemed valid.

    Args:
        test_case_name (str): Name of the test case, used for context.
        thread_id (int): Thread ID for parallel execution tracking.
        payload (dict): Request payload sent to the API (not used here).
        application (str): Name of the application (not used here).
        endpoint (str): API endpoint under test (not used here).
        response_data (dict): Response returned from the API call.
        additional_fields (dict): Reserved for compatibility; not used here.
        expected_status_code (int): Expected HTTP status code (not validated here).
        actual_status_code (int): Actual HTTP status code from the response (not validated here).
        file_logger (logging.Logger): Logger for capturing logs and results.
        test_key (str): Identifier for the specific test case (not used here).
        method (str): HTTP method used (not used here).
        topic (str): Kafka topic or domain used to determine the expected booking behavior.

    Returns:
        tuple:
            - success (bool): True if booking status is valid; False otherwise.
            - exact_matches (list): Empty (not applicable).
            - partial_matches (list): Empty (not applicable).
            - unmatched_attributes (list): Empty (not applicable).
    """
    file_logger.info(f"Thread-{thread_id}: Checking status.")

    is_valid, error_message, status = compare_utils.check_booking_status(response_data, topic)

    if not is_valid:
        file_logger.error(f"Status validation FAILED: {error_message}")
        return False, [], [], []

    file_logger.info(f"Status validation PASSED: {status}")
    return True, [], [], []
