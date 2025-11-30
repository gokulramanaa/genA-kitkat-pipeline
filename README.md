# genA-kitkat-pipeline

Airflow example that generates bedtime stories with the ChatGPT API, saves
the story text to Oracle Cloud Infrastructure (OCI) Object Storage, parses
basic metadata, and records the metadata plus the Object Storage URL into
Oracle Autonomous Database (ADB).

## Features
- Airflow DAG with two Python @task steps
  - Generate a bedtime story via ChatGPT, upload to OCI Object Storage
  - Fetch the story, extract metadata, and insert metadata + URL into ADB
- Minimal helper functions to keep OCI/OpenAI/ADB logic isolated
- Environment variable configuration to avoid embedding secrets

## Repository layout
```
.
├─ dags/
│  └─ bedtime_story_pipeline.py  # Airflow DAG definition
├─ requirements.txt              # Dependencies for Airflow workers
└─ README.md
```

## Prerequisites
- Python 3.10+
- Airflow 2.9+
- Access to the ChatGPT API and OCI credentials with Object Storage access
- An Oracle Autonomous Database (or other Oracle DB) account for storing
  metadata

## Installation
1. Install dependencies (ideally in an Airflow worker/virtualenv):
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `dags/bedtime_story_pipeline.py` into your Airflow `dags`
   directory (or mount this repo there).

## Local development quickstart (visualize the DAG)
These steps bring up an Airflow UI locally so you can see the DAG
graph without deploying to a remote environment. The commands use a
throwaway `AIRFLOW_HOME` inside the repo root to keep local state
isolated.

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Initialize Airflow metadata DB and create an admin user (accepting
   prompts with defaults is fine):
   ```bash
   export AIRFLOW_HOME="$(pwd)/.airflow"
   airflow db init
   airflow users create \
     --username admin \
     --password admin \
     --firstname Airflow \
     --lastname Admin \
     --role Admin \
     --email admin@example.com
   ```
3. Point Airflow at this repo's DAGs directory and start a local
   webserver plus scheduler in two shells:
   ```bash
   export AIRFLOW_HOME="$(pwd)/.airflow"
   export AIRFLOW__CORE__DAGS_FOLDER="$(pwd)/dags"

   # Shell 1
   airflow webserver -p 8080

   # Shell 2
   airflow scheduler
   ```
4. Open http://localhost:8080 in your browser, log in with the admin
   credentials, and view the `bedtime_story_pipeline` DAG to inspect
   its graph and tasks.

## Configuration
Provide the following environment variables to your Airflow workers:

| Variable | Description |
| --- | --- |
| `OPENAI_API_KEY` | API key for the ChatGPT API. |
| `OPENAI_MODEL` | Optional, model name (default: `gpt-4o-mini`). |
| `OCI_CONFIG_FILE` | Optional, path to OCI config file (default: `~/.oci/config`). |
| `OCI_CONFIG_PROFILE` | Optional, config profile name (default: `DEFAULT`). |
| `OCI_BUCKET_NAME` | OCI Object Storage bucket that will hold stories. |
| `OCI_OBJECT_PREFIX` | Optional, object key prefix (default: `bedtime-stories/`). |
| `ADB_USER` | Database username. |
| `ADB_PASSWORD` | Database password. |
| `ADB_DSN` | Oracle DSN, e.g. `adb.example.com:1522/adb_high`. |
| `ADB_WALLET_LOCATION` | Optional, wallet directory if your ADB requires one. |

### OCI configuration
The DAG expects a standard OCI config file. A minimal example:
```ini
[DEFAULT]
user=ocid1.user.oc1..aaaa...
fingerprint=aa:bb:cc:dd:ee:ff:11:22:33:44:55:66:77:88:99:00
key_file=/path/to/oci_api_key.pem
tenancy=ocid1.tenancy.oc1..aaaa...
region=us-phoenix-1
```

### Database table
The DAG auto-creates a table named `BEDTIME_STORIES` if it does not yet
exist. Columns recorded:
- `CREATED_AT`
- `TITLE`
- `LENGTH_CHARS`
- `LENGTH_WORDS`
- `ESTIMATED_READ_TIME_MIN`
- `PRIMARY_THEME`
- `OBJECT_URL`

## Running the DAG
- Trigger `bedtime_story_pipeline` manually from the Airflow UI or via
  the CLI:
  ```bash
  airflow dags trigger bedtime_story_pipeline
  ```
- Each run will:
  1. Select a prompt, generate a story, and upload it to OCI Object Storage
  2. Fetch the uploaded story, extract simple metadata (title, counts,
     estimated reading time, theme), and insert a row into ADB with the
     metadata and object URL

## Notes
- Prompts are intentionally simple; edit `PROMPTS` in the DAG to customize
  generated stories.
- The DAG uses synchronous API calls for clarity. For production, consider
  adding retries, timeouts, and secret backends (e.g., Airflow
  Connections/Variables or OCI Vault).
