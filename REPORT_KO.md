# AWS HealthOmics EventBridge 통합 솔루션 분석 보고서

## 1. 솔루션 개요

### 1.1 목적
이 솔루션은 AWS HealthOmics와 Amazon EventBridge를 활용하여 이벤트 기반의 완전 자동화된 유전체 분석 파이프라인을 구축합니다. 고객이 자체 계정에서 재사용할 수 있는 샘플 코드와 인프라 코드(IaC)를 제공합니다.

### 1.2 주요 기능
- **자동 워크플로우 실행**: S3에 CSV 파일 업로드 시 자동으로 GATK-BP 워크플로우 시작
- **이벤트 기반 체이닝**: GATK-BP 완료 시 자동으로 VEP 워크플로우 실행
- **실패 알림**: 워크플로우 실패 시 SNS를 통한 이메일 알림

### 1.3 아키텍처

```
S3 Upload (CSV) → Lambda 1 → HealthOmics GATK-BP → EventBridge → Lambda 2 → VEP Workflow
                                    ↓ (실패 시)
                              SNS Notification
```

---

## 2. 기술 구성 요소

### 2.1 AWS 서비스
| 서비스 | 역할 |
|--------|------|
| AWS HealthOmics | 유전체 워크플로우 실행 (GATK-BP, VEP) |
| Amazon S3 | 입력 데이터 및 결과 저장 |
| AWS Lambda | 워크플로우 트리거 및 이벤트 처리 |
| Amazon EventBridge | 이벤트 기반 자동화 |
| Amazon SNS | 실패 알림 전송 |
| AWS IAM | 보안 및 권한 관리 |
| AWS CDK | 인프라 코드 배포 |

### 2.2 워크플로우
1. **GATK-BP Germline fq2vcf** (Ready2Run ID: 9500764)
   - FASTQ → BAM → VCF 변환
   - 30x 전장 유전체 분석용

2. **VEP (Variant Effect Predictor)**
   - Nextflow 기반 프라이빗 워크플로우
   - VCF 변이 주석(annotation) 처리

---

## 3. 분석 결과 및 발견된 문제점

### 3.1 버그 수정 (완료)

#### 3.1.1 S3 버킷 ARN 콤마 누락 (Critical)
**파일:** `stack/compute.py:175-176`

**수정 전 (버그):**
```python
f"arn:aws:s3:::omics-{aws_region}"
f"arn:aws:s3:::omics-{aws_region}/*"
```
- 콤마가 누락되어 두 문자열이 연결됨
- 결과: `"arn:aws:s3:::omics-us-east-1arn:aws:s3:::omics-us-east-1/*"`
- S3 접근 권한 오류 발생 가능

**수정 후:**
```python
f"arn:aws:s3:::omics-{aws_region}",
f"arn:aws:s3:::omics-{aws_region}/*"
```

### 3.2 코드 현대화 (완료)

#### 3.2.1 Python 런타임 업그레이드
- **변경:** Python 3.8 → Python 3.12
- **파일:** `stack/compute.py` (lines 263, 295)
- **이유:** Python 3.8은 2024년 10월 EOL, 최신 보안 패치 및 성능 향상

#### 3.2.2 미사용 상수 제거
- **파일:** `constants.py`
- **제거 항목:**
  - `SQS_MESSAGE_VISIBILITY` - SQS 미사용
  - `REQUIREMENTS_FILE` - 참조되지 않음

---

## 4. 배포 가이드

### 4.1 사전 요구 사항
- AWS 계정 및 적절한 IAM 권한
- Node.js, npm, Python 3 설치
- AWS CLI 및 CDK CLI 설치

### 4.2 배포 단계

```bash
# 1. CDK 설치 및 부트스트랩
python3 -m pip install aws-cdk-lib
npm install -g aws-cdk
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>

# 2. 프로젝트 설정
cd aws-healthomics-eventbridge-integration
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 배포
cdk synth
cdk deploy --all
```

### 4.3 생성되는 리소스
- S3 버킷 2개 (입력/출력)
- Lambda 함수 2개 (초기/후속 워크플로우)
- HealthOmics 프라이빗 워크플로우 (VEP)
- EventBridge 규칙 2개
- SNS 토픽 1개
- IAM 역할 및 정책

---

## 5. 데모 실행 가이드

### 5.1 SNS 알림 구독
1. AWS 콘솔에서 SNS 토픽 (`*_workflow_status_topic`) 찾기
2. 이메일 주소로 구독 생성
3. 확인 이메일에서 구독 승인

### 5.2 테스트 데이터 실행

#### 샘플 1 실행
```bash
# {aws-region}을 실제 리전으로 변경 (예: us-east-1)
cd workflows/vep/test_data/

# 리전 변수 설정
export AWS_REGION=us-east-1
sed -i "s/{aws-region}/${AWS_REGION}/g" sample_manifest_NA12878.csv

# 입력 버킷으로 업로드 (버킷 이름은 CDK 출력에서 확인)
aws s3 cp sample_manifest_NA12878.csv s3://<INPUT_BUCKET>/fastqs/
```

#### 샘플 2 실행 (병렬 테스트)
```bash
sed -i "s/{aws-region}/${AWS_REGION}/g" sample_manifest_NA12878_2.csv
aws s3 cp sample_manifest_NA12878_2.csv s3://<INPUT_BUCKET>/fastqs/
```

### 5.3 실행 모니터링

```bash
# 실행 중인 워크플로우 확인
aws omics list-runs --max-results 10

# 특정 실행 상태 확인
aws omics get-run --id <RUN_ID>

# 실행 작업 목록
aws omics list-run-tasks --id <RUN_ID>
```

