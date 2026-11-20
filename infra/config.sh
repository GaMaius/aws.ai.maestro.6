#!/usr/bin/env bash
# 공통 설정. create.sh, deploy.sh가 source 한다. 서울 리전, team06- 이름만 쓴다.
set -euo pipefail

export AWS_REGION=ap-northeast-2
export AWS_DEFAULT_REGION=ap-northeast-2

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
FUNCTION=team06-agent
ROLE=team06-agent-role
TABLE=team06-jobs
BUCKET="team06-docs-${ACCOUNT_ID}"
LOG_GROUP="/aws/lambda/${FUNCTION}"
CODE_KEY="deploy/${FUNCTION}.zip"

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BUILD="${ROOT}/build"

# 정책 JSON의 __ACCOUNT_ID__, __BUCKET__ 자리를 채워 build/ 에 쓴다
render_policy() {
  mkdir -p "${BUILD}/policies"
  sed -e "s/__ACCOUNT_ID__/${ACCOUNT_ID}/g" -e "s/__BUCKET__/${BUCKET}/g" \
    "${ROOT}/infra/$1" > "${BUILD}/policies/$1"
  echo "${BUILD}/policies/$1"
}

# 코드와 의존성을 Lambda(x86_64, Python 3.13)용 zip으로 묶어 S3에 올린다
package_and_upload() {
  # manylinux_2_28은 2014 휠도 받는다. pillow 13 이후 2014 휠이 없어 2_28로 둔다 (Lambda AL2023 glibc 2.34)
  # zip이 50MB를 넘어 직접 업로드 대신 S3를 거친다
  echo "[deploy] 패키징 (manylinux_2_28 x86_64, Python 3.13)"
  rm -rf "${BUILD}/pkg" "${BUILD}/${FUNCTION}.zip"
  mkdir -p "${BUILD}/pkg"
  (cd "${ROOT}" && uv export --frozen --no-dev --no-hashes --no-emit-project -o "${BUILD}/requirements.txt" >/dev/null)
  uv pip install --quiet --target "${BUILD}/pkg" \
    --python-platform x86_64-manylinux_2_28 --python-version 3.13 --only-binary=:all: \
    -r "${BUILD}/requirements.txt"
  cp -R "${ROOT}/agent" "${ROOT}/tools" "${ROOT}/api" "${BUILD}/pkg/"
  find "${BUILD}/pkg" -name "__pycache__" -type d -prune -exec rm -rf {} +
  (cd "${BUILD}/pkg" && zip -qr "../${FUNCTION}.zip" .)
  echo "[deploy] zip 크기: $(du -h "${BUILD}/${FUNCTION}.zip" | cut -f1)"
  aws s3 cp --only-show-errors "${BUILD}/${FUNCTION}.zip" "s3://${BUCKET}/${CODE_KEY}"
}
