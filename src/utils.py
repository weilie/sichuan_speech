import os
import sys
import dashscope

def setup_dashscope():
    """Initializes DashScope endpoint and returns the API key."""
    dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("Error: DASHSCOPE_API_KEY environment variable not set.")
    return api_key

def handle_api_response(response, error_msg):
    """Checks the API response status and exits on error."""
    if response.status_code != 200:
        sys.exit(f"API Error ({response.status_code}): {response.message}")
    return response.output
