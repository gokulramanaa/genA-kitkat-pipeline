"""
Airflow DAG for generating a bedtime story with the ChatGPT API,
uploading the text to OCI Object Storage, parsing metadata, and
recording the metadata plus the object URL into Oracle Autonomous
Database.

Prerequisites (env vars)
------------------------
OPENAI_API_KEY: API key for the ChatGPT API.
OPENAI_MODEL: Model to use (default: gpt-4o-mini).
OCI_CONFIG_FILE: Path to oci config file (default: ~/.oci/config).
OCI_CONFIG_PROFILE: Profile name in the oci config (default: DEFAULT).
OCI_BUCKET_NAME: Object Storage bucket to receive the stories.
OCI_OBJECT_PREFIX: Optional prefix for objects (default: bedtime-stories/).
ADB_USER: Database username.
ADB_PASSWORD: Database password.
ADB_DSN: Oracle connection string (e.g., "adb.example.com:1522/adb_high").
ADB_WALLET_LOCATION: Optional wallet directory when using Autonomous
    Database with a wallet.

Deployment
----------
Place this file in your Airflow ``dags`` directory and provide the
required dependencies (apache-airflow, openai, oci, oracledb). Each task
uses only environment variables so you can keep secrets out of your DAG
code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional
from urllib.parse import quote

import oci
import oracledb
from airflow import DAG
from airflow.decorators import task
from openai import OpenAI


def load_oci_config() -> Dict[str, str]:
    """Load OCI configuration from the standard config file.

    The function keeps configuration handling in one place so both tasks
    create clients the same way.
    """

    config_path = os.getenv("OCI_CONFIG_FILE", os.path.expanduser("~/.oci/config"))
    profile = os.getenv("OCI_CONFIG_PROFILE", "DEFAULT")
    return oci.config.from_file(file_location=config_path, profile_name=profile)


@dataclass
class StoryUploadResult:
    object_name: str
    object_url: str
    created_at: datetime


@dataclass
class StoryMetadata:
    title: str
    length_chars: int
    length_words: int
    estimated_read_time_min: float
    primary_theme: str


PROMPTS = [
    "Write a gentle bedtime story about curiosity and exploration for children aged 5-7.",
    "Tell a short bedtime tale featuring a brave cat who learns about kindness.",
    "Create a calm bedtime story about a quiet night sky and the constellations coming alive.",
]


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def choose_prompt(run_id: str) -> str:
    index = hash(run_id) % len(PROMPTS)
    return PROMPTS[index]


def build_object_name(prefix: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    sanitized_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
    return f"{sanitized_prefix}story-{timestamp}.txt"


def build_object_url(region: str, namespace: str, bucket: str, object_name: str) -> str:
    quoted = quote(object_name)
    return (
        f"https://objectstorage.{region}.oraclecloud.com/n/{namespace}/"
        f"b/{bucket}/o/{quoted}"
    )


def extract_metadata(story_text: str) -> StoryMetadata:
    lines = [line.strip() for line in story_text.splitlines() if line.strip()]
    title = lines[0][:120] if lines else "Bedtime Story"

    words = story_text.split()
    length_words = len(words)
    length_chars = len(story_text)
    estimated_read_time_min = round(max(length_words / 180.0, 1 / 60), 2)

    lowered = story_text.lower()
    if "kindness" in lowered:
        primary_theme = "kindness"
    elif "stars" in lowered or "sky" in lowered:
        primary_theme = "night sky"
    elif "adventure" in lowered:
        primary_theme = "adventure"
    else:
        primary_theme = "bedtime"

    return StoryMetadata(
        title=title,
        length_chars=length_chars,
        length_words=length_words,
        estimated_read_time_min=estimated_read_time_min,
        primary_theme=primary_theme,
    )


def ensure_table(cursor) -> None:
    cursor.execute(
        """
        DECLARE
          v_count INTEGER;
        BEGIN
          SELECT COUNT(*) INTO v_count FROM user_tables WHERE table_name = 'BEDTIME_STORIES';
          IF v_count = 0 THEN
            EXECUTE IMMEDIATE '
              CREATE TABLE BEDTIME_STORIES (
                ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                CREATED_AT TIMESTAMP,
                TITLE VARCHAR2(200),
                LENGTH_CHARS NUMBER,
                LENGTH_WORDS NUMBER,
                ESTIMATED_READ_TIME_MIN NUMBER,
                PRIMARY_THEME VARCHAR2(100),
                OBJECT_URL VARCHAR2(500)
              )';
          END IF;
        END;
        """
    )


def insert_metadata(
    connection,
    created_at: datetime,
    metadata: StoryMetadata,
    object_url: str,
) -> None:
    cursor = connection.cursor()
    ensure_table(cursor)
    cursor.execute(
        """
        INSERT INTO BEDTIME_STORIES (
            CREATED_AT,
            TITLE,
            LENGTH_CHARS,
            LENGTH_WORDS,
            ESTIMATED_READ_TIME_MIN,
            PRIMARY_THEME,
            OBJECT_URL
        ) VALUES (:1, :2, :3, :4, :5, :6, :7)
        """,
        [
            created_at,
            metadata.title,
            metadata.length_chars,
            metadata.length_words,
            metadata.estimated_read_time_min,
            metadata.primary_theme,
            object_url,
        ],
    )
    connection.commit()


def create_oracle_connection() -> oracledb.Connection:
    dsn = os.environ["ADB_DSN"]
    user = os.environ["ADB_USER"]
    password = os.environ["ADB_PASSWORD"]
    wallet_location = os.getenv("ADB_WALLET_LOCATION")

    if wallet_location:
        return oracledb.connect(
            user=user,
            password=password,
            dsn=dsn,
            config_dir=wallet_location,
            wallet_location=wallet_location,
        )
    return oracledb.connect(user=user, password=password, dsn=dsn)


def generate_story_text(prompt: str) -> str:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a calming storyteller who writes short bedtime stories.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=600,
    )
    return response.choices[0].message.content.strip()


def upload_to_object_storage(story_text: str) -> StoryUploadResult:
    bucket = os.environ["OCI_BUCKET_NAME"]
    prefix = os.getenv("OCI_OBJECT_PREFIX", "bedtime-stories/")

    config = load_oci_config()
    client = oci.object_storage.ObjectStorageClient(config)
    namespace = client.get_namespace().data
    region = config["region"]

    object_name = build_object_name(prefix)
    client.put_object(
        namespace,
        bucket,
        object_name,
        story_text.encode("utf-8"),
        content_type="text/plain",
    )
    object_url = build_object_url(region, namespace, bucket, object_name)
    return StoryUploadResult(object_name=object_name, object_url=object_url, created_at=datetime.utcnow())


def fetch_story_text(object_name: str) -> str:
    bucket = os.environ["OCI_BUCKET_NAME"]
    config = load_oci_config()
    client = oci.object_storage.ObjectStorageClient(config)
    namespace = client.get_namespace().data

    response = client.get_object(namespace, bucket, object_name)
    return response.data.text


with DAG(
    dag_id="bedtime_story_pipeline",
    description="Generate bedtime stories, store them on OCI, and index metadata in ADB",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    dagrun_timeout=timedelta(minutes=20),
    tags=["genai", "oci", "adw", "chatgpt"],
) as dag:

    @task
    def generate_and_upload(**context) -> Dict[str, str]:
        run_id = context["run_id"]
        prompt = choose_prompt(run_id)
        story_text = generate_story_text(prompt)
        upload_result = upload_to_object_storage(story_text)
        return {
            "object_name": upload_result.object_name,
            "object_url": upload_result.object_url,
            "created_at": upload_result.created_at.isoformat(),
        }

    @task
    def parse_and_store(upload_info: Dict[str, str]) -> Dict[str, str]:
        object_name = upload_info["object_name"]
        object_url = upload_info["object_url"]
        created_at = datetime.fromisoformat(upload_info["created_at"])

        story_text = fetch_story_text(object_name)
        metadata = extract_metadata(story_text)

        connection = create_oracle_connection()
        insert_metadata(connection, created_at, metadata, object_url)
        connection.close()

        return {
            "title": metadata.title,
            "object_url": object_url,
            "length_words": metadata.length_words,
            "primary_theme": metadata.primary_theme,
        }

    parse_and_store(generate_and_upload())
