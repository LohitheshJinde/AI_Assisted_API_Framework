# utils.py
import json
import os
import sys
import re
import logging
from datetime import datetime, timezone

project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root_path)

# Initialize current_date as a global variable
current_date = datetime.now(timezone.utc).strftime("%Y%m%d")

# core/utils/utils.py

def calculate_process_status(pass_rate: float | None) -> dict:
    import logging

    if pass_rate is None:
        logging.warning("No pass rate returned from engine — setting to 0.0")
        pass_rate = 0.0

    try:
        pass_rate = round(pass_rate, 2)
        failure_rate = round(100 - pass_rate, 2)
    except Exception:
        logging.error("Divide by zero or rounding error")
        pass_rate = 0.0
        failure_rate = 100.0

    print(f"Pass Rate: {pass_rate}%")
    print(f"Failure Rate: {failure_rate}%")

    if pass_rate == 100.0:
        process_status = {
            "status": "success",
            "message": f"Test Execution passed with {pass_rate}% success"
        }
        return process_status
    else:
        process_status = {
            "status": "failed",
            "message": f"Test Execution failed with {failure_rate}% failure"
        }
        return process_status

def log_program_status(processed_files_count, failed_files_count, total_files, failure_details):
    if failed_files_count == 0:
        program_status = {
            "status": "success",
            "message": f"All {processed_files_count} files processed successfully."
        }
        return program_status
    else:
        program_status = {
            "status": "failed",
            "message": f"{failed_files_count} out of {total_files} files failed.",
            "failures": failure_details
        }
        return program_status
    
        
def log_file_status(failed_files):
    if not failed_files:
        log_status = {
            "status": "success",
            "message": "program executed successfully"
        }
        return log_status
    else:
        log_status = {
            "status": "failed",
            "message": f"program not executed properly"
        }
        return log_status
    
    

def get_json_files(subfolder, filename_pattern, base_folder):
    if subfolder.lower() != 'all':
        specific_folder = os.path.join(project_root_path, base_folder, subfolder)
        if not os.path.isdir(specific_folder):
            logging.error(f"Subfolder '{subfolder}' not found: {specific_folder}")
            return
        json_files = [os.path.join(root, file)
                        for root, _, files in os.walk(specific_folder)
                        for file in files
                        if file.endswith(filename_pattern)]
    else:
        json_files = [os.path.join(root, file)
                        for root, _, files in os.walk(base_folder)
                        for file in files
                        if file.endswith(filename_pattern)]
    return json_files


def get_json_files_api(base_folder, application, subfolder, filename_pattern):
    if subfolder.lower() != 'all':
        specific_folder = os.path.join(project_root_path, base_folder, application, subfolder)
        if not os.path.isdir(specific_folder):
            logging.error(f"Subfolder '{subfolder}' not found: {specific_folder}")
            return
        json_files = [os.path.join(root, file)
                        for root, _, files in os.walk(specific_folder)
                        for file in files
                        if file.endswith(filename_pattern)]
    else:
        json_files = [os.path.join(root, file)
                        for root, _, files in os.walk(base_folder)
                        for file in files
                        if file.endswith(filename_pattern)]
    return json_files

def load_params(param_file_name, base_folder):
    """Loads parameters from a JSON file."""
    param_file_path = os.path.join(project_root_path, base_folder, param_file_name)
    with open(param_file_path, 'r') as param_file:
        param_data = json.load(param_file)
    return param_data

def get_param_value(param_key, default_value=None):
    """Get a parameter value from api_engine param.json"""
    try:
        param_data = load_params('param.json', 'core/api_engine')
        return param_data.get(param_key, default_value)
    except Exception:
        return default_value

def store_as_json(data, filename_prefix):
    """Store data as a JSON file."""
    global current_date  # Access the global variable
    json_filename = f"{current_date}_{filename_prefix}.json"
    json_file_path = os.path.join("context", json_filename)

    with open(json_file_path, 'w') as json_file:
        json.dump(data, json_file)

    logging.info(f'Successfully stored data in {json_file_path}')

def rename_date_folder(parent_folder, current_date):
    """
    Rename folders with the given current_date in the specified parent_folder.
    
    Args:
        parent_folder (str): Path to the parent folder where renaming will be performed.
        current_date (str): The current date used for renaming.
    """
    original_folder = os.path.join(parent_folder, current_date)

    # If the folder doesn't exist, no need to rename
    if not os.path.exists(original_folder):
        logging.info(f"Folder '{original_folder}' does not exist.")
        return

    index = 1
    new_folder = f"{current_date}_{index}"

    while os.path.exists(os.path.join(parent_folder, new_folder)):
        index += 1
        new_folder = f"{current_date}_{index}"

    os.rename(original_folder, os.path.join(parent_folder, new_folder))
    logging.info(f"Folder '{original_folder}' has been renamed to '{new_folder}'.")
    logging.shutdown()

