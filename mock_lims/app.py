"""Clarity LIMS Mock Emulator - Streamlit application for testing LIMS integration."""

import streamlit as st
import requests
from datetime import datetime
import pandas as pd

from sample_generator import generate_sample, generate_batch


# Page configuration
st.set_page_config(
    page_title="Clarity LIMS Mock Emulator",
    page_icon="🧬",
    layout="wide"
)

st.title("Clarity LIMS Mock Emulator")

# Initialize session state for submission history
if "submission_history" not in st.session_state:
    st.session_state.submission_history = []

if "generated_samples" not in st.session_state:
    st.session_state.generated_samples = []


# Sidebar configuration
st.sidebar.header("Configuration")

api_url = st.sidebar.text_input(
    "API Endpoint URL",
    value="https://iesbx2ssmd.execute-api.us-east-1.amazonaws.com/v1",
    help="Base URL for the LIMS API endpoint"
)

api_key = st.sidebar.text_input(
    "API Key",
    type="password",
    help="API key for authentication"
)

s3_bucket = st.sidebar.text_input(
    "S3 Input Bucket",
    value="omics-eventbridge-solutio-healthomicsckainput66426-agmbnrjahnkz",
    help="S3 bucket name for FASTQ file paths"
)


def submit_sample(payload: dict) -> tuple:
    """
    Submit a sample to the API endpoint.

    Returns:
        tuple: (success: bool, response_data: dict or str)
    """
    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key

        response = requests.post(
            f"{api_url}/analysis/start",
            json=payload,
            headers=headers,
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


def add_to_history(sample_id: str, project_id: str, success: bool, response: dict):
    """Add a submission to the history."""
    st.session_state.submission_history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_id": sample_id,
        "project_id": project_id,
        "status": "Success" if success else "Failed",
        "response": str(response)
    })


# Main content area with tabs
tab_single, tab_batch = st.tabs(["Single Sample", "Batch Submit"])


# Single Sample Tab
with tab_single:
    st.subheader("Submit Single Sample")

    with st.form("single_sample_form"):
        col1, col2 = st.columns(2)

        with col1:
            project_id = st.text_input("Project ID", value="PROJ-001")
            sample_id = st.text_input("Sample ID", value="SAM-001")
            patient_id = st.text_input("Patient ID (hash)", value="PAT-HASH-001")
            submitter_email = st.text_input("Submitter Email", value="researcher@lab.org")

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
                "event_type": "StepCompleted",
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
                sample_id = sample["data"]["sample_id"]
                project_id = sample["data"]["project_id"]

                success, response = submit_sample(sample)
                add_to_history(sample_id, project_id, success, response)

                results.append({
                    "sample_id": sample_id,
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
