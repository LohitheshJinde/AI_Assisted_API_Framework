# API Framework

A data-driven, multi-threaded API testing framework built with Python. Supports REST API testing with automatic token management, response comparison, contract testing, and reporting.

## Features

- **Multi-threaded execution** — concurrent test case processing via ThreadPoolExecutor
- **Multiple HTTP methods** — GET, POST, PUT, PATCH, DELETE
- **Auth management** — OAuth, Cognito, client credentials with auto-refresh
- **Response comparison** — exact, partial (fuzzy), and status-code-only validators
- **Contract testing** — JSON schema validation for request/response contracts
- **Pagination support** — automatic multi-page API response handling
- **Configurable via JSON** — endpoint configs in `param.json`, no code changes needed
- **Structured reporting** — JSON reports with pass/fail, timing, and payload data
- **AWS integration** — SNS, SQS, DynamoDB, S3 helpers
- **Jira/Xray integration** — push results to Xray test management
- **CI/CD ready** — GitLab CI compatible with exit codes

## Project Structure

```
smarttest-api/
├── core/                        # Framework core
│   ├── api_engine/              # API engine, auth, HTTP method runners
│   │   ├── api_engine.py        # Main APIEngine class
│   │   ├── Auth.py              # Token management (OAuth, Cognito, etc.)
│   │   ├── param.json           # Default framework parameters
│   │   ├── TestAPIRequests.py   # Generic test runner
│   ├── awsresources/            # AWS service helpers
│   ├── reports/                 # HTML/JSON report generators
│   ├── utils/                   # Comparison, config, utilities
├── myapp/                       # Your application config (create this)
│   └── param.json               # Endpoint definitions
├── testdata/                    # Test data JSON files (create this)
│   └── myapp/
│       └── endpoint1/
│           └── endpoint1_data_post.json
├── .env.example                 # Environment variable template
├── .gitignore
├── requirements.txt
└── README.md
```

## Quick Start

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API URLs, credentials, etc.
   ```

3. **Create your application config**
   
   Create `myapp/param.json` with your endpoint definitions:
   ```json
   {
     "endpoint1": {
       "auth_type": "oauth",
       "POST": {
         "url": "{base_url}/api/v1/resource",
         "headers": {
           "Content-Type": "application/json",
           "Authorization": "Bearer {access_token}"
         },
         "payload_key": "payload",
         "expected_status_code_key": "expected_status_code",
         "test_description": "Test {test}"
       }
     }
   }
   ```

4. **Create test data**
   
   Create `testdata/myapp/endpoint1/endpoint1_data_post.json`:
   ```json
   [
     {
       "test_case_name": "Create resource - happy path",
       "test_key": "TC-001",
       "test_description": "Verify resource creation",
       "expected_status_code": 201,
       "payload": {
         "name": "Test Resource",
         "type": "example"
       }
     }
   ]
   ```

5. **Run tests**
   ```bash
   cd core/api_engine
   python TestPost.py myapp endpoint1 data_post.json all "" post
   ```

## Usage

### Command Line Arguments

All Test runners accept the same arguments:
```
python Test<Method>.py <application> <endpoint> <filename_pattern> <test_case_key> <topic> <method>
```

| Argument | Description | Example |
|---|---|---|
| application | App folder name | `myapp` |
| endpoint | API endpoint name | `endpoint1` |
| filename_pattern | Test data file suffix | `data_post.json` |
| test_case_key | Filter by test key (or `all`) | `TC-001` |
| topic | Optional topic for SNS tests | `""` |
| method | HTTP method | `post` |

### Auth Types

Configure `auth_type` in your `param.json`:
- `oauth` — Basic auth token exchange
- `cognito` — AWS Cognito USER_PASSWORD_AUTH
- `csop_client` — Client credentials flow
- `gca` — Client credentials with client_id/secret
- `customersearch` — API key based auth

## License

MIT
