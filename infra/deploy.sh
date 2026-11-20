#!/usr/bin/env bash
# 코드만 다시 배포한다 (리소스 설정은 바꾸지 않는다). main을 최신으로 받은 뒤 실행.
# 실행: bash infra/deploy.sh
source "$(dirname "$0")/config.sh"

package_and_upload
aws lambda update-function-code --function-name "${FUNCTION}" \
  --s3-bucket "${BUCKET}" --s3-key "${CODE_KEY}" >/dev/null
aws lambda wait function-updated-v2 --function-name "${FUNCTION}"
URL=$(aws lambda get-function-url-config --function-name "${FUNCTION}" --query FunctionUrl --output text)
echo "[deploy] 끝. 확인: curl ${URL}"
