#!/usr/bin/env bash
# 뼈대 리소스를 처음 한 번 만든다. 이미 있으면 건너뛴다 (지우거나 바꾸지 않는다).
# 실행: MODEL_ID=<global 추론 프로필 ID> bash infra/create.sh
# 만드는 것: IAM 역할 team06-agent-role, DynamoDB team06-jobs, S3 team06-docs-<계정>,
#           로그 그룹(보존 7일), Lambda team06-agent, 동시 실행 상한 5, 공개 Function URL
source "$(dirname "$0")/config.sh"

: "${MODEL_ID:?MODEL_ID 환경 변수가 필요합니다}"
case "${MODEL_ID}" in global.anthropic.*) ;; *)
  echo "MODEL_ID는 global.anthropic. 로 시작해야 합니다 (policy-bedrock.json 범위)"; exit 1;;
esac

echo "[create] 계정 ${ACCOUNT_ID}, 리전 ${AWS_REGION}"

# 1. IAM 역할 (Lambda 실행 역할, 필요한 권한만)
if aws iam get-role --role-name "${ROLE}" >/dev/null 2>&1; then
  echo "[create] 역할 ${ROLE} 있음"
else
  aws iam create-role --role-name "${ROLE}" \
    --assume-role-policy-document "file://${ROOT}/infra/trust-lambda.json" >/dev/null
  echo "[create] 역할 ${ROLE} 만듦"
fi
for name in bedrock logs data; do
  aws iam put-role-policy --role-name "${ROLE}" --policy-name "team06-${name}" \
    --policy-document "file://$(render_policy "policy-${name}.json")"
done
ROLE_ARN=$(aws iam get-role --role-name "${ROLE}" --query Role.Arn --output text)

# 2. DynamoDB 작업 테이블 (온디맨드)
if aws dynamodb describe-table --table-name "${TABLE}" >/dev/null 2>&1; then
  echo "[create] 테이블 ${TABLE} 있음"
else
  aws dynamodb create-table --table-name "${TABLE}" \
    --attribute-definitions AttributeName=job_id,AttributeType=S \
    --key-schema AttributeName=job_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  aws dynamodb wait table-exists --table-name "${TABLE}"
  echo "[create] 테이블 ${TABLE} 만듦"
fi

# 3. S3 서류 버킷 (공개 차단)
if aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  echo "[create] 버킷 ${BUCKET} 있음"
else
  aws s3api create-bucket --bucket "${BUCKET}" \
    --create-bucket-configuration LocationConstraint=ap-northeast-2 >/dev/null
  echo "[create] 버킷 ${BUCKET} 만듦"
fi
aws s3api put-public-access-block --bucket "${BUCKET}" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# 4. 로그 그룹 (보존 7일)
aws logs create-log-group --log-group-name "${LOG_GROUP}" 2>/dev/null || true
aws logs put-retention-policy --log-group-name "${LOG_GROUP}" --retention-in-days 7

# 5. Lambda 함수
package_and_upload
if aws lambda get-function --function-name "${FUNCTION}" >/dev/null 2>&1; then
  echo "[create] 함수 ${FUNCTION} 있음. 코드 갱신은 deploy.sh"
else
  # 새 역할은 몇 초 뒤에 쓸 수 있어 몇 번 다시 시도한다
  for attempt in 1 2 3 4 5 6; do
    if aws lambda create-function --function-name "${FUNCTION}" \
      --runtime python3.13 --architectures x86_64 --memory-size 1024 --timeout 300 \
      --handler api.handler.lambda_handler --role "${ROLE_ARN}" \
      --code "S3Bucket=${BUCKET},S3Key=${CODE_KEY}" \
      --environment "Variables={MODEL_ID=${MODEL_ID},JOBS_TABLE=${TABLE},DOCS_BUCKET=${BUCKET}}" \
      >/dev/null 2>"${BUILD}/create-function.err"; then
      echo "[create] 함수 ${FUNCTION} 만듦"; break
    fi
    if grep -q "cannot be assumed" "${BUILD}/create-function.err" && [ "${attempt}" -lt 6 ]; then
      echo "[create] 역할 전파 대기 (${attempt}/6)"; sleep 10
    else
      cat "${BUILD}/create-function.err"; exit 1
    fi
  done
  aws lambda wait function-active-v2 --function-name "${FUNCTION}"
fi

# 6. 동시 실행 상한 5 (공개 URL 비용 상한)
aws lambda put-function-concurrency --function-name "${FUNCTION}" --reserved-concurrent-executions 5 >/dev/null

# 7. 공개 Function URL (인증 없음, 함수 URL로만 호출 가능)
if ! aws lambda get-function-url-config --function-name "${FUNCTION}" >/dev/null 2>&1; then
  aws lambda create-function-url-config --function-name "${FUNCTION}" --auth-type NONE \
    --cors 'AllowOrigins=*,AllowMethods=GET,POST,AllowHeaders=content-type' >/dev/null
  aws lambda add-permission --function-name "${FUNCTION}" --statement-id FunctionURLAllowPublicAccess \
    --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE >/dev/null
  aws lambda add-permission --function-name "${FUNCTION}" --statement-id FunctionURLInvokeAllowPublicAccess \
    --action lambda:InvokeFunction --principal '*' --invoked-via-function-url >/dev/null
  echo "[create] Function URL 만듦"
fi
URL=$(aws lambda get-function-url-config --function-name "${FUNCTION}" --query FunctionUrl --output text)
echo "[create] 끝. 확인: curl ${URL}"
