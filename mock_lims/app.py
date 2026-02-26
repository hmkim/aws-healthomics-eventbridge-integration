"""Clarity LIMS Mock Emulator - Streamlit application for testing LIMS integration."""

import streamlit as st
import requests
import json
import base64
import boto3
from datetime import datetime
import pandas as pd

from sample_generator import generate_sample, generate_batch, generate_batch_for_org, ORG_TEMPLATES


# Page configuration
st.set_page_config(
    page_title="Clarity LIMS Mock Emulator",
    page_icon="🧬",
    layout="wide"
)

st.title("Clarity LIMS Mock Emulator")

# Initialize session state
if "submission_history" not in st.session_state:
    st.session_state.submission_history = []

if "generated_samples" not in st.session_state:
    st.session_state.generated_samples = []

if "register_samples" not in st.session_state:
    st.session_state.register_samples = []


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification (for display only)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def authenticate(user_pool_id: str, client_id: str, username: str, password: str) -> dict:
    """Authenticate with Cognito via admin_initiate_auth and return token info."""
    region = user_pool_id.split("_")[0]
    client = boto3.client("cognito-idp", region_name=region)

    response = client.admin_initiate_auth(
        UserPoolId=user_pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_NO_SRP_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": password,
        },
    )

    tokens = response["AuthenticationResult"]
    claims = _decode_jwt_payload(tokens["IdToken"])

    return {
        "id_token": tokens["IdToken"],
        "access_token": tokens["AccessToken"],
        "refresh_token": tokens.get("RefreshToken", ""),
        "email": claims.get("email", username),
        "organization_id": claims.get("organization_id", ""),
        "groups": claims.get("cognito:groups", []),
    }


# =============================================================================
# Sidebar
# =============================================================================
st.sidebar.header("API Configuration")

api_url = st.sidebar.text_input(
    "API Endpoint URL",
    value="",
    help="Base URL for the LIMS API endpoint (e.g. https://<api-id>.execute-api.us-east-1.amazonaws.com/v1)"
)

s3_bucket = st.sidebar.text_input(
    "S3 Input Bucket",
    value="",
    help="S3 bucket name for FASTQ file paths (created by CDK deploy)"
)

st.sidebar.divider()
st.sidebar.header("Cognito Authentication")

user_pool_id = st.sidebar.text_input(
    "User Pool ID",
    value="",
)

client_id = st.sidebar.text_input(
    "App Client ID",
    value="",
)

username = st.sidebar.text_input("Email")
password = st.sidebar.text_input("Password", type="password")

if st.sidebar.button("Login", type="primary", use_container_width=True):
    if not username or not password:
        st.sidebar.error("Email and password are required")
    else:
        try:
            auth_info = authenticate(user_pool_id, client_id, username, password)
            st.session_state.auth = auth_info
            st.sidebar.success("Authenticated")
        except Exception as e:
            st.sidebar.error(f"Login failed: {e}")

# Show auth status
if "auth" in st.session_state:
    auth = st.session_state.auth
    st.sidebar.success(f"Logged in: {auth['email']}")
    st.sidebar.caption(f"Org: `{auth['organization_id']}`")
    st.sidebar.caption(f"Roles: `{', '.join(auth['groups'])}`")
    if st.sidebar.button("Logout", use_container_width=True):
        del st.session_state.auth
        st.rerun()
else:
    st.sidebar.warning("Not authenticated")


# =============================================================================
# Helper functions
# =============================================================================

def get_auth_headers() -> dict:
    """Build request headers with Cognito Bearer token."""
    headers = {"Content-Type": "application/json"}
    if "auth" in st.session_state:
        headers["Authorization"] = st.session_state.auth["id_token"]
    return headers


def submit_sample(payload: dict) -> tuple:
    """
    Submit a sample to the API endpoint.

    Returns:
        tuple: (success: bool, response_data: dict or str)
    """
    if "auth" not in st.session_state:
        return False, {"error": "Not authenticated. Please login first."}

    try:
        response = requests.post(
            f"{api_url}/analysis/start",
            json=payload,
            headers=get_auth_headers(),
            timeout=30
        )

        if response.status_code in (200, 201, 202):
            return True, response.json() if response.text else {"status": "accepted"}
        else:
            return False, {
                "status_code": response.status_code,
                "error": response.text
            }
    except requests.exceptions.RequestException as e:
        return False, {"error": str(e)}


