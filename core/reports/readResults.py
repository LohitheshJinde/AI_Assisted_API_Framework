import json
import os
import sys
import pandas as pd
import logging
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import seaborn as sns

# Load configuration from the config file
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..','..'))
sys.path.append(project_root_path)

from utils import utils

# Automatically reload environment variables when .env file changes
load_dotenv(dotenv_path=".env", verbose=True, override=True)

# Set up logging
current_dir = os.path.dirname(os.path.abspath(__file__))
current_date = utils.current_date
param_key = "readResults.log"
log_file_path = utils.configure_logging_api(param_key, current_date, current_dir)

# Define the path to the JSON file
results_folder = os.path.join(project_root_path, "results", "trips", "jumpcustomer")
json_file_name = "jumpcustomer_report_data.json"
json_file_path = os.path.join(results_folder, json_file_name)

# Read the JSON data
try:
    with open(json_file_path, 'r') as file:
        json_data = json.load(file)
    logging.info("JSON data loaded successfully!")
except FileNotFoundError:
    logging.error(f"File not found: {json_file_path}")
    exit(1)
except json.JSONDecodeError as e:
    logging.error(f"Error decoding JSON: {e}")
    exit(1)

# Convert JSON tests section into a DataFrame
tests = json_data.get("tests", [])

# Keep only required attributes
filtered_tests = []
for test in tests:
    filtered_test = {
        "testKey": test["testKey"],
        "testCaseName": test["testCaseName"],
        "startDate": test["startDate"],
        "finishDate": test["finishDate"],
        "responseTime": test["responseTime"],
        "testCaseTime": test["testCaseTime"],
        "status": test["status"],
    }
    if test["status"] == "failed":
        filtered_test["unmatched"] = test["unmatched"]
        filtered_test["unmatchedAttributes"] = test["unmatchedAttributes"]
    else:
        filtered_test["unmatched"] = ""
        filtered_test["unmatchedAttributes"] = ""
    filtered_tests.append(filtered_test)

df = pd.DataFrame(filtered_tests)

# Read the HTML template
template_file_path = os.path.join(project_root_path, "reports", "report_template.html")
try:
    with open(template_file_path, 'r') as file:
        html_template = file.read()
    logging.info("HTML template loaded successfully!")
except FileNotFoundError:
    logging.error(f"HTML template not found: {template_file_path}")
    exit(1)

# Generate table rows from the DataFrame with color highlighting
rows = ""
for _, row in df.iterrows():
    status_class = "failed" if row["status"] == "failed" else "passed"
    row_color = "#eca386" if row["status"] == "failed" else "#94a4f1"  # Highlight color based on status
    rows += f"""
        <tr style="background-color: {row_color};">
            <td>{row['testKey']}</td>
            <td>{row['testCaseName']}</td>
            <td>{row['startDate']}</td>
            <td>{row['finishDate']}</td>
            <td>{row['responseTime']}</td>
            <td>{row['testCaseTime']}</td>
            <td>{row['status']}</td>
            <td>{row['unmatched']}</td>
            <td>{row['unmatchedAttributes']}</td>
        </tr>
    """

# Populate the template
html_report = html_template.replace("{{ testSuite }}", json_data["info"]["testSuite"])
html_report = html_report.replace("{{ summary }}", json_data["info"]["summary"])
html_report = html_report.replace("{{ duration }}", json_data['info']['duration'])
html_report = html_report.replace("{{ environment }}", json_data["info"]["environment"])
html_report = html_report.replace("{{ testPlanKey }}", json_data["info"]["testPlanKey"])
html_report = html_report.replace("{{ testExecutionKey }}", json_data["info"]["testExecutionKey"])
html_report = html_report.replace("{{ CI_JOB_URL }}", json_data["info"]["CI_JOB_URL"])
html_report = html_report.replace("{{ total }}", str(json_data["info"]["results"]["total"]))
html_report = html_report.replace("{{ passed }}", str(json_data["info"]["results"]["passed"]))
html_report = html_report.replace("{{ failed }}", str(json_data["info"]["results"]["failed"]))
html_report = html_report.replace("{{ pass_rate }}", f"{json_data['info']['results']['pass rate %']}%")
html_report = html_report.replace("{{ average_response_time }}", f"{json_data['info']['results']['average_response_time']}")
html_report = html_report.replace("{{ average_test_case_time }}", f"{json_data['info']['results']['average_test_case_time']}")
html_report = html_report.replace("{{ rows }}", rows)
html_report = html_report.replace("{{ pass_rate_chart }}", f"{results_folder}/pass_rate_chart.png")
html_report = html_report.replace("{{ test_case_status_summary }}", f"{results_folder}/test_case_status_summary.png")
html_report = html_report.replace("{{ response_time_comparison }}", f"{results_folder}/response_time_comparison.png")
html_report = html_report.replace("{{ test_case_status_over_time }}", f"{results_folder}/test_case_status_over_time.png")

# Write the HTML report to a file
output_file_path = os.path.join(results_folder, "jumpcustomer_report.html")
with open(output_file_path, "w") as output_file:
    output_file.write(html_report)

logging.info(f"HTML report generated successfully: {output_file_path}")

# Function to create the Test Case Status Summary chart
def generate_status_summary_chart(df, output_file="status_summary_chart.png"):
    """
    Generates a bar chart showing the number of passed and failed test cases.

    Args:
        df (pd.DataFrame): DataFrame with a 'status' column (e.g., 'passed', 'failed').
        output_file (str): File path where the chart will be saved.
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
    Generates a box plot comparing response times of passed and failed test cases.

    Args:
        df (pd.DataFrame): DataFrame containing 'status' and 'responseTime' columns.
        output_file (str): Path to save the generated box plot image.

    Output:
        Saves a box plot visualizing the distribution of response times by test status.
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
    Generates a line chart showing how test case statuses (passed/failed) change over time.

    Args:
        df (pd.DataFrame): DataFrame containing 'startDate' and 'status' columns.
        output_file (str): Path to save the generated line chart image.

    Output:
        Saves a line chart that visualizes the count of each test status by date.
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
    Create a pie chart showing the percentage of passed vs. failed test cases.

    This function calculates the number of passed and failed test cases from the 
    provided DataFrame, computes their respective percentage shares, and generates 
    a pie chart to visually represent the test pass rate. The chart is then saved 
    as an image to the specified file path.

    Args:
        df (pd.DataFrame): A pandas DataFrame containing a 'status' column, 
                           where each value is expected to be either 'passed' or 'failed'.
        output_file (str): The path where the pie chart image will be saved. 
                           Defaults to "pass_rate_chart.png".

    Behavior:
        - Counts how many tests passed and failed.
        - Calculates the pass/fail percentage.
        - Generates a pie chart with labeled segments.
        - Saves the chart as a PNG image.

    Notes:
        - If the DataFrame contains no 'passed' or 'failed' values, a 0% chart is generated.
        - Colors used: green for passed, red for failed.
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

os.makedirs(results_folder, exist_ok=True)

generate_status_summary_chart(df, output_file=os.path.join(results_folder, "test_case_status_summary.png"))
generate_response_time_chart(df, output_file=os.path.join(results_folder, "response_time_comparison.png"))
generate_status_over_time_chart(df, output_file=os.path.join(results_folder, "test_case_status_over_time.png"))
generate_pass_rate_chart(df, output_file=os.path.join(results_folder, "pass_rate_chart.png"))