import json
import os
import sys
import logging
import time
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from concurrent.futures import ProcessPoolExecutor
from jinja2 import Template
from dotenv import load_dotenv
import argparse
import traceback
import requests

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(project_root_path)

from core.utils import utils, gitlab_utils
from core.utils.utils import log_file_status

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

# Set up logging
current_dir = os.path.dirname(os.path.abspath(__file__))
current_date = utils.current_date
param_key = "endpoint_method_gen_report.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)

def generate_html_report(json_file, output_folder):
    """
    Generate a detailed HTML report and associated visual charts from a JSON test report file.

    This function processes the given JSON file, extracts and filters test case data,
    generates multiple performance and status charts (saved as PNGs), and uses an HTML 
    template to produce a full-featured HTML report. The report includes metadata, 
    test statistics, charts, and a color-coded test case table.

    Parameters:
        json_file (str): Path to the JSON file containing structured test execution data.
        output_folder (str): Directory where the HTML report and charts will be saved.

    Function Highlights:
        - Validates and parses the input JSON file.
        - Extracts relevant test attributes, including pass/fail status, response time, etc.
        - Generates:
            - Test case status summary bar chart.
            - Response time comparison boxplot.
            - Test case status over time line chart.
            - Pass rate pie chart.
        - Uses a pre-defined HTML template to embed:
            - Test execution metadata (suite, environment, duration, etc.)
            - A styled test case result table.
            - CI job URL (fetched from environment variables).
            - Embedded chart images.
        - Saves the final HTML report to the specified output directory.
        
    Environment Variables Used:
        - CI_JOB_ID: Used to generate job link for traceability.
        - CI_JOB_URL: Base URL for job link.
    """
    try:
        with open(json_file, 'r') as file:
            json_data = json.load(file)
        logging.info(f"Loaded JSON data from {json_file}")
        
    except FileNotFoundError as e:
        error_message = f"Report Input File not found: {e}"
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

    # Convert JSON tests section into a DataFrame
    tests = json_data.get("tests", [])

    # Keep only required attributes
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
            filtered_test["unmatched"] = test["unmatched"]
            filtered_test["unmatchedAttributes"] = test["unmatchedAttributes"]
        else:
            filtered_test["unmatched"] = 0
            filtered_test["unmatchedAttributes"] = []
        filtered_tests.append(filtered_test)
        
    df = pd.DataFrame(filtered_tests)
    dfc = pd.DataFrame(tests)

    generate_status_summary_chart(dfc, output_file=os.path.join(output_folder, "test_case_status_summary.png"))
    generate_response_time_chart(dfc, output_file=os.path.join(output_folder, "response_time_comparison.png"))
    generate_status_over_time_chart(dfc, output_file=os.path.join(output_folder, "test_case_status_over_time.png"))
    generate_pass_rate_chart(dfc, output_file=os.path.join(output_folder, "pass_rate_chart.png"))

    # Read the HTML template
    template_file_path = os.path.join(project_root_path, "core", "reports", "functional", "endpoint_method_template.html")
    try:
        with open(template_file_path, 'r') as file:
            html_template = file.read()
        logging.info("HTML template loaded successfully!")
        
    except FileNotFoundError as e:
        error_message = f"HTML template not found: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "message": error_message
        }, indent=2))
        sys.exit(1)
    
    # Generate table rows from the DataFrame with color highlighting
    rows = ""
    for _, row in df.iterrows():
        status_class = "failed" if row["status"] == "failed" else "passed"
        row_color = "#eca386" if row["status"] == "failed" else "#94a4f1"  # Highlight color based on status
        rows += f"""
            <tr style="background-color: {row_color};">
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
    #Generate CI JOB URL
    ci_job_id = os.getenv("CI_JOB_ID", "")  # Default to empty string if None
    ci_job_url = os.getenv("CI_JOB_URL", "")

    ci_job_full_url = ci_job_url + ci_job_id  # Concatenation

    # Populate the template
    html_report = html_template.replace("{{ testSuite }}", json_data["info"]["testSuite"])
    html_report = html_report.replace("{{ summary }}", json_data["info"]["summary"])
    html_report = html_report.replace("{{ duration }}", json_data['info']['duration'])
    html_report = html_report.replace("{{ environment }}", json_data["info"]["environment"])
    html_report = html_report.replace("{{ testPlanKey }}", json_data["info"]["testPlanKey"])
    html_report = html_report.replace("{{ testExecutionKey }}", json_data["info"]["testExecutionKey"])
    html_report = html_report.replace("{{ CI_JOB_URL }}", ci_job_full_url)
    html_report = html_report.replace("{{ total }}", str(json_data["info"]["results"]["total"]))
    html_report = html_report.replace("{{ passed }}", str(json_data["info"]["results"]["passed"]))
    html_report = html_report.replace("{{ failed }}", str(json_data["info"]["results"]["failed"]))
    html_report = html_report.replace("{{ pass_rate }}", f"{json_data['info']['results']['pass rate %']}%")
    html_report = html_report.replace("{{ average_response_time }}", f"{json_data['info']['results']['average_response_time']}")
    html_report = html_report.replace("{{ average_test_case_time }}", f"{json_data['info']['results']['average_test_case_time']}")
    html_report = html_report.replace("{{ rows }}", rows)
    html_report = html_report.replace("{{ pass_rate_chart }}", f"{output_folder}/pass_rate_chart.png")
    html_report = html_report.replace("{{ test_case_status_summary }}", f"{output_folder}/test_case_status_summary.png")
    html_report = html_report.replace("{{ response_time_comparison }}", f"{output_folder}/response_time_comparison.png")
    html_report = html_report.replace("{{ test_case_status_over_time }}", f"{output_folder}/test_case_status_over_time.png")

    output_file = os.path.join(output_folder, os.path.basename(json_file).replace(".json", ".html"))
    with open(output_file, "w") as file:
        file.write(html_report)
    logging.info(f"HTML report generated: {output_file}")

# Function to create the Test Case Status Summary chart
def generate_status_summary_chart(df, output_file="status_summary_chart.png"):
    """
    Generate a bar chart summarizing the count of test cases by their status.
    This function takes a DataFrame with a 'status' column (e.g., 'passed', 'failed') 
    and creates a bar chart showing the count of each status category. The chart is 
    saved as a PNG image.

    Parameters:
        df (pandas.DataFrame): DataFrame containing a 'status' column.
        output_file (str): Path where the output chart image will be saved (default: 'status_summary_chart.png').
    Notes:
        - Assumes the 'status' column includes values like 'passed' and 'failed'.
        - Bars are color-coded: green for passed, red for failed.
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
    Generate a boxplot comparing response times of test cases by status.

    This function creates a boxplot visualization of the 'responseTime' distribution 
    for each test status (e.g., 'passed', 'failed') to compare performance between 
    passing and failing test cases. The chart is saved as a PNG image.

    Parameters:
        df (pandas.DataFrame): DataFrame containing 'status' and 'responseTime' columns.
        output_file (str): Path where the output chart image will be saved 
                           (default: 'response_time_chart.png').
    Notes:
        - The chart uses color coding: green for 'passed', red for 'failed'.
        - The legend is hidden to keep the plot clean, as the hue and x-axis already show status.
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
    Generate a line chart showing the count of test case statuses over time.

    This function visualizes how the distribution of test case statuses 
    (e.g., 'passed', 'failed') changes over time using a line plot. 
    It groups the test cases by date and status, and plots their counts.

    Parameters:
        df (pandas.DataFrame): DataFrame containing 'startDate' and 'status' columns.
        output_file (str): Path to save the generated chart image 
                           (default: 'status_over_time_chart.png').

    Notes:
        - The function ensures 'startDate' is properly parsed as datetime.
        - Colors are automatically selected using the 'coolwarm' colormap.
        - Each status gets a separate line for visual comparison over time.
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
    Generate a pie chart visualizing the test pass/fail rate as percentages.

    This function calculates the percentage of passed and failed test cases
    from the given DataFrame and visualizes the data as a pie chart. The 
    resulting chart provides a clear view of the test pass rate distribution.

    Parameters:
        df (pandas.DataFrame): DataFrame containing a 'status' column with 
                               values like 'passed' and 'failed'.
        output_file (str): Path where the generated pie chart image will be saved 
                           (default: 'pass_rate_chart.png').
    Notes:
        - If there are no passed or failed statuses, the chart will show 0% passed.
        - Colors are fixed: green for passed, red for failed.
        - Percentages are displayed with two decimal places.
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

