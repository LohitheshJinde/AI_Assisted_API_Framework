from difflib import SequenceMatcher
import numpy as np
from dateutil.parser import parse

def is_datetime(value):
    """
    Determines whether the given value is a valid datetime string.
    Attempts to parse the value using dateutil's parser. Excludes purely numeric
    strings (e.g., timestamps or IDs) which might otherwise be misinterpreted.

    Args:
        value (Any): The value to be checked.
    """
    if not isinstance(value, str):
        return False  # Only strings can be datetime
    
    # Filter out purely numeric strings (like "5672540665")
    if value.isdigit():
        return False
    
    try:
        parse(value)  # Attempt to parse as datetime
        return True
    except (ValueError, TypeError):
        return False

def normalize_datetime(value):
    """
    Converts a datetime string to ISO 8601 format without timezone. Returns original value if not applicable.

    Args:
        value (Any): The value to normalize. Typically a string representing a datetime.

    Notes:
        - Uses `dateutil.parser.parse` to support flexible date formats.
        - Intended for use in data normalization or comparison routines where consistent
          datetime formatting is required.
    """
    if not isinstance(value, str):
        return value  # Return the value as is if it's not a string
    try:
        return parse(value).replace(tzinfo=None).isoformat()
    except (ValueError, TypeError):
        return value

def flatten_json(nested_json, parent_key='', sep='.'):
    """
    Recursively flattens a nested JSON/dict structure.
    
    Args:
        nested_json (dict or list): The JSON or dictionary to flatten.
        parent_key (str): The base key for the current level.
        sep (str): Separator to use in flattened keys.
    
    Returns:
        dict: A flattened dictionary.
    """
    if not isinstance(nested_json, (dict, list)):
        # Base case for primitive types
        return {parent_key: nested_json} if parent_key else {}

    items = []
    if isinstance(nested_json, dict):
        for key, value in nested_json.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            items.extend(flatten_json(value, new_key, sep=sep).items())
    elif isinstance(nested_json, list):
        for i, item in enumerate(nested_json):
            new_key = f"{parent_key}[{i}]" if parent_key else str(i)
            items.extend(flatten_json(item, new_key, sep=sep).items())

    return dict(items)

def get_base_name(path):
    """
    Extracts and returns the base name from a dot-separated path string.

    Parameters:
    ----------
    path : str
        The dot-separated string path (e.g., "com.example.testcase").

    Returns:
    -------
    str
        The last component after the final dot (e.g., "testcase").
    """
    return path.split('.')[-1]

def normalize_value(value):
    """
    Normalizes a given value for comparison purposes.

    - Converts None to an empty string.
    - Strips and lowercases strings.
    - Returns non-string values as-is.

    Parameters:
    ----------
    value : any
        The value to be normalized.

    Returns:
    -------
    any
        The normalized value. For strings, it's lowercased and stripped.
        For None, an empty string is returned. All other types are returned unchanged.
    """
    if value is None:
        return ''  # Normalize None to empty string
    if isinstance(value, str):
        return value.strip().lower()  # Normalize strings to lowercase and trim spaces
    return value

def compare_partial(response_path, flattened_payload, threshold=0.8):
    """
    Finds the best partial match for a response path in the flattened payload using fuzzy matching.

    Args:
        response_path (str): Key from the response to match.
        flattened_payload (dict): Payload keys to compare against.
        threshold (float): Minimum similarity score required for a match.

    Returns:
        str or None: The best-matching payload key, or None if no match exceeds the threshold.
    """
    response_parts = response_path.split('.')
    response_base_name = response_parts[-1]
    response_parent_context = '.'.join(response_parts[:-1])  # Extract parent path

    best_match = None
    best_score = 0

    for payload_path in flattened_payload:
        payload_parts = payload_path.split('.')
        payload_base_name = payload_parts[-1]
        payload_parent_context = '.'.join(payload_parts[:-1])  # Extract parent path

        # Calculate base name similarity
        base_name_ratio = SequenceMatcher(None, response_base_name, payload_base_name).ratio()

        # Calculate parent context similarity
        if response_parent_context and payload_parent_context:
            context_ratio = SequenceMatcher(None, response_parent_context, payload_parent_context).ratio()
        elif not response_parent_context and not payload_parent_context:
            context_ratio = 1.0  # Both have no parent
        else:
            context_ratio = 0.5  # One has a parent, the other does not

        # Combined score
        combined_score = (0.7 * base_name_ratio) + (0.3 * context_ratio)

        # Check if this is the best match
        if combined_score > best_score and combined_score > threshold:
            best_score = combined_score
            best_match = payload_path

    return best_match