def store_result_set_as_json(result_set_target, resultset_filename):

    logging.info("I am here : utils.store_result_set_as_json")
    # Create a filename based on the current date
    global current_date  # Access the global variable
    
    # Define the folder path
    folder_path = os.path.join("context", current_date)

    # Create the folder if it doesn't exist
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    # Define the JSON file path
    json_file_path = os.path.join(folder_path, resultset_filename)

    # Write the result_set_target to the JSON file
    with open(json_file_path, 'w') as json_file:
        json.dump(result_set_target, json_file)
    
    logging.info(f'Successfully stored result set in {str(json_file_path)}')

def store_result_set_as_json1(result_set_target, resultset_filename):
    logging.info("I am here : utils.store_result_set_as_json")
    # Create a filename based on the current date
    global current_date  # Access the global variable
    
    # Convert the current_date to a string
    current_date_str = str(current_date)
    
    # Define the folder path
    folder_path = os.path.join("context", current_date_str)

    # Create the folder if it doesn't exist
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        
    # Define the JSON file path
    json_file_path = os.path.join(folder_path, resultset_filename)

    # Write the result_set_target to the JSON file
    with open(json_file_path, 'w') as json_file:
        json.dump(result_set_target, json_file)
    
    logging.info(f'Successfully stored result set in {str(json_file_path)}')
        
def configure_logging(param_key, current_date, current_dir):
    # Create log file name
    # Get the directory name from the current directory path
    directory_name = os.path.basename(current_dir)
    
    if param_key == "archival.log":
        log_name = os.path.splitext(param_key)[0] + current_date +  ".log"
    else:
        log_name = os.path.splitext(param_key)[0] +  ".log"
    print("log_name : ", log_name)
    # Create logs directory if it doesn't exist
    parent_dir = os.path.abspath(os.path.join(current_dir, os.pardir))
    if param_key == "archival.log":
        logs_dir = os.path.join(parent_dir, "delete", current_date)
    else:
        logs_dir = os.path.join(parent_dir, "logs", current_date, directory_name)
    
    # Ensure the logs directory exists
    if not os.path.exists(logs_dir):
        try:
            os.makedirs(logs_dir)
        except FileExistsError:
            # Directory already exists, no need to create it
            pass
    # Set log file path
    log_file_path = os.path.join(logs_dir, log_name)
    
    # Configure logging
    logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    return log_file_path

def configure_logging_api(param_key, current_date, current_dir):
    # Create log file name
    if param_key == "archival.log":
        log_name = os.path.splitext(param_key)[0] + current_date + ".log"
    else:
        log_name = os.path.splitext(param_key)[0] + ".log"
    
    print("log_name:", log_name)

    # Calculate the relative path from project_root_path to current_dir
    try:
        relative_path = os.path.relpath(current_dir, project_root_path)
    except ValueError:
        # Handles the case where paths are on different drives (Windows-specific issue)
        relative_path = os.path.basename(current_dir)

    # Determine logs directory, mirroring the relative path under "logs"
    if param_key == "archival.log":
        logs_dir = os.path.join(project_root_path, "delete", current_date, relative_path)
    else:
        logs_dir = os.path.join(project_root_path, "logs", current_date, relative_path)

    # Ensure the logs directory exists
    os.makedirs(logs_dir, exist_ok=True)

    # Set log file path
    log_file_path = os.path.join(logs_dir, log_name)

    # Configure logging
    logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    return log_file_path