---

## 6. 비용 분석

### 6.1 예상 비용 (실행당)

| 구성 요소 | 예상 비용 | 비고 |
|-----------|-----------|------|
| S3 저장소 (1GB) | ~$0.023 | 월 기준 |
| GATK-BP 워크플로우 | ~$10.00 | 실행당 |
| VEP 워크플로우 | ~$0.17 | 실행당 |
| Lambda | ~$0.01 | 무시할 수준 |
| EventBridge | $0.00 | 프리 티어 |
| SNS | $0.00 | 프리 티어 |
| **총 예상 비용** | **~$10.59** | 실행당 |

### 6.2 비용 최적화 권장사항
1. **AWS Budgets 설정**: 예산 초과 알림 구성
2. **비용 할당 태그**: 리소스에 태그 추가하여 비용 추적
   ```
   Application: healthomics-eventbridge
   Environment: dev/prod
   ```
3. **HealthOmics Sequence Store 활용**: FASTQ 파일 저장 비용 절감

---

## 7. 제공된 테스트 데이터

### 7.1 샘플 매니페스트 파일

| 파일명 | 샘플 | 읽기 그룹 | 용도 |
|--------|------|-----------|------|
| `sample_manifest_NA12878.csv` | NA12878 | Sample_U0a | 데모 실행 1 |
| `sample_manifest_NA12878_2.csv` | NA12878 | Sample_U0b | 데모 실행 2 |
| `sample_manifest_with_test_data.csv` | NA12878 | Sample_U0a | 원본 테스트 |

### 7.2 데이터 소스
- **공개 테스트 데이터**: `s3://aws-genomics-static-{region}/omics-tutorials/data/fastq/`
- **VEP 캐시**: `s3://aws-genomics-static-{region}/omics-tutorials/data/databases/vep/`
- **참조 데이터**: Broad References, GIAB (Genome in a Bottle)

---

## 8. 파이프라인 흐름 상세

### 8.1 단계별 설명

1. **CSV 업로드**
   - S3 입력 버킷의 `fastqs/` 프리픽스에 매니페스트 파일 업로드
   - S3 이벤트가 Lambda 함수 트리거

2. **GATK-BP 워크플로우 실행**
   - `initial_workflow_lambda`가 Ready2Run 워크플로우 시작
   - FASTQ 파일을 BAM 및 VCF로 처리
   - 예상 실행 시간: 수 시간 (데이터 크기에 따라 다름)

3. **EventBridge 이벤트**
   - 워크플로우 완료 시 `Run Status Change` 이벤트 발생
   - 상태: `COMPLETED` → VEP Lambda 트리거
   - 상태: `FAILED` → SNS 알림 전송

4. **VEP 워크플로우 실행**
   - `post_initial_workflow_lambda`가 VEP 워크플로우 시작
   - GATK-BP 출력 VCF를 입력으로 사용
   - 변이에 대한 기능적 주석 추가

5. **결과 출력**
   - 최종 결과는 S3 출력 버킷에 저장
   - 디렉토리 구조: `s3://<OUTPUT_BUCKET>/outputs/<RUN_ID>/`

---

## 9. 트러블슈팅

### 9.1 일반적인 문제

| 문제 | 원인 | 해결 방법 |
|------|------|-----------|
| 워크플로우 시작 실패 | IAM 권한 부족 | `omics_role` 정책 확인 |
| S3 접근 오류 | 버킷 정책 또는 ARN 오류 | S3 정책 및 IAM 정책 확인 |
| Lambda 타임아웃 | 실행 시간 초과 | 타임아웃 값 증가 (현재 60초) |
| VEP 캐시 오류 | 잘못된 캐시 경로 | 리전별 S3 경로 확인 |

### 9.2 로그 확인

```bash
# Lambda 로그 확인
aws logs tail /aws/lambda/<LAMBDA_NAME> --follow

# HealthOmics 실행 로그 확인
aws omics get-run --id <RUN_ID>
```

---

## 10. 개선 완료 항목 요약

| 항목 | 상태 | 파일 |
|------|------|------|
| S3 ARN 콤마 버그 수정 | 완료 | `stack/compute.py` |
| Python 3.12 업그레이드 | 완료 | `stack/compute.py` |
| 미사용 상수 제거 | 완료 | `constants.py` |
| VEP README 작성 | 완료 | `workflows/vep/README.md` |
| 테스트 매니페스트 추가 | 완료 | `workflows/vep/test_data/` |
| 한국어 보고서 | 완료 | `REPORT_KO.md` |

---

## 11. 제외된 항목 (사용자 요청에 따라)

다음 항목은 이번 개선 범위에서 제외되었습니다:
- cdk_nag 보안 스캐닝
- KMS 정책 범위 지정
- S3 버킷 버전 관리/암호화 강화
- CloudWatch 알람
- Dead Letter Queue (DLQ)
- X-Ray 추적

---

## 12. 참고 자료

- [AWS HealthOmics 문서](https://docs.aws.amazon.com/omics/)
- [Amazon EventBridge 문서](https://docs.aws.amazon.com/eventbridge/)
- [AWS CDK 문서](https://docs.aws.amazon.com/cdk/)
- [Ensembl VEP 문서](https://www.ensembl.org/info/docs/tools/vep/index.html)
- [GATK Best Practices](https://gatk.broadinstitute.org/hc/en-us/sections/360007226651-Best-Practices-Workflows)

---

*보고서 작성일: 2025년 1월*
