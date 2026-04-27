import json
import os
import sys
import logging
import time
from venv import logger
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from concurrent.futures import ProcessPoolExecutor
from jinja2 import Template
from dotenv import load_dotenv
import argparse
import traceback

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..','..'))
sys.path.append(project_root_path)

from core.utils import utils
from core.utils.utils import log_file_status

# Automatically reload environment variables when .env file changes
load_dotenv(dotenv_path=".env", verbose=True, override=True)

# Set up logging
current_dir = os.path.dirname(os.path.abspath(__file__))
current_date = utils.current_date
param_key = "endpoint_gen_report.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)

# Tracking counters and failure details
total_files = 0
processed_files_count = 0
failed_files_count = 0
failure_details = []

def generate_html_report(json_file, output_folder):
    """
    Generate an HTML report and visual charts from a given JSON test result file.

    This function processes test result data and endpoint metrics from a JSON file to:
    - Validate required JSON sections.
    - Create charts (status summary, response time, status over time, pass rate).
    - Generate a detailed HTML report using a template.
    - Populate the template with test case data, endpoint summaries, CI job info, and charts.
    - Write the final HTML report to the specified output folder.

    Parameters:
        json_file (str): Path to the input JSON file containing test and endpoint results.
        output_folder (str): Directory where the output HTML report and charts will be saved.

    JSON File Requirements:
        The JSON must contain:
            - 'tests' (list): Each entry should include testKey, testCaseName, testDescription, 
              endpointMethod, responseTime, testCaseTime, and status.
            - 'results' (list): Summarized endpoint data with endpoint, method, pass/fail stats, etc.
            - 'info' (dict): Contains metadata including testSuite, summary, environment,
              testPlanKey, and testExecutionKey.

    Charts Generated:
        - test_case_status_summary.png
        - response_time_comparison.png
        - test_case_status_over_time.png
        - pass_rate_chart.png
    """

    try:
        with open(json_file, 'r') as file:
            json_data = json.load(file)
        logging.info(f"Loaded JSON data from {json_file}")
        
    except FileNotFoundError as e:
        error_message = f"Report input file not found: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
            
    except json.JSONDecodeError as e:
        error_message = f"Error decoding JSON: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)

    # Validate presence of required sections
    if "tests" not in json_data or not isinstance(json_data["tests"], list):
        logging.error("The 'tests' section is missing or not a list in the JSON file.")
        exit(1)
    if "results" not in json_data or not isinstance(json_data["results"], list):
        logging.error("The 'results' section is missing or not a list in the JSON file.")
        exit(1)

    logging.info("JSON structure validated successfully.")

    # Convert JSON tests section into a DataFrame
    tests = json_data.get("tests", [])
    logging.info(f"Number of test records found: {len(tests)}")
    dfc = pd.DataFrame(tests)

    # Convert JSON endpoint summary section into a DataFrame
    results = json_data.get("results", [])
    logging.info(f"Number of endpoint results found: {len(results)}")
    dfep = pd.DataFrame(results)

    # Filter required attributes and log progress
    filtered_tests = []
    for test in tests:
        filtered_test = {
            "testKey": test["testKey"],
            "testCaseName": test["testCaseName"],
            "testDescription": test["testDescription"],
            "endpointMethod": test["endpointMethod"],
            "responseTime": test["responseTime"],
            "testCaseTime": test["testCaseTime"],
            "status": test["status"],
        }
        if test["status"] == "failed" or test["status"] == "passed":
            filtered_test["unmatched"] = test.get("unmatched", "N/A")
            filtered_test["unmatchedAttributes"] = test.get("unmatchedAttributes", "N/A")
        else:
            filtered_test["unmatched"] = 0
            filtered_test["unmatchedAttributes"] = []
        filtered_tests.append(filtered_test)
    logging.info(f"Filtered {len(filtered_tests)} tests for report generation.")

    df = pd.DataFrame(filtered_tests)

    # Generate charts and log
    try:
        generate_status_summary_chart(dfc, output_file=os.path.join(output_folder, "test_case_status_summary.png"))
        logging.info("Generated status summary chart.")
        generate_response_time_chart(dfc, output_file=os.path.join(output_folder, "response_time_comparison.png"))
        logging.info("Generated response time comparison chart.")
        generate_status_over_time_chart(dfc, output_file=os.path.join(output_folder, "test_case_status_over_time.png"))
        logging.info("Generated status over time chart.")
        generate_pass_rate_chart(dfc, output_file=os.path.join(output_folder, "pass_rate_chart.png"))
        logging.info("Generated pass rate chart.")
        
    except Exception as e:
        error_message = f"Error generating charts: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
    
    # Read the HTML template
    template_file_path = os.path.join(project_root_path, "core", "reports", "functional", "endpoint_template.html")
    try:
        with open(template_file_path, 'r') as file:
            html_template = file.read()
        logging.info("HTML template loaded successfully.")
        
    except FileNotFoundError as e:
        error_message = f"HTML template not found: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
    
    # Generate rows for tests
    rows = ""
    for _, row in df.iterrows():
        rows += f"""
            <tr style="background-color: {'#eca386' if row['status'] == 'failed' else '#94a4f1'};">
                <td>{row['testKey']}</td>
                <td>{row['testCaseName']}</td>
                <td>{row['testDescription']}</td>
                <td>{row['endpointMethod']}</td>
                <td>{row['responseTime']}</td>
                <td>{row['testCaseTime']}</td>
                <td>{row['status']}</td>
                <td>{row['unmatched']}</td>
                <td>{row['unmatchedAttributes']}</td>
            </tr>
        """
    logging.info("Generated rows for test data.")

    # Generate rows for endpoints
    rows_endpoint = ""
    for index, row_endpoint in dfep.iterrows():
        row_color = "#f2f2f2" if index % 2 == 0 else "#eca386"
        rows_endpoint += f"""
            <tr style="background-color: {row_color};">
                <td>{row_endpoint['endpoint']}</td>
                <td>{row_endpoint['method']}</td>
                <td>{row_endpoint['passed']}</td>
                <td>{row_endpoint['failed']}</td>
                <td>{row_endpoint['total']}</td>
                <td>{row_endpoint['pass rate %']}</td>
                <td>{row_endpoint['average_response_time']}</td>
                <td>{row_endpoint['average_test_case_time']}</td>
            </tr>
        """
    logging.info("Generated rows for endpoint data.")

    #Generate CI JOB URL
    ci_job_id = os.getenv("CI_JOB_ID", "")  # Default to empty string if None
    ci_job_url = os.getenv("CI_JOB_URL", "")

    ci_job_full_url = ci_job_url + ci_job_id  # Concatenation

    # Populate the template and log replacements
    try:
        html_report = html_template.replace("{{ testSuite }}", json_data["info"]["testSuite"])
        html_report = html_report.replace("{{ summary }}", json_data["info"]["summary"])
        html_report = html_report.replace("{{ environment }}", json_data["info"]["environment"])
        html_report = html_report.replace("{{ testPlanKey }}", json_data["info"]["testPlanKey"])
        html_report = html_report.replace("{{ testExecutionKey }}", json_data["info"]["testExecutionKey"])
        html_report = html_report.replace("{{ CI_JOB_URL }}", ci_job_full_url)
        html_report = html_report.replace("{{ rows_endpoint }}", rows_endpoint)
        html_report = html_report.replace("{{ rows }}", rows)
        html_report = html_report.replace("{{ pass_rate_chart }}", f"{output_folder}/pass_rate_chart.png")
        html_report = html_report.replace("{{ test_case_status_summary }}", f"{output_folder}/test_case_status_summary.png")
        html_report = html_report.replace("{{ response_time_comparison }}", f"{output_folder}/response_time_comparison.png")
        html_report = html_report.replace("{{ test_case_status_over_time }}", f"{output_folder}/test_case_status_over_time.png")
        logging.info("Populated HTML template with dynamic data.")
        
    except KeyError as e:
        error_message = f"Missing key in JSON data for template replacement: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)

    # Write the HTML report
    output_file = os.path.join(output_folder, os.path.basename(json_file).replace(".json", ".html"))
    try:
        with open(output_file, "w") as file:
            file.write(html_report)
        logging.info(f"HTML report generated successfully at {output_file}")
        
    except IOError as e:
        error_message = f"Failed to write HTML report to {output_file}: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)