def register_samples_api(samples: list) -> dict:
    """Register samples via POST /lims/samples (batch)."""
    if "auth" not in st.session_state:
        return {"error": "Not authenticated. Please login first."}

    try:
        response = requests.post(
            f"{api_url}/lims/samples",
            json={"samples": samples},
            headers=get_auth_headers(),
            timeout=30,
        )
        if response.status_code in (200, 201, 207):
            return response.json()
        else:
            # API Gateway / Lambda error — extract message
            try:
                body = response.json()
                msg = body.get("error") or body.get("message") or str(body)
            except Exception:
                msg = response.text or f"HTTP {response.status_code}"
            return {"error": f"HTTP {response.status_code}: {msg}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def add_to_history(sample_id: str, project_id: str, success: bool, response: dict):
    """Add a submission to the history."""
    st.session_state.submission_history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_id": sample_id,
        "project_id": project_id,
        "status": "Success" if success else "Failed",
        "response": str(response)
    })


# =============================================================================
# Auth guard
# =============================================================================
if "auth" not in st.session_state:
    st.info("Please login using the sidebar to submit samples.")
    st.stop()

# =============================================================================
# Main content area with tabs
# =============================================================================
tab_single, tab_batch, tab_register, tab_status = st.tabs(["Single Sample", "Batch Submit", "Register Samples", "Status Check"])


# Single Sample Tab
with tab_single:
    st.subheader("Submit Single Sample")

    with st.form("single_sample_form"):
        col1, col2 = st.columns(2)

        with col1:
            project_id = st.text_input("Project ID", value="PROJ-001")
            sample_id = st.text_input("Sample ID", value="SAM-001")
            patient_id = st.text_input("Patient ID (hash)", value="PAT-HASH-001")
            submitter_email = st.text_input(
                "Submitter Email",
                value=st.session_state.auth.get("email", "researcher@lab.org")
            )

        with col2:
            fastq_r1 = st.text_input(
                "FASTQ R1 Path",
                value=f"s3://{s3_bucket}/raw_data/sample_R1_001.fastq.gz"
            )
            fastq_r2 = st.text_input(
                "FASTQ R2 Path",
                value=f"s3://{s3_bucket}/raw_data/sample_R2_001.fastq.gz"
            )

        col3, col4 = st.columns(2)

        with col3:
            reference_genome = st.selectbox(
                "Reference Genome",
                options=["GRCh38", "hg38"],
                index=0
            )

        with col4:
            analysis_type = st.selectbox(
                "Analysis Type",
                options=["WGS", "WES", "PANEL"],
                index=0
            )

        submitted = st.form_submit_button("Submit Sample", type="primary")

        if submitted:
            payload = {
                "source": "ClarityLIMS_Mock",
                "event_type": "analysis.requested",
                "data": {
                    "project_id": project_id,
                    "sample_id": sample_id,
                    "patient_id": patient_id,
                    "submitter_email": submitter_email,
                    "fastq_paths": {
                        "r1": fastq_r1,
                        "r2": fastq_r2
                    },
                    "reference_genome": reference_genome,
                    "analysis_type": analysis_type
                }
            }

            with st.spinner("Submitting sample..."):
                success, response = submit_sample(payload)

            add_to_history(sample_id, project_id, success, response)

            with st.expander("Submission Result", expanded=True):
                if success:
                    st.success(f"Sample {sample_id} submitted successfully!")
                    st.json(response)
                else:
                    st.error(f"Failed to submit sample {sample_id}")
                    st.json(response)


# Batch Submit Tab
with tab_batch:
    st.subheader("Batch Sample Submission")

    col1, col2 = st.columns([1, 2])

    with col1:
        sample_count = st.number_input(
            "Number of Samples",
            min_value=1,
            max_value=20,
            value=5,
            help="Generate 1-20 random samples"
        )

        if st.button("Generate Samples", type="secondary"):
            st.session_state.generated_samples = generate_batch(sample_count, s3_bucket)
            st.success(f"Generated {sample_count} samples")

    # Show generated samples
    if st.session_state.generated_samples:
        st.subheader("Generated Samples")

        # Create a display dataframe
        display_data = []
        for sample in st.session_state.generated_samples:
            data = sample["data"]
            display_data.append({
                "Project ID": data["project_id"],
                "Sample ID": data["sample_id"],
                "Submitter": data["submitter_email"],
                "Analysis Type": data["analysis_type"],
                "Reference": data["reference_genome"]
            })

        df = pd.DataFrame(display_data)
        st.dataframe(df, use_container_width=True)

        # Submit all button
        if st.button("Submit All Samples", type="primary"):
            progress_bar = st.progress(0)
            status_container = st.container()

            results = []
            total = len(st.session_state.generated_samples)

            for i, sample in enumerate(st.session_state.generated_samples):
                sid = sample["data"]["sample_id"]
                pid = sample["data"]["project_id"]

                success, response = submit_sample(sample)
                add_to_history(sid, pid, success, response)

                results.append({
                    "sample_id": sid,
                    "success": success,
                    "response": response
                })

                progress_bar.progress((i + 1) / total)

            # Show results summary
            with status_container:
                successful = sum(1 for r in results if r["success"])
                failed = len(results) - successful

                if failed == 0:
                    st.success(f"All {successful} samples submitted successfully!")
                elif successful == 0:
                    st.error(f"All {failed} samples failed to submit")
                else:
                    st.warning(f"{successful} succeeded, {failed} failed")

                with st.expander("Detailed Results"):
                    for result in results:
                        status_icon = "+" if result["success"] else "-"
                        st.text(f"[{status_icon}] {result['sample_id']}: {result['response']}")

            # Clear generated samples after submission
            st.session_state.generated_samples = []


