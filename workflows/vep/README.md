# VEP (Variant Effect Predictor) Workflow

## Overview

This workflow runs Ensembl's Variant Effect Predictor (VEP) on AWS HealthOmics. VEP determines the effect of variants (SNPs, insertions, deletions, CNVs, or structural variants) on genes, transcripts, and protein sequences.

## Workflow Parameters

| Parameter | Description | Required | Example |
|-----------|-------------|----------|---------|
| `vcf` | Input VCF file path (S3 URI) | Yes | `s3://bucket/sample.vcf.gz` |
| `vep_cache` | Cache directory path (S3 URI) | Yes | `s3://aws-genomics-static-us-east-1/omics-tutorials/data/databases/vep/` |
| `vep_cache_version` | VEP cache version to use | Yes | `110` |
| `vep_species` | Species name (latin or alias) | Yes | `homo_sapiens` |
| `vep_genome` | Reference genome assembly | Yes | `GRCh38` |
| `ecr_registry` | ECR registry URL for container images | Yes | `<account-id>.dkr.ecr.<region>.amazonaws.com` |
| `id` | Sample identifier | No | `NA12878` |

## Workflow Engine

- **Engine:** Nextflow
- **DSL Version:** 2

## ECR Container Setup (Required)

AWS HealthOmics private workflows require container images to be stored in Amazon ECR with proper permissions.

### ECR Repository Policy

The CDK stack automatically creates an ECR repository with the required HealthOmics permissions. The repository policy grants `omics.amazonaws.com` service principal access to pull images:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "OmicsWorkflowAccess",
            "Effect": "Allow",
            "Principal": {
                "Service": "omics.amazonaws.com"
            },
            "Action": [
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability"
            ]
        }
    ]
}
```

Reference: [Amazon ECR Permissions for AWS HealthOmics](https://docs.aws.amazon.com/omics/latest/dev/permissions-ecr.html)

### Push Container Image to ECR

After deploying the CDK stack, push the VEP container image to ECR:

```bash
# Set variables
export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REGISTRY=${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin ${ECR_REGISTRY}

# Pull public image
docker pull quay.io/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0

# Tag for ECR
docker tag quay.io/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0 \
  ${ECR_REGISTRY}/quay/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0

# Push to ECR
docker push ${ECR_REGISTRY}/quay/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0
```

### Manual ECR Policy Setup (if needed)

If you need to manually add the policy to an existing ECR repository:

```bash
# Create policy file
cat > ecr-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "OmicsWorkflowAccess",
            "Effect": "Allow",
            "Principal": {
                "Service": "omics.amazonaws.com"
            },
            "Action": [
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability"
            ]
        }
    ]
}
EOF

# Apply policy
aws ecr set-repository-policy \
  --repository-name quay/biocontainers/ensembl-vep \
  --policy-text file://ecr-policy.json \
  --region ${AWS_REGION}
```

## Directory Structure

```
vep/
├── nextflow/
│   ├── main.nf              # Main workflow file
│   └── modules/
│       └── ensemblvep/
│           └── main.nf      # VEP module
├── omics/
│   └── workflow-param-desc.json  # Parameter template for HealthOmics
└── test_data/
    ├── sample_manifest_NA12878.csv    # Sample 1 manifest
    ├── sample_manifest_NA12878_2.csv  # Sample 2 manifest
    └── sample_manifest_with_test_data.csv  # Original test manifest
```

## Usage Examples

### Running via AWS HealthOmics

```bash
aws omics start-run \
  --workflow-id <workflow-id> \
  --role-arn <omics-service-role-arn> \
  --output-uri s3://output-bucket/outputs/ \
  --parameters '{
    "vcf": "s3://bucket/sample.vcf.gz",
    "vep_cache": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/databases/vep/",
    "vep_cache_version": "110",
    "vep_species": "homo_sapiens",
    "vep_genome": "GRCh38",
    "ecr_registry": "123456789012.dkr.ecr.us-east-1.amazonaws.com",
    "id": "sample_001"
  }'
```

### Triggered Automatically

This workflow is automatically triggered by EventBridge when the upstream GATK-BP workflow completes successfully. The Lambda function (`post_initial_workflow_lambda`) passes the VCF output from GATK-BP as input to VEP.

## VEP Cache

The workflow uses pre-cached VEP annotation data stored in S3. AWS provides public VEP cache files in region-specific buckets:

```
s3://aws-genomics-static-{region}/omics-tutorials/data/databases/vep/
```

Supported cache versions and genomes:
- **Version:** 110
- **Genome:** GRCh38
- **Species:** homo_sapiens

## Output

The workflow produces annotated VCF files with variant effect predictions including:
- Gene and transcript annotations
- Protein position and amino acid changes
- SIFT and PolyPhen predictions
- Regulatory feature annotations
- Known variant identifiers (dbSNP, COSMIC, etc.)

## Test Data

Sample manifests are provided in the `test_data/` directory for testing the complete pipeline:

1. **sample_manifest_NA12878.csv** - NA12878 Sample_U0a read group
2. **sample_manifest_NA12878_2.csv** - NA12878 Sample_U0b read group

To run a demo:
```bash
# Replace {aws-region} with your actual region (e.g., us-east-1)
# Upload manifest to trigger the pipeline
aws s3 cp sample_manifest_NA12878.csv s3://INPUT_BUCKET/fastqs/
```

## References

- [Ensembl VEP Documentation](https://www.ensembl.org/info/docs/tools/vep/index.html)
- [AWS HealthOmics Documentation](https://docs.aws.amazon.com/omics/)
- [nf-core/ensemblvep](https://nf-co.re/modules/ensemblvep)