# Function to create the Test Case Status Summary chart
def generate_status_summary_chart(df, output_file="status_summary_chart.png"):
    """
    Generate a bar chart summarizing the count of test cases by their status.

    This chart visually represents the number of test cases that passed or failed
    by using a simple bar graph.

    Parameters:
        df (pandas.DataFrame): DataFrame containing at least a 'status' column,
            where each value represents the outcome of a test (e.g., 'passed', 'failed').
        output_file (str): Path to save the generated chart image file (default is
            'status_summary_chart.png').
    """
    df["status"].value_counts().plot(kind="bar", color=["green", "red"])
    plt.title("Test Case Status Summary")
    plt.xlabel("Status")
    plt.ylabel("Count")
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Status summary chart saved: {output_file}")

# Function to create the Response Time Comparison chart
def generate_response_time_chart(df, output_file="response_time_chart.png"):
    """
    Generate a boxplot comparing response times of passed and failed test cases.

    This visualization helps identify performance differences between passed and
    failed tests by plotting their response times using a boxplot for each status group.

    Parameters:
        df (pandas.DataFrame): DataFrame containing at least 'status' and 'responseTime'
            columns. 'status' should indicate test result (e.g., 'passed', 'failed'),
            and 'responseTime' should be a numeric value representing execution time in milliseconds.
        output_file (str): Path to save the generated chart image file (default is
            'response_time_chart.png').
    """
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x="status", y="responseTime", hue="status",
                palette={"passed": "green", "failed": "red"}, dodge=False)
    plt.title("Response Time Comparison")
    plt.xlabel("Status")
    plt.ylabel("Response Time (ms)")
    plt.legend([], [], frameon=False)  # Hide the legend
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Response time chart saved: {output_file}")