def update_test_execution_info(json_file):
    """
    Update the 'info' section of a JSON report file with test execution details.

    This function reads a JSON report file and updates its 'info' section with 
    test execution metadata (testExecutionKey and testExecutionId). The values 
    are fetched from GitLab CI/CD pipeline variables if running in a CI context, 
    or from environment variables otherwise (e.g., a `.env` file).

    Parameters:
        json_file (str): Path to the JSON file containing test execution results.

    Behavior:
        - If `CI_PIPELINE` is set (indicating a GitLab CI environment), variables
          are retrieved using the `gitlab_utils.get_gitlab_variable` method.
        - If not in a CI environment, it falls back to reading `os.environ` values.
        - Updates (or creates) the `info` section in the JSON with:
            - `testExecutionKey`
            - `testExecutionId`
        - Overwrites the original file with the updated data.
    """
    try:
        # Load the JSON file
        with open(json_file, 'r') as file:
            data = json.load(file)
        
        if os.getenv("CI_PIPELINE"):
            test_execution_key = gitlab_utils.get_gitlab_variable("TEST_EXECUTION_KEY")
            test_execution_id = gitlab_utils.get_gitlab_variable("TEST_EXECUTION_ID")
            logging.info("[INFO] get CICD pipeline variables with Test Execution details.")
        else:
            test_execution_key = os.getenv("TEST_EXECUTION_KEY")
            test_execution_id = os.getenv("TEST_EXECUTION_ID")
            logging.info("[INFO] get .env file with Test Execution details.")

        # Update the `info` section
        #test_execution_key = get_gitlab_variable("TEST_EXECUTION_KEY")
        #test_execution_id = get_gitlab_variable("TEST_EXECUTION_ID")
        
        if not data.get("info"):
            data["info"] = {}

        data["info"]["testExecutionKey"] = test_execution_key
        data["info"]["testExecutionId"] = test_execution_id
        
        logging.info(f"[INFO] Updated test execution info in {json_file}.")
        
        # Save the updated JSON back to the same file
        with open(json_file, 'w') as file:
            json.dump(data, file, indent=4)
        logging.info(f"[INFO] Updated test execution info and saved file: {json_file}.")
        
        return data
    
    except Exception as e:
        error_message = f"[ERROR] Failed to update test execution info in {json_file}: {e}"
        logging.error(error_message)
        print(json.dumps({
            "status": "failed",
            "file": json_file,
            "message": error_message
        }, indent=2))
        return False

    