# Compare semantic similarity between two paths using SentenceTransformer
def compare_semantic_similarity(model, response_path, flattened_payload, threshold=0.8):
    """
    Compare semantic similarity between two paths using SentenceTransformer on base names.
    Args:
        response_path (str): The path in the response JSON.
        flattened_payload (dict): The flattened payload.
        threshold (float): The similarity threshold for considering paths as similar.
    Returns:
        str: The matching path if found, else None.
    """
    # Extract base name from the response path
    response_base_name = get_base_name(response_path)
    
    response_embedding = model.encode(response_base_name)

    # Iterate through each payload path
    for payload_path in flattened_payload:
        # Extract base name from the payload path
        payload_base_name = get_base_name(payload_path)
        
        # Encode the base names for semantic similarity
        payload_embedding = model.encode(payload_base_name)
        
        # Compute cosine similarity
        cosine_sim = np.dot(response_embedding, payload_embedding) / (np.linalg.norm(response_embedding) * np.linalg.norm(payload_embedding))
        
        # Check if cosine similarity exceeds the threshold
        if cosine_sim > threshold:
            return payload_path
    
    return None

# Compare a response path with all paths in the flattened payload to find a matching path
def compare_paths(model, response_path, flattened_payload, threshold=0.8):
    """
    Attempts to find the best match for a response path in the flattened payload.
    Returns an exact match if found; otherwise, uses partial fuzzy matching.

    Args:
        model (str): Placeholder argument (not used).
        response_path (str): The key path from the response.
        flattened_payload (dict): Dictionary of flattened payload keys.
        threshold (float): Minimum similarity threshold for partial match.
    """
    # Exact match (check path directly)
    if response_path in flattened_payload:
        return response_path

    # Partial match using SequenceMatcher
    matching_path = compare_partial(response_path, flattened_payload)
    if matching_path:
        return matching_path

    '''
    # Semantic match using SentenceTransformer
    matching_path = compare_semantic_similarity(model, response_path, flattened_payload, threshold)
    return matching_path
    '''
# Compare values of response and payload
def compare_values(response_value, payload_value):
    """
    Compares two values for exact equality.

    Args:
        response_value: Value from the response.
        payload_value: Expected value from the payload.
    """
    return response_value == payload_value

def check_booking_status(response_json, topic):
    """
    Checks if a status attribute in the response JSON matches the expected value
    based on the topic variable.

    Configure topic_to_status mapping for your application.

    Args:
        response_json (dict or list): The JSON response to check.
        topic (str): The topic that determines the expected status value.

    Returns:
        tuple: (is_valid: bool, error_message: str|None, status_value: str|None)
    """
    try:
        # Define expected statuses for topics — customize for your application
        topic_to_status = {
            # "topic_name": "expected_status_value",
        }

        if topic not in topic_to_status:
            return False, f"Unknown topic '{topic}'. No expected status defined.", None

        expected_status = topic_to_status[topic]

        if isinstance(response_json, list):
            if not response_json:
                return False, "Response JSON is an empty list.", None
            response_json = response_json[0]

        status = response_json.get("status")
        if status is None:
            return False, "The attribute 'status' is missing from the response JSON.", None

        if status != expected_status:
            return (
                False,
                f"Expected status: '{expected_status}' for topic '{topic}', but got: '{status}'",
                status
            )

        return True, None, status

    except Exception as e:
        return False, f"An error occurred during validation: {e}", None