# Function to create the Test Case Status Over Time chart
def generate_status_over_time_chart(df, output_file="status_over_time_chart.png"):
    """
    Generate a line chart to show test case status trends over time.

    This function groups test cases by their execution date and status, and then
    creates a line chart to visualize how the count of each status changes over time.

    Parameters:
        df (pandas.DataFrame): DataFrame containing 'startDate' and 'status' columns.
        output_file (str): File path to save the generated chart image.
    """
    df["startDate"] = pd.to_datetime(df["startDate"])  # Ensure startDate is a datetime object
    status_counts_over_time = df.groupby([df["startDate"].dt.date, "status"]).size().unstack(fill_value=0)
    status_counts_over_time.plot(kind="line", marker="o", colormap="coolwarm")
    plt.title("Test Case Status Over Time")
    plt.xlabel("Date")
    plt.ylabel("Count")
    plt.legend(title="Status")
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Status over time chart saved: {output_file}")

# Function to create the Test Case Pass Rate Percentage Chart
def generate_pass_rate_chart(df, output_file="pass_rate_chart.png"):
    """
    Generate a pie chart showing the percentage of passed and failed test cases.

    This function calculates the pass and fail rates from the DataFrame and visualizes 
    the distribution using a pie chart.

    Parameters:
        df (pandas.DataFrame): DataFrame containing a 'status' column with 'passed' or 'failed' values.
        output_file (str): File path to save the generated chart image.
    """
    # Calculate pass and fail counts
    status_counts = df["status"].value_counts()
    pass_count = status_counts.get("passed", 0)
    fail_count = status_counts.get("failed", 0)
    total = pass_count + fail_count

    # Calculate pass rate percentage
    pass_rate = (pass_count / total) * 100 if total > 0 else 0
    fail_rate = 100 - pass_rate

    # Prepare data for the pie chart
    labels = ["Passed", "Failed"]
    sizes = [pass_rate, fail_rate]
    colors = ["green", "red"]

    # Plot the pie chart
    plt.figure(figsize=(8, 8))
    plt.pie(sizes, labels=labels, autopct="%.2f%%", startangle=90, colors=colors)
    plt.title("Pass Rate Percentage")
    plt.axis("equal")  # Equal aspect ratio ensures the pie chart is circular
    plt.savefig(output_file)
    plt.close()
    logging.info(f"Pass rate percentage chart saved: {output_file}")