def process_folder(folder_path, output_folder, end_point, method):
    """
    Process method-specific JSON test report files and generate HTML reports.
    """
    # Look for method-specific JSON files
    json_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(folder_path)
        for file in files if file.endswith(f"_{method}_report_data.json")
    ]
    
    if not json_files:
        logging.warning(f"No JSON files found for method {method}")
        return
    
    for json_file in json_files:
        subfolder = os.path.dirname(json_file).split(os.path.sep)[-1]
        
        # Check if subfolder contains endpoint name and method
        if f"{end_point}_{method}" in subfolder:
            subfolder_output = os.path.join(output_folder, f"{end_point}_{method}")
            os.makedirs(subfolder_output, exist_ok=True)
            
            logging.info(f"Processing method-specific file: {json_file}")
            
            # Update test execution info
            updated_json_data = update_test_execution_info(json_file)
            
            if updated_json_data:
                generate_html_report(json_file, subfolder_output)
                logging.info(f"Generated HTML report for {end_point}_{method}")
            else:
                logging.error(f"Skipping file {json_file} due to update failure.")

def generate_index_html(output_folder):
    """
    Generate an index HTML file listing links to all individual report HTML files.

    This function recursively scans the given `output_folder` for all `.html` files 
    (excluding the index file itself if already present), generates clickable links 
    to each report, and writes them into an `index.html` file at the root of the `output_folder`.

    Parameters:
        output_folder (str): The root directory to search for HTML report files and 
                             where the index file will be generated.

    Workflow:
        1. Traverse all subdirectories under `output_folder`.
        2. Identify files ending with `.html`.
        3. For each report found:
            - Generate a relative path.
            - Add an HTML list item linking to the file.
        4. Write all links into a simple HTML structure and save as `index.html`.
    """
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
    
        
# def main(application):
#     failed_files = []
#     # Your processing logic here
#     # Example: suppose process_folder or other steps add to failed_files if any
#     # For demonstration, just return empty list (meaning success)
#     return failed_files


if __name__ == "__main__":
    failed_files = []
    
    try:
        parser = argparse.ArgumentParser(description="Process test files in parallel.")
        parser.add_argument('application', type=str, nargs='?', default='trips', help='Path to the application')
        parser.add_argument('end_point', type=str, nargs='?', default='jumpcustomer', help='Path to the folder containing test files')
        parser.add_argument('method', type=str, nargs='?', default='post', help='HTTP method (post, get, put, patch, delete)')

        args = parser.parse_args()
        start_time_program = time.time()
        end_point = args.end_point
        application_name = args.application
        method = args.method

        # Define paths
        base_folder = os.path.join(project_root_path, "results", application_name)
        output_folder = os.path.join(project_root_path,"reports_output", application_name, "functional")

        # Control the number of parallel processes
        num_processes = int(os.getenv("NUM_PROCESSES", 2))

        # Process JSON files in parallel
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            executor.submit(process_folder, base_folder, output_folder, end_point, method)

        # Generate index HTML
        #generate_index_html(output_folder)
        logging.info("HTML Reports generation completed.")

        logging.info(f"Merging of result files completed for {end_point}.")

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
        