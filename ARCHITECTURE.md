# LIMS Genomics Pipeline - Architecture & Deployment Guide

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [CDK Stack Structure](#3-cdk-stack-structure)
4. [Pipeline Data Flow](#4-pipeline-data-flow)
5. [Step Functions State Machine](#5-step-functions-state-machine)
6. [DynamoDB Data Model](#6-dynamodb-data-model)
7. [API Gateway Endpoints](#7-api-gateway-endpoints)
8. [Lambda Functions Reference](#8-lambda-functions-reference)
9. [Authentication & Multi-Tenancy](#9-authentication--multi-tenancy)
10. [Frontend Dashboard](#10-frontend-dashboard)
11. [Deployment Guide](#11-deployment-guide)
12. [Security Architecture](#12-security-architecture)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Overview

LIMS Genomics Pipeline은 **Laboratory Information Management System (LIMS)**과 **AWS HealthOmics**를 통합하여 유전체 분석 파이프라인을 자동화하는 시스템입니다.

### 핵심 기능

- **GATK (Germline Short Variant Discovery)**: Ready2Run 워크플로우를 통한 FASTQ-to-VCF 변환
- **VEP (Variant Effect Predictor)**: 변이 주석(annotation) 분석
- **Admin Approval**: 분석 결과에 대한 관리자 승인/반려 워크플로우
- **Multi-Tenant Isolation**: 조직(Organization)별 데이터 격리
- **Role-Based Access Control**: Cognito 기반 admin/operator/viewer 역할 관리

### 두 가지 파이프라인 경로

| 경로 | 트리거 | 용도 |
|------|--------|------|
| **Path 1: EventBridge** | S3에 CSV 업로드 | 단순 배치 실행 (approval 없음) |
| **Path 2: LIMS Orchestration** | API Gateway POST 요청 | 전체 워크플로우 (GATK → VEP → Approval) |

두 경로 모두 동일한 HealthOmics 워크플로우와 EventBridge 이벤트를 공유합니다. `post_initial_workflow_lambda`는 `SOURCE=STEP_FUNCTIONS` 태그를 확인하여 Step Functions가 관리하는 실행에 대한 중복 VEP 실행을 방지합니다.

---

## 2. Architecture Diagram

```
                                    LIMS Genomics Pipeline Architecture
 ================================================================================================================================

  [LIMS / Mock LIMS]                                           [Admin Dashboard]
        |                                                      https://<your-cloudfront-domain>
        | POST /analysis/start                                        |
        v                                                             v
  +------------------+    +---------+    +----------------------------+---------------------------+
  | API Gateway      |<-->| Cognito |    | CloudFront + S3 (OAC)                                 |
  | (REST, v1 stage) |    | Hosted  |    | index.html / samples / status / approvals / results   |
  | + Cognito Auth   |    | UI      |    +----------------------------------------------------------+
  +------------------+    +---------+
        |
        v
  +----------------------------------------------------------------------+
  |                    Step Functions State Machine                       |
  |                  "lims-genomics-genomics-pipeline"                    |
  |                                                                      |
  |  ValidateInput --> InitializeDynamoDB --> StartGATKWorkflow           |
  |       |                                       |                      |
  |       |                          [start_gatk Lambda]                 |
  |       |                            omics.StartRun()                  |
  |       |                                       |                      |
  |       |                          WaitForGATKCompletion               |
  |       |                          (waitForTaskToken, 24h)             |
  |       |                                       |                      |
  |       |                          StartVEPWorkflow                    |
  |       |                            [start_vep Lambda]                |
  |       |                            omics.StartRun()                  |
  |       |                                       |                      |
  |       |                          WaitForVEPCompletion                |
  |       |                          (waitForTaskToken, 24h)             |
  |       |                                       |                      |
  |       |                          PrepareForApproval                  |
  |       |                            [prepare_approval Lambda]         |
  |       |                            SNS notification                  |
  |       |                                       |                      |
  |       |                          WaitForAdminApproval                |
  |       |                          (waitForTaskToken, 7 days)          |
  |       |                               /          \                   |
  |       |                         APPROVED      REJECTED               |
  |       |                              |              |                |
  |       |                      FinalizeApproved  FinalizeRejected      |
  |       |                                                              |
  |       +--- Error --> HandleFailure --> SendFailureNotification       |
  +----------------------------------------------------------------------+
        |                                       ^
        | omics.StartRun()                      | sfn.SendTaskSuccess()
        v                                       |
  +-------------------+                  +-------------------+
  | AWS HealthOmics   |  EventBridge     | workflow_status   |
  | - GATK (9500764)  |  COMPLETED/      | _handler Lambda   |
  | - VEP (private)   |  FAILED          | (DDB token lookup)|
  +-------------------+  ===========>   +-------------------+
        |                                       ^
        v                                       |
  +-------------------+                  +-------------------+
  | S3 Output Bucket  |                  | WorkflowTaskTokens|
  | /outputs/         |                  | DynamoDB Table    |
  +-------------------+                  | (RunId -> Token)  |
                                         +-------------------+

  +-------------------+    +---------------------+    +-------------------+
  | GenomicWorkflow   |    | LimsSamples         |    | SNS Topic         |
  | State Table       |    | Table               |    | (failure alerts)  |
  | (SampleID+TS)     |    | (SampleID)          |    |                   |
  | StatusIndex GSI   |    | OrganizationIndex   |    +-------------------+
  +-------------------+    +---------------------+           |
                                                             v
                                                      +-------------------+
                                                      | SES Email         |
                                                      | (results/alerts)  |
                                                      +-------------------+
```

---

## 3. CDK Stack Structure

4개 스택은 순서대로 배포되며, 각 스택은 이전 스택의 리소스를 참조합니다.

```
omics-eventbridge-solution  (1)
        |
        v
lims-cognito-auth           (2)
        |
        v
lims-orchestration          (3)  ← omics_resources + cognito_resources
        |
        v
lims-frontend               (4)  ← api_url + cognito_resources
```

### Stack 1: `omics-eventbridge-solution` (`stack/compute.py`)

HealthOmics 워크플로우 실행을 위한 기반 인프라를 구성합니다.

| 리소스 | 이름 | 설명 |
|--------|------|------|
| S3 Bucket | `healthomics-cka-input-{account}-{region}` | FASTQ 입력 파일 저장 |
| S3 Bucket | `healthomics-cka-output-{account}-{region}` | 워크플로우 결과 저장 |
| SNS Topic | `healthomics_workflow_status_topic` | 실패 알림 |
| IAM Role | `healthomics-omics-service-role` | HealthOmics 서비스 역할 (S3, ECR, CloudWatch, KMS) |
| IAM Role | `healthomics-lambda-role` | Path 1 Lambda 역할 |
| ECR Repository | `healthomics-vep` | VEP Docker 이미지 저장소 |
| CodeBuild Project | `healthomics-vep-image-build` | VEP 컨테이너 빌드 (배포 시 자동 실행) |
| HealthOmics Workflow | `vep` (Private, Nextflow) | VEP 주석 분석 워크플로우 |
| Lambda | `healthomics_initial_workflow_lambda` | S3 CSV 업로드 → GATK 실행 |
| Lambda | `healthomics_post_initial_workflow_lambda` | GATK 완료 → VEP 실행 |
| Lambda | `healthomics_notification_lambda` | VEP 완료 → 이메일 알림 |
| EventBridge Rule | COMPLETED 이벤트 | `post_initial_workflow_lambda` + `notification_lambda` 트리거 |
| EventBridge Rule | FAILED 이벤트 | SNS Topic으로 전달 |

**핵심 설정값:**
- GATK Ready2Run Workflow ID: `9500764`
- VEP Container: `ensembl-vep:106.1` (biocontainers)
- VEP Cache: `s3://aws-genomics-static-{region}/omics-tutorials/data/databases/vep/`

**Cross-Stack Export:**
`bucket_input`, `bucket_output`, `omics_role`, `lambda_role`, `sns_topic`, `vep_workflow_id`, `gatk_workflow_id`, `vep_container_image_uri`

---

### Stack 2: `lims-cognito-auth` (`stack/cognito_auth.py`)

사용자 인증 및 역할 관리를 담당합니다.

| 리소스 | 이름 | 설명 |
|--------|------|------|
| Cognito User Pool | `lims-genomics-users` | 사용자 풀 |
| Cognito Domain | `lims-genomics-{account}` | Hosted UI 도메인 |
| User Pool Group | `admin` (precedence: 1) | 전체 권한: 승인/반려, 결과 전송, 파이프라인 실행 |
| User Pool Group | `operator` (precedence: 2) | 파이프라인 실행 및 샘플 조회 |
| User Pool Group | `viewer` (precedence: 3) | 샘플 및 상태 조회 (읽기 전용) |
| Lambda | `lims-genomics-pre-token` | `custom:organization_id`를 JWT 클레임에 주입 |

**Custom Attributes:**
- `custom:organization_id` — 조직 식별자 (생성 시 설정, 불변)
- `custom:display_name` — 표시 이름 (변경 가능)

**Password Policy:** 12자 이상, 대/소문자 + 숫자 + 특수문자 필수, MFA 선택

**Cross-Stack Export:** `user_pool`, `user_pool_id`, `cognito_domain_prefix`

---

### Stack 3: `lims-orchestration` (`stack/lims_orchestration.py`)

LIMS 오케스트레이션의 핵심 스택입니다. Step Functions, API Gateway, DynamoDB, Lambda를 모두 포함합니다.

#### DynamoDB Tables

| 테이블 | Partition Key | Sort Key | GSI | 용도 |
|--------|---------------|----------|-----|------|
| `GenomicWorkflowState` | `SampleID` (S) | `Timestamp` (S) | `StatusIndex` (Status + Timestamp) | 파이프라인 상태 추적 |
| `LimsSamples` | `SampleID` (S) | - | `OrganizationIndex` (OrganizationID + SampleID) | LIMS 샘플 레지스트리 |
| `WorkflowTaskTokens` | `RunId` (S) | - | - (TTL 활성화) | HealthOmics RunId ↔ SFN Task Token 매핑 |

#### Lambda Functions (14개)

| Lambda | 핸들러 | 용도 | 인증 역할 |
|--------|--------|------|-----------|
| `lims-genomics-start-gatk` | `start_gatk.handler` | GATK 워크플로우 시작 | SFN 내부 |
| `lims-genomics-start-vep` | `start_vep.handler` | VEP 워크플로우 시작 | SFN 내부 |
| `lims-genomics-store-token` | `store_token.handler` | Task Token 저장 (DDB) | SFN 내부 |
| `lims-genomics-prepare-approval` | `prepare_approval.handler` | SNS 승인 요청 발송 | SFN 내부 |
| `lims-genomics-store-approval-token` | `store_approval_token.handler` | 승인 Token 저장 | SFN 내부 |
| `lims-genomics-trigger-handler` | `trigger_handler.handler` | POST /analysis/start | operator+ |
| `lims-genomics-approval-handler` | `approval_handler.handler` | POST /admin/approve | admin |
| `lims-genomics-status-query` | `status_query.handler` | GET /analysis/status/{id} | viewer+ |
| `lims-genomics-pending-approvals` | `pending_approvals.handler` | GET /admin/pending | admin |
| `lims-genomics-list-samples` | `lims_samples.handler` | GET /lims/samples | viewer+ |
| `lims-genomics-approved-results` | `approved_results.handler` | GET /admin/results | admin |
| `lims-genomics-send-results` | `send_results.handler` | POST /admin/results/send | admin |
| `lims-genomics-workflow-status-handler` | `workflow_status_handler.handler` | EventBridge → SFN 콜백 | EventBridge |
| `lims-genomics-failure-notification` | `failure_notification.handler` | 파이프라인 실패 알림 | SFN 내부 |

#### Step Functions State Machine

- **이름:** `lims-genomics-genomics-pipeline`
- **타입:** STANDARD
- **로깅:** CloudWatch Logs (`/aws/stepfunctions/lims-genomics-pipeline`), ALL 레벨
- **ASL 정의:** `state_machine/genomics_pipeline.asl.json`

#### EventBridge Rule

- **패턴:** `source: aws.omics`, `detail-type: Run Status Change`, `status: COMPLETED|FAILED`
- **타겟:** `workflow_status_handler` Lambda

#### API Gateway

- **이름:** `lims-genomics-api`
- **스테이지:** `v1`
- **인증:** Cognito User Pool Authorizer
- **CORS:** CloudFront 도메인만 허용 (`https://<your-cloudfront-domain>`)
- **Throttling:** 50 req/s (burst: 100)

**Cross-Stack Export:** `api_id`

---

### Stack 4: `lims-frontend` (`stack/frontend.py`)

정적 웹 대시보드를 호스팅합니다.

| 리소스 | 설명 |
|--------|------|
| S3 Bucket | 프라이빗 버킷 (OAC 접근만 허용, BlockPublicAccess: BLOCK_ALL) |
| CloudFront Distribution | HTTPS, OAC, SPA 라우팅 (403/404 → index.html) |
| Cognito App Client | `lims-dashboard` (CfnUserPoolClient, 순환 참조 방지) |
| `config.js` | 배포 시 자동 생성 (API URL + Cognito 설정) |

**`config.js` 내용 (배포 시 CDK가 생성):**
```javascript
window.LIMS_CONFIG = {
  apiUrl: 'https://{api_id}.execute-api.us-east-1.amazonaws.com/v1',
  cognitoUserPoolId: '{pool_id}',
  cognitoClientId: '{client_id}',
  cognitoHostedUiDomain: 'https://{prefix}.auth.us-east-1.amazoncognito.com',
  callbackUrl: 'https://{cf_domain}/callback.html',
  logoutUrl: 'https://{cf_domain}/index.html',
};
```

---

## 4. Pipeline Data Flow

### Path 2: LIMS Orchestration (주요 경로)

```
1. 사용자가 웹 대시보드에서 "Run Pipeline" 클릭
   └── POST /v1/analysis/start (Bearer token)

2. trigger_handler Lambda
   ├── LIMS 페이로드 검증 (validators.py)
   ├── 인증 컨텍스트 추출 (organization_id, user_id, email)
   └── Step Functions StartExecution

3. Step Functions 실행
   ├── InitializeDynamoDB: 상태 레코드 생성 (Status=INITIALIZED)
   ├── StartGATKWorkflow: start_gatk Lambda → omics.StartRun()
   │   └── GATK Ready2Run 워크플로우 시작 (workflow ID: 9500764)
   ├── WaitForGATKCompletion: waitForTaskToken (24시간 타임아웃)
   │   ├── store_token: {RunId → TaskToken} DDB 저장
   │   └── [대기] EventBridge COMPLETED 이벤트 수신까지
   ├── UpdateStateGATKCompleted: GATKOutputUri 저장
   ├── StartVEPWorkflow: start_vep Lambda → omics.StartRun()
   │   └── VEP Private 워크플로우 시작
   ├── WaitForVEPCompletion: waitForTaskToken (24시간 타임아웃)
   ├── UpdateStateVEPCompleted: VEPOutputUri 저장
   ├── PrepareForApproval: SNS로 관리자 승인 요청 발송
   ├── WaitForAdminApproval: waitForTaskToken (7일 타임아웃)
   │   └── [대기] 관리자가 대시보드에서 승인/반려까지
   └── FinalizeApproved / FinalizeRejected

4. EventBridge 콜백 메커니즘 (비동기)
   ├── HealthOmics Run 완료 → EventBridge "Run Status Change" 이벤트
   ├── workflow_status_handler Lambda가 이벤트 수신
   ├── WorkflowTaskTokens 테이블에서 RunId로 TaskToken 조회
   └── sfn.SendTaskSuccess(token, {output_uri}) 또는 SendTaskFailure

5. 관리자 승인 메커니즘
   ├── 관리자가 대시보드의 Pending Approvals 페이지에서 승인/반려
   ├── POST /v1/admin/approve (approval_handler Lambda)
   ├── GenomicWorkflowState에서 ApprovalTaskToken 조회
   └── sfn.SendTaskSuccess 또는 SendTaskFailure("ApprovalRejected")
```

### Path 1: EventBridge (S3 트리거)

```
1. S3에 CSV 파일 업로드: s3://{input-bucket}/fastqs/*.csv
2. initial_workflow_lambda: CSV 파싱 → GATK Ready2Run 시작
3. EventBridge COMPLETED → post_initial_workflow_lambda: VCF 찾기 → VEP 시작
   └── SOURCE 태그 확인: "STEP_FUNCTIONS"이면 스킵 (중복 방지)
4. EventBridge COMPLETED → notification_lambda: SES 이메일 (presigned URL 포함)
```

---

## 5. Step Functions State Machine

### 상태 전이도

```
                        ValidateInput
                             |
                      InitializeDynamoDB -----> [에러] HandleValidationFailure
                      (Status=INITIALIZED)                    |
                             |                        SendFailureNotification
                      StartGATKWorkflow -----> [에러] HandleWorkflowFailure
                             |                                |
                   UpdateStateGATKRunning             SendFailureNotification
                   (Status=GATK_RUNNING)
                             |
                   WaitForGATKCompletion -----> [타임아웃] HandleWorkflowTimeout
                   (waitForTaskToken, 24h)                    |
                             |                        SendFailureNotification
                   UpdateStateGATKCompleted
                   (Status=GATK_COMPLETED)
                   (GATKOutputUri 저장)
                             |
                      StartVEPWorkflow ------> [에러] HandleWorkflowFailure
                             |
                   UpdateStateVEPRunning
                   (Status=VEP_RUNNING)
                             |
                   WaitForVEPCompletion -----> [타임아웃] HandleWorkflowTimeout
                   (waitForTaskToken, 24h)
                             |
                   UpdateStateVEPCompleted
                   (Status=VEP_COMPLETED)
                   (VEPOutputUri 저장)
                             |
                     PrepareForApproval -----> [에러] HandleWorkflowFailure
                     (SNS 알림 발송)
                             |
                   WaitForAdminApproval -----> [타임아웃 7일] HandleApprovalTimeout
                   (waitForTaskToken)    \---> [반려] FinalizeRejected
                             |                          (Status=COMPLETED_REJECTED)
                      FinalizeApproved
                      (Status=COMPLETED_APPROVED)
                             |
                      PipelineSucceeded
```

### 상태 라이프사이클

```
정상 흐름:
  INITIALIZED → GATK_RUNNING → GATK_COMPLETED → VEP_RUNNING → VEP_COMPLETED
    → AWAITING_APPROVAL → COMPLETED_APPROVED 또는 COMPLETED_REJECTED

에러 상태:
  VALIDATION_FAILED  — 입력 검증 실패
  WORKFLOW_FAILED    — GATK/VEP 실행 실패
  WORKFLOW_TIMEOUT   — 24시간 내 HealthOmics 완료 안됨
  APPROVAL_TIMEOUT   — 7일 내 관리자 승인 안됨
```

### waitForTaskToken 패턴 상세

Step Functions의 비동기 콜백 패턴으로 HealthOmics 실행 완료를 기다립니다.

```
[Step Functions]                    [DynamoDB]              [EventBridge]           [Lambda]
     |                                  |                        |                     |
     |--- invoke store_token ---------> |                        |                     |
     |    {RunId, TaskToken}            |                        |                     |
     |    ----- putItem --------------> |                        |                     |
     |                                  |                        |                     |
     |<--- 대기 (24시간 타임아웃) ---    |                        |                     |
     |                                  |                        |                     |
     |                                  |    Run COMPLETED -->   |                     |
     |                                  |                   workflow_status_handler     |
     |                                  |    <-- getItem -----   |                     |
     |                                  |    {TaskToken} ------> |                     |
     |                                  |                        |                     |
     |<--------- SendTaskSuccess({output_uri}) ----------------------------------------|
     |                                  |                        |                     |
     |--- 다음 상태로 진행 -->          |                        |                     |
```

---

## 6. DynamoDB Data Model

### GenomicWorkflowState

파이프라인 실행 상태를 추적합니다. SFN ASL에서 직접 DynamoDB SDK 통합으로 업데이트됩니다.

```
PK: SampleID (String)   SK: Timestamp (String, $$.Execution.StartTime)

속성:
├── ProjectID (String)
├── SubmitterEmail (String)
├── ReferenceGenome (String)       — "GRCh38" | "hg38"
├── AnalysisType (String)          — "WGS" | "WES" | "PANEL"
├── ExecutionArn (String)          — Step Functions Execution ARN
├── OrganizationID (String)        — 테넌트 격리 키
├── Status (String)                — 현재 상태 (GSI PK)
├── GATKRunId (String)             — HealthOmics GATK Run ID
├── VEPRunId (String)              — HealthOmics VEP Run ID
├── GATKOutputUri (String)         — s3://output-bucket/outputs/{run-id}
├── VEPOutputUri (String)          — s3://output-bucket/outputs/{run-id}
├── FastqR1 (String)               — 입력 FASTQ R1 경로
├── FastqR2 (String)               — 입력 FASTQ R2 경로
├── ApprovalTaskToken (String)     — 관리자 승인 대기 Token
├── ErrorInfo (String)             — 에러 시 JSON 문자열
└── UpdatedAt (String)             — 마지막 상태 변경 시간

GSI: StatusIndex
├── PK: Status (String)
└── SK: Timestamp (String)
```

### LimsSamples

LIMS에서 관리하는 샘플 레지스트리입니다.

```
PK: SampleID (String)

속성:
├── OrganizationID (String)
├── PatientID (String)
├── ProjectID (String)
├── SubmitterEmail (String)
├── Source (String)                 — "ClarityLIMS" | "ClarityLIMS_Mock"
├── ReferenceGenome (String)
├── AnalysisType (String)
├── FastqR1 (String)
├── FastqR2 (String)
└── CreatedAt (String)

GSI: OrganizationIndex
├── PK: OrganizationID (String)
└── SK: SampleID (String)
```

### WorkflowTaskTokens

HealthOmics RunId와 Step Functions TaskToken의 매핑 테이블입니다.

```
PK: RunId (String)

속성:
├── TaskToken (String)             — Step Functions Task Token
├── ExecutionArn (String)
├── WorkflowType (String)          — "GATK" | "VEP"
├── SampleId (String)
└── TTL (Number)                   — 생성 + 604800 (7일)
```

---

## 7. API Gateway Endpoints

**Base URL:** `https://<your-api-id>.execute-api.us-east-1.amazonaws.com/v1`

| Method | Path | Lambda | 필요 역할 | 설명 |
|--------|------|--------|-----------|------|
| POST | `/analysis/start` | trigger_handler | operator | 파이프라인 실행 시작 |
| GET | `/analysis/status/{sample_id}` | status_query | viewer | 샘플 상태 조회 |
| POST | `/admin/approve` | approval_handler | admin | 결과 승인/반려 |
| GET | `/admin/pending` | pending_approvals | admin | 승인 대기 목록 |
| GET | `/admin/results` | approved_results | admin | 승인된 결과 목록 |
| POST | `/admin/results/send` | send_results | admin | 결과 이메일 발송 |
| GET | `/lims/samples` | lims_samples | viewer | LIMS 샘플 목록 |

### POST /analysis/start 요청 형식

```json
{
  "source": "ClarityLIMS",
  "event_type": "analysis.requested",
  "data": {
    "sample_id": "SAM-001",
    "project_id": "PROJ-001",
    "patient_id": "PAT-001",
    "submitter_email": "user@example.com",
    "reference_genome": "GRCh38",
    "analysis_type": "WGS",
    "fastq_paths": {
      "r1": "s3://input-bucket/reads/sample_R1.fastq.gz",
      "r2": "s3://input-bucket/reads/sample_R2.fastq.gz"
    }
  }
}
```

**입력 검증 규칙 (`validators.py`):**
- `source`: `ClarityLIMS` 또는 `ClarityLIMS_Mock`
- `event_type`: `analysis.requested`
- `reference_genome`: `GRCh38` 또는 `hg38`
- `analysis_type`: `WGS`, `WES`, `PANEL`
- `fastq_paths.r1`, `fastq_paths.r2`: 필수

### POST /admin/approve 요청 형식

```json
{
  "sample_id": "SAM-001",
  "timestamp": "2026-02-23T08:00:00.000Z",
  "decision": "APPROVED",
  "comment": "Results verified"
}
```

`decision` 값: `APPROVED` 또는 `REJECTED`

---

## 8. Lambda Functions Reference

### Environment Variables (공통)

모든 오케스트레이션 Lambda에 설정되는 공통 환경변수:

| 변수 | 값 | 설명 |
|------|-----|------|
| `WORKFLOW_STATE_TABLE` | `GenomicWorkflowState` | 상태 추적 테이블 |
| `TASK_TOKENS_TABLE` | `WorkflowTaskTokens` | 토큰 매핑 테이블 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `ALLOWED_ORIGIN` | `https://<your-cloudfront-domain>` | CORS 허용 오리진 |

### Lambda별 추가 환경변수

| Lambda | 추가 변수 |
|--------|-----------|
| `start_gatk` | `OMICS_ROLE`, `OUTPUT_S3_LOCATION`, `GATK_WORKFLOW_ID` |
| `start_vep` | `OMICS_ROLE`, `OUTPUT_S3_LOCATION`, `VEP_WORKFLOW_ID`, `VEP_CONTAINER_IMAGE`, `VEP_SPECIES`, `VEP_DIR_CACHE`, `VEP_CACHE_VERSION`, `VEP_GENOME` |
| `prepare_approval` | `SNS_TOPIC_ARN`, `ADMIN_EMAIL` |
| `trigger_handler` | `STATE_MACHINE_ARN` |
| `lims_samples` | `LIMS_SAMPLES_TABLE` |
| `send_results` | `SES_SENDER_EMAIL`, `USER_POOL_ID` |
| `failure_notification` | `SNS_TOPIC_ARN`, `USER_POOL_ID` |

### HealthOmics StartRun 제약사항

- **TPS 제한:** 1.0 req/s
- **Retry 설정:** `botocore.config.Config(retries={'mode': 'adaptive', 'max_attempts': 10})`
- `start_gatk`와 `start_vep` 모두 adaptive retry 적용

### SES 이메일 처리 (`send_results.py`)

```python
# SES 프로덕션/샌드박스 자동 감지
def _is_ses_sandbox():
    quota = ses.get_send_quota()
    return quota.get('Max24HourSend', 0) <= 200  # 샌드박스: 200/일 제한

# 샌드박스인 경우 인증된 수신자만 필터링
def _filter_verified_recipients(recipients):
    if not _is_ses_sandbox():
        return recipients, []  # 프로덕션: 필터링 불필요
    response = ses.get_identity_verification_attributes(Identities=recipients)
    # verified / skipped 분류
```

---

## 9. Authentication & Multi-Tenancy

### Cognito 인증 흐름

```
[브라우저]                          [Cognito Hosted UI]               [API Gateway]
    |                                      |                               |
    |--- 로그인 리다이렉트 ------------>   |                               |
    |                                      |                               |
    |<--- Authorization Code -----------   |                               |
    |                                      |                               |
    |--- POST /oauth2/token ------------->  |                               |
    |    (code + PKCE)                     |                               |
    |                                      |                               |
    |<--- {id_token, access_token,         |                               |
    |      refresh_token} ----------------  |                               |
    |                                      |                               |
    |--- GET /lims/samples ------------------------------------------------>|
    |    Authorization: Bearer {id_token}                                   |
    |                                                                       |
    |<--- 200 OK (조직별 필터링된 데이터) ----------------------------------|
```

### Pre-Token-Generation Lambda

Cognito가 토큰을 발급하기 전에 `custom:organization_id`를 JWT 클레임에 주입합니다:

```python
def handler(event, context):
    user_attributes = event['request']['userAttributes']
    org_id = user_attributes.get('custom:organization_id', '')
    event['response']['claimsOverrideDetails'] = {
        'claimsToAddOrOverride': {
            'organization_id': org_id,
        }
    }
    return event
```

### 역할 기반 접근 제어 (RBAC)

`@require_auth(role)` 데코레이터가 모든 API Lambda에 적용됩니다:

```
역할 계층: admin > operator > viewer

admin    — approve/reject, send results, pending/results 조회, pipeline 실행, 샘플/상태 조회
operator — pipeline 실행, 샘플/상태 조회
viewer   — 샘플/상태 조회 (읽기 전용)
```

### Multi-Tenant 데이터 격리

모든 데이터 조회 시 JWT에서 추출한 `organization_id`로 필터링합니다:

- `LimsSamples`: `OrganizationIndex` GSI로 조직별 쿼리
- `GenomicWorkflowState`: 결과 반환 시 `OrganizationID` 필터링
- Step Functions 실행 시 `organization_id`가 입력에 포함되어 DynamoDB 레코드에 저장

---

## 10. Frontend Dashboard

### 페이지 구성

| 파일 | URL | 역할 | 필요 권한 |
|------|-----|------|-----------|
| `index.html` | `/` | 랜딩 페이지, Cognito 로그인 리다이렉트 | - |
| `callback.html` | `/callback.html` | OAuth2 콜백, 토큰 교환 | - |
| `samples.html` | `/samples.html` | LIMS 샘플 목록 + "Run Pipeline" 버튼 | viewer+ |
| `status.html` | `/status.html` | 파이프라인 상태 검색 | viewer+ |
| `approvals.html` | `/approvals.html` | 승인 대기 목록 (승인/반려) | admin |
| `results.html` | `/results.html` | 승인된 결과 + 이메일 발송 | admin |

### Shared Modules (`frontend/shared/`)

| 모듈 | 기능 |
|------|------|
| `auth.js` | OAuth2 토큰 관리 (sessionStorage), `Auth.requireAuth()`, `Auth.hasRole()`, 자동 리프레시 |
| `api.js` | API 클라이언트 (Bearer token), 401 시 자동 토큰 갱신 |
| `nav.js` | 네비게이션 바 (역할별 메뉴 가시성 제어) |
| `ui.js` | `escapeHtml()`, 상태 뱃지, 토스트, 모달, 날짜 포맷 |

### config.js

CDK 배포 시 `Source.data()` 를 통해 자동 생성됩니다. Cognito 설정과 API URL을 포함합니다.

---

## 11. Deployment Guide

### Prerequisites

- AWS CLI 설정 완료 (us-east-1 리전)
- Node.js 18+ (CDK CLI)
- Python 3.12+ (Lambda 런타임)
- Docker (VEP 이미지 빌드용)

### 초기 설정

```bash
cd aws-healthomics-eventbridge-integration

# 가상 환경 생성
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# CDK Bootstrap (최초 1회)
cdk bootstrap aws://{ACCOUNT_ID}/us-east-1
```

### constants.py 설정

배포 전 반드시 설정해야 하는 값:

```python
DEV_CONFIG = {
    "AWS_REGION": "us-east-1",                        # 필수: HealthOmics Ready2Run은 us-east-1만 지원
    "SES_SENDER_EMAIL": "your-email@example.com",     # SES 발신 이메일 (인증 필요)
    "SES_RECIPIENT_EMAIL": "your-email@example.com",  # 기본 수신 이메일
    "ADMIN_EMAIL": "admin@example.com",               # 관리자 이메일
    "APPROVAL_TIMEOUT_DAYS": 7,                       # 승인 타임아웃 (일)
    "FRONTEND_URL": "",                               # 최초 배포 후 CloudFront URL 설정
}
```

### 배포 순서

```bash
# 1. 모든 스택 합성 (검증)
cdk synth

# 2. 전체 스택 배포 (의존성 순서 자동)
cdk deploy --all --require-approval never

# 또는 개별 배포:
cdk deploy omics-eventbridge-solution   # (1) HealthOmics + EventBridge
cdk deploy lims-cognito-auth            # (2) Cognito User Pool
cdk deploy lims-orchestration           # (3) Step Functions + API Gateway
cdk deploy lims-frontend                # (4) S3 + CloudFront
```

### 배포 후 필수 작업

**1. FRONTEND_URL 설정 (최초 배포 시만)**

첫 배포 후 CloudFront URL을 `constants.py`에 설정하고 재배포합니다:

```python
"FRONTEND_URL": "https://{distribution-id}.cloudfront.net",
```

```bash
cdk deploy lims-orchestration  # CORS 설정 반영
```

**2. SES 이메일 인증**

```bash
aws ses verify-email-identity --email-address your-email@example.com
```

SES 샌드박스 모드에서는 발신자와 수신자 모두 인증 필요합니다. 프로덕션으로 전환하려면 AWS Console에서 SES 프로덕션 액세스를 요청합니다.

**3. 테스트 데이터 시딩**

```bash
# Cognito 사용자 + LIMS 샘플 생성
python scripts/seed_test_data.py --user-pool-id {POOL_ID} --region us-east-1

# 기존 데이터에 OrganizationID 마이그레이션
python scripts/migrate_add_org_id.py --region us-east-1 --execute
```

### 테스트

```bash
# 전체 테스트 (162개)
pytest tests/

# 특정 테스트 파일
pytest tests/test_validators.py
pytest tests/test_send_results.py -v
```

### 업데이트 배포

코드 변경 후:

```bash
# 합성 → 테스트 → 배포
cdk synth && pytest tests/ && cdk deploy --all --require-approval never
```

---

## 12. Security Architecture

### IAM Least Privilege

| 리소스 | 스코핑 |
|--------|--------|
| HealthOmics | `arn:aws:omics:{region}:{account}:run/*`, `arn:aws:omics:{region}:{account}:workflow/*`, `arn:aws:omics:us-east-1::workflow/*` |
| S3 | 입력/출력 버킷 ARN만 허용 |
| DynamoDB | 테이블별 `grant_read_write_data()` |
| SES | `arn:aws:ses:{region}:{account}:identity/{sender-email}` |
| Step Functions | `arn:aws:states:{region}:{account}:stateMachine:lims-genomics-*` |
| Cognito | 특정 User Pool ARN의 `ListUsersInGroup`만 |
| IAM PassRole | HealthOmics 서비스 역할 ARN만 |
| KMS | `arn:aws:kms:{region}:{account}:key/*` |

### CORS 설정

- **API Gateway:** CloudFront 도메인만 허용 (`allowed_origin` 변수)
- **Gateway Responses (4xx/5xx):** 동일 도메인으로 CORS 헤더 설정
- **Lambda 응답:** `cors_headers()` 함수로 일관된 CORS 헤더 반환

### 프론트엔드 보안

- S3 버킷: `BlockPublicAccess.BLOCK_ALL`, OAC를 통한 CloudFront만 접근
- HTTPS 강제: `ViewerProtocolPolicy.REDIRECT_TO_HTTPS`
- 토큰 저장: `sessionStorage` (탭 닫으면 삭제)
- XSS 방지: `ui.js`의 `escapeHtml()` 유틸리티

### 비밀번호 정책

- Cognito: 12자 이상, 대/소/숫자/특수문자 필수
- MFA: Optional (TOTP)
- 시드 스크립트: `secrets` 모듈로 랜덤 임시 비밀번호 생성

---

## 13. Troubleshooting

### HealthOmics `AccessDeniedException` on `StartRun`

**원인:** IAM 정책에서 Ready2Run 워크플로우 ARN 패턴이 올바르지 않음

Ready2Run 워크플로우는 `arn:aws:omics:us-east-1::workflow/{id}` 형식입니다 (빈 계정 ID, `ready2run/` 접두사 없음).

**해결:** IAM 리소스에 `arn:aws:omics:us-east-1::workflow/*` 패턴 사용

### Step Functions `prepare_approval` 실패 (SNS NotFound)

**원인:** CDK 배포 중 SNS 토픽 일시적 불가용

**해결:** 배포 완료 후 재실행, 또는 DynamoDB 상태 수동 업데이트

### SES `MessageRejected` (Unverified Recipients)

**원인:** SES 샌드박스 모드에서 미인증 수신자에게 전송 시도

**해결:**
1. 수신자 이메일 인증: `aws ses verify-email-identity --email-address {email}`
2. 또는 SES 프로덕션 액세스 요청

### SES 샌드박스 감지 오류 (항상 True 반환)

**원인:** SES v1 클라이언트(`boto3.client('ses')`)에서 v2 전용 API(`get_account()`) 호출

**해결:** `get_send_quota()` API만 사용 (`Max24HourSend <= 200`이면 샌드박스)

### EventBridge에서 중복 VEP 실행

**원인:** Path 1과 Path 2 모두 EventBridge COMPLETED 이벤트를 수신

**해결:** `post_initial_workflow_lambda`가 `SOURCE=STEP_FUNCTIONS` 태그를 확인하여 SFN 관리 실행을 스킵

### DynamoDB에 Output URI 누락

**원인:** Step Functions 실행이 중간에 실패하면 `UpdateStateGATKCompleted`/`UpdateStateVEPCompleted` 상태를 건너뜀

**해결:** HealthOmics `GetRun` API로 실제 output URI 확인 후 DynamoDB 수동 업데이트

---

## Appendix: Resource Inventory

### 현재 배포된 리소스 (us-east-1)

| 리소스 | 값 |
|--------|-----|
| CloudFront URL | `https://<your-cloudfront-domain>` |
| API Gateway URL | `https://<your-api-id>.execute-api.us-east-1.amazonaws.com/v1/` |
| Cognito User Pool ID | `<your-user-pool-id>` |
| Cognito Domain | `https://lims-genomics-<account-id>.auth.us-east-1.amazoncognito.com` |
| Cognito Client ID | `<your-client-id>` |
| State Machine | `lims-genomics-genomics-pipeline` |
| GATK Workflow ID | `9500764` (Ready2Run) |
| VEP Workflow ID | `<your-vep-workflow-id>` (Private) |
| SES Sender | `<your-ses-email>` |
| AWS Account | `<account-id>` |
| Region | `us-east-1` |