def merge_report_data(folder_path, output_folder, endpoint):
    """
    Identify valid JSON files to merge based on subfolder names containing '_' or '-',
    merge their contents, and save the result to an output file.

    Args:
        folder_path (str): Path to the folder containing the JSON files.
        output_folder (str): Path to save the merged output file.
        endpoint (str): The endpoint name to use in the output file name.
    """
    # Find JSON files where subfolder names contain '_' or '-'
    json_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(folder_path)
        for file in files if file.endswith("_report_data.json")
    ]

    valid_files = []
    for json_file in json_files:
        subfolder = os.path.dirname(json_file).split(os.path.sep)[-1]
        if ('_' in subfolder or '-' in subfolder) and f"{end_point}" in subfolder:
            valid_files.append(json_file)

    if not valid_files:
        logging.info("No valid files found to merge.")
        return

    # Initialize merged data structure
    merged_data = {
        "info": {},
        "results": [],
        "tests": []
    }

    for file_path in valid_files:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Populate "info" from the first valid file
        if not merged_data["info"]:
            merged_data["info"] = data.get("info", {})
            #merged_data["info"].pop("results", None)  # Remove "results" from "info"
            merged_data["info"].pop("startDate", None)
            merged_data["info"].pop("finishDate", None)
            merged_data["info"].pop("duration", None)
            merged_data["info"]["summary"] = f"Test Report for trips_e2e - {endpoint}"

        # Add the "results" section data as individual entries in the array
        results_data = data.get("info", {}).get("results", {})
        if results_data:
            result_entry = {
                "endpoint": endpoint,
                "method": results_data.get("method", ""),
                "passed": results_data.get("passed", 0),
                "failed": results_data.get("failed", 0),
                "total": results_data.get("total", 0),
                "pass rate %": results_data.get("pass rate %", "0.00"),
                "average_response_time": results_data.get("average_response_time", 0.0),
                "average_test_case_time": results_data.get("average_test_case_time", 0.0)
            }
            merged_data["results"].append(result_entry)
            logging.info(f"Added {len(merged_data['results'])} results from file: {file_path}")

        # Merge tests from the current file
        if "tests" in data:
            merged_data["tests"].extend(data["tests"])
            logging.info(f"Added {len(data['tests'])} tests from file: {file_path}")

        merged_data["info"].pop("results", None)  # Remove "results" from "info"

    # Log total number of results and tests
    total_results = len(merged_data["results"])
    total_tests = len(merged_data["tests"])
    logging.info(f"Total results added: {total_results}")
    logging.info(f"Total tests added: {total_tests}")

    # Create the output file name
    endpoint_output_folder = os.path.join(output_folder, endpoint)
    output_file = os.path.join(endpoint_output_folder, f"{endpoint}_report_data.json")

    # Log the output file path
    logging.info(f"Output file path generated: {output_file}")

    # Ensure the output folder exists
    os.makedirs(endpoint_output_folder, exist_ok=True)
    logging.info(f"Output folder created (if not existing): {endpoint_output_folder}")

    # Write the merged data to the output file
    try:
        with open(output_file, 'w') as f:
            json.dump(merged_data, f, indent=4)
        logging.info(f"Merged data successfully saved to {output_file}")
        
    except Exception as e:
        error_message = f"Failed to save merged data to {output_file}. Error: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
        