# Register Samples Tab (organization-based)
with tab_register:
    st.subheader("Register Samples to LIMS")

    auth = st.session_state.auth
    org_id = auth.get("organization_id", "UNKNOWN")

    # Organization name lookup
    ORG_NAMES = {
        "ORG-ACME": "ACME Genomics Lab",
        "ORG-BIOCORP": "BioCorp Research",
        "ORG-UNIVERSITY": "State University Medical Center",
    }
    org_display = ORG_NAMES.get(org_id, org_id)
    st.info(f"Registering for: **{org_id}** ({org_display})")

    col1, col2 = st.columns([1, 2])

    with col1:
        register_count = st.number_input(
            "Number of Samples",
            min_value=1,
            max_value=20,
            value=3,
            key="register_count",
            help="Generate 1-20 samples based on your organization's templates"
        )

        if st.button("Generate", type="secondary", key="generate_register"):
            st.session_state.register_samples = generate_batch_for_org(
                register_count, org_id, auth.get("email", "")
            )
            st.success(f"Generated {register_count} samples for {org_id}")

    # Show generated samples
    if st.session_state.register_samples:
        st.subheader("Generated Samples Preview")

        display_data = []
        for sample in st.session_state.register_samples:
            display_data.append({
                "Sample ID": sample["sample_id"],
                "Project": sample["project_id"],
                "Description": sample.get("description", ""),
                "Type": sample["analysis_type"],
                "Genome": sample["reference_genome"],
            })

        df = pd.DataFrame(display_data)
        st.dataframe(df, use_container_width=True)

        if st.button("Register All", type="primary", key="register_all"):
            with st.spinner("Registering samples..."):
                result = register_samples_api(st.session_state.register_samples)

            if "error" in result:
                st.error(f"Registration failed: {result['error']}")
            else:
                registered = result.get("registered", 0)
                failed = result.get("failed", 0)
                total = result.get("total", 0)

                if failed == 0:
                    st.success(f"All {registered} samples registered successfully!")
                elif registered == 0:
                    st.error(f"All {total} samples failed to register")
                else:
                    st.warning(f"{registered} registered, {failed} failed out of {total}")

                # Show individual results
                with st.expander("Detailed Results"):
                    for r in result.get("results", []):
                        if r["status"] == "registered":
                            st.text(f"[+] {r['sample_id']}: registered")
                        else:
                            st.text(f"[-] {r['sample_id']}: {r.get('error', 'failed')}")

            # Clear generated samples after registration attempt
            st.session_state.register_samples = []


# Status Check Tab
with tab_status:
    st.subheader("Pipeline Status Check")

    check_sample_id = st.text_input("Sample ID to check", key="status_sample_id")

    if st.button("Check Status") and check_sample_id:
        try:
            response = requests.get(
                f"{api_url}/analysis/status/{check_sample_id}",
                headers=get_auth_headers(),
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                st.json(data)
            else:
                st.error(f"Error {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Request failed: {e}")


# Submission History Section
st.divider()
st.subheader("Submission History")

if st.session_state.submission_history:
    history_df = pd.DataFrame(st.session_state.submission_history)
    # Show most recent first
    history_df = history_df.iloc[::-1].reset_index(drop=True)
    st.dataframe(history_df, use_container_width=True)

    if st.button("Clear History"):
        st.session_state.submission_history = []
        st.rerun()
else:
    st.info("No submissions yet. Submit a sample to see history here.")