def configure_result(param_key, current_date, current_dir):
    # Create log file name
    # Get the directory name from the current directory path
    directory_name = os.path.basename(current_dir)
    
    if param_key == "archival.log":
        log_name = os.path.splitext(param_key)[0] + current_date +  ".res"
    else:
        log_name = os.path.splitext(param_key)[0] +  ".res"
    print("log_name : ", log_name)
    # Create logs directory if it doesn't exist
    parent_dir = os.path.abspath(os.path.join(current_dir, os.pardir))
    if param_key == "archival.res":
        logs_dir = os.path.join(parent_dir, "delete", current_date)
    else:
        logs_dir = os.path.join(parent_dir, "logs", current_date, directory_name)
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Set log file path
    res_file_path = os.path.join(logs_dir, log_name)
    
    # Configure logging
    logging.basicConfig(filename=res_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    return res_file_path

#IngestionCustomer.py uses this
def move_attributes_inside_json(result_set):
    for item in result_set:
        # Remove unnecessary spaces in timestamp strings
        for key, value in item["json_data"].items():
            if isinstance(value, str):
                item["json_data"][key] = value.strip()
        item["json_data"]["file_name"] = item.pop("file_name")
        item["json_data"]["condition_name"] = item.pop("condition_name")
        item.update(item.pop("json_data"))  # Remove the "json_data" wrapper
    logging.info(f'Json {result_set}')
    return result_set

def cal_duration(start_time, end_time):
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
# Example: Rename the date folder within "context" using current date
#current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
# rename_date_folder("context", current_date)

def add_attributes_to_payload(payload, additional_fields, endpoint):
    """Add additional fields to payload dict or list of dicts."""
    if isinstance(payload, list):
        return [dict(item, **additional_fields) for item in payload]
    elif isinstance(payload, dict):
        return dict(payload, **additional_fields)
    return payload

def find_associated_payload_from_respective_post_testcases(application, test_key, compare_endpoint, json_suffix):
    """
    Find and return a single record from response data based on test_key
    Args:
        endpoint: Source endpoint name (e.g., 'jumpcustomer')
        test_key: Key to search for in the another data
        compare_endpoint: Endpoint to compare against (e.g., 'bookingbasics')
        json_suffix: Suffix of the JSON file to search for (e.g., '_data_post.json')
    Returns:
        First record that matches the test_key, or None if no match found
    Raises:
        ValueError: If test_key is None or empty
        FileNotFoundError: If no JSON files are found
    """
    try:
        # Validate input parameters
        if not test_key:
            raise ValueError("test_key cannot be None or empty")
           
        if not compare_endpoint:
            raise ValueError("compare_endpoint cannot be None or empty")
           
        if not json_suffix:
            raise ValueError("json_suffix cannot be None or empty")
        
        # Construct the path to testdata folder
        testdata_path = os.path.join(project_root_path, 'testdata', application, compare_endpoint)
       
        if not os.path.exists(testdata_path):
            raise FileNotFoundError(f"Testdata directory not found: {testdata_path}")
       
        # Search for the JSON file with both patterns
        json_files = []
        for root, _, files in os.walk(testdata_path):
            for file in files:
                if file.endswith(json_suffix):
                    json_files.append(os.path.join(root, file))
        if not json_files:
            logging.warning(f"No response files found for endpoint {compare_endpoint} with suffix {json_suffix}")
            return None
        logging.info(f"Found {len(json_files)} JSON files in {testdata_path}")
       
        # Process files until we find a match
        for json_file in json_files:
            try:
                # Load response data
                with open(json_file, 'r') as f:
                    response_data = json.load(f)
                   
                # Validate response data structure
                if not isinstance(response_data, (list, dict)):
                    logging.warning(f"Invalid response data structure in {json_file}. Expected list or dict, got {type(response_data)}")
                    continue
               
                # Search for record matching the test_key
                if isinstance(response_data, list):
                    for record in response_data:
                        if not isinstance(record, dict):
                            logging.warning(f"Invalid record structure in {json_file}. Expected dict, got {type(record)}")
                            continue
                           
                        if "test_key" not in record:
                            logging.warning(f"Record in {json_file} does not contain 'test_key' field")
                            continue
                           
                        logging.debug(f"Comparing test_key: {record['test_key']} with {test_key}")
                        if record["test_key"] == test_key:
                            logging.info(f"Found matching record in {json_file} for test_key: {test_key}")
                            return record
                elif isinstance(response_data, dict):
                    if "test_key" not in response_data:
                        logging.warning(f"Response data in {json_file} does not contain 'test_key' field")
                        continue
                       
                    if response_data["test_key"] == test_key:
                        logging.info(f"Found matching record in {json_file} for test_key: {test_key}")
                        return response_data
                       
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing JSON file {json_file}: {str(e)}")
                continue
            except Exception as e:
                logging.error(f"Error processing file {json_file}: {str(e)}")
                continue
                   
        logging.warning(f"No record found matching test_key: {test_key} in any files")
        return None
           
    except Exception as e:
        logging.error(f"Error finding associated payload: {str(e)}")
        raise