def process_folder(folder_path, output_folder, end_point): 
    """
    Process all JSON test report files in the specified folder and generate HTML reports.

    This function recursively searches for JSON files ending with '_report_data.json',
    validates subfolder names to ensure they do not contain underscores or hyphens and 
    must include the given `end_point`. If the conditions are met, an HTML report is 
    generated for each file using `generate_html_report`.

    Parameters:
        folder_path (str): Path to the root folder containing subfolders with report files.
        output_folder (str): Path where the generated HTML reports will be saved.
        end_point (str): Endpoint keyword that must be present in valid subfolder names.
    """
    logging.info(f"Starting processing for folder: {folder_path}")
    
    json_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(folder_path)
        for file in files if file.endswith("_report_data.json")
    ]

    if not json_files:
        logging.warning(f"No matching JSON files found in folder: {folder_path}")
    
    for json_file in json_files:
        subfolder = os.path.dirname(json_file).split(os.path.sep)[-1]
        
        logging.info(f"Found JSON file: {json_file} in subfolder: {subfolder}")
        
        # Check if the subfolder does not have '_' or '-' and contains {end_point}
        if ('_' in subfolder or '-' in subfolder) or end_point not in subfolder:
            logging.info(f"Skipping subfolder '{subfolder}' as it does not match criteria.")
            continue

        # Process valid subfolders
        subfolder_output = os.path.join(output_folder, end_point)
        os.makedirs(subfolder_output, exist_ok=True)
        logging.info(f"Processing file: {json_file} for subfolder: {subfolder}")
        logging.info(f"Output folder created (if not existing): {subfolder_output}")

        try:
            generate_html_report(json_file, subfolder_output)
            logging.info(f"Successfully processed and generated report for: {json_file}")
            
        except Exception as e:
         error_message = f"Error processing file {json_file}: {e}"
         logging.error(error_message)
         print(json.dumps({
            "status": "failed",
            "message": error_message
         }, indent=2))
         sys.exit(1)

    logging.info(f"Completed processing for folder: {folder_path}")

def generate_index_html(output_folder):
    """
    Generate an index HTML file that provides links to all individual HTML reports.

    This function scans the given output folder (recursively) for all `.html` files 
    and creates an `index.html` file listing them as clickable links. It is useful 
    for quick navigation across multiple reports from a single entry point.

    Parameters:
        output_folder (str): The root directory where HTML reports are stored.
                             The generated index file will be placed in this folder.
    """
    logging.info(f"Inside Index file generation")
    links = []
    for root, _, files in os.walk(output_folder):
        for file in files:
            if file.endswith(".html"):
                relative_path = os.path.relpath(os.path.join(root, file), output_folder)
                links.append(f"<li><a href='{relative_path}'>{file}</a></li>")
    index_content = f"<html><body><h1>Index of Reports</h1><ul>{''.join(links)}</ul></body></html>"
    index_file = os.path.join(output_folder, "index.html")
    with open(index_file, "w") as file:
        file.write(index_content)
    logging.info(f"Index file generated: {index_file}")
    

if __name__ == "__main__":
    failed_files = []
    
    try:
        parser = argparse.ArgumentParser(description="Process test files in parallel.")
        parser.add_argument('application', type=str, nargs='?', default='trips', help='Path to the application')
        parser.add_argument('end_point', type=str, nargs='?', default='jumpcustomer', help='Path to the folder containing test files')

        args = parser.parse_args()
        start_time_program = time.time()
        end_point = args.end_point
        application_name = args.application

        # Define paths
        base_folder = os.path.join(project_root_path, "results", application_name)
        output_folder = os.path.join(project_root_path,"reports_output", application_name, "functional")

        merge_report_data(base_folder, base_folder, end_point)
        logging.info(f"Merging of result files completed for {end_point}.")

        # Control the number of parallel processes
        num_processes = int(os.getenv("NUM_PROCESSES", 2))

        # Process JSON files in parallel
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            executor.submit(process_folder, base_folder, output_folder, end_point)

        end_time_program = time.time()
        elapsed_time_program = end_time_program - start_time_program
        logging.info(f"Elapsed Time for Program : {elapsed_time_program:.2f} seconds")
        logging.info("HTML Reports generation completed.")
        
        # Now call your logging function and print the JSON status
        log_status = log_file_status(failed_files)
        print(json.dumps(log_status, indent=2))

        # Exit according to success/failure
        if log_status.get("status") == "success":
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        tb = traceback.extract_tb(sys.exc_info()[2])
        line_number = tb[-1].lineno if tb else 'unknown'
        script_name = __file__
        error_message = f"Exception occurred in script {script_name} at line {line_number}: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
