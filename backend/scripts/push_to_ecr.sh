#!/usr/bin/env bash
# ==============================================================================
# Push Backend Docker Image to Amazon ECR (AWS Learner Lab / Standard Account)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${BACKEND_DIR}/.." && pwd)"

# 1. Load environment variables from .env if available
if [[ -f "${BACKEND_DIR}/.env" ]]; then
    echo "📄 Loading credentials from ${BACKEND_DIR}/.env..."
    set -a
    # Load only non-empty, non-comment lines
    eval "$(grep -v '^[[:space:]]*#' "${BACKEND_DIR}/.env" | grep -v '^[[:space:]]*$' | sed -e 's/\r$//')"
    set +a
elif [[ -f "${REPO_ROOT}/.env" ]]; then
    echo "📄 Loading credentials from ${REPO_ROOT}/.env..."
    set -a
    eval "$(grep -v '^[[:space:]]*#' "${REPO_ROOT}/.env" | grep -v '^[[:space:]]*$' | sed -e 's/\r$//')"
    set +a
fi

# Ensure AWS Region is set (Learner Lab is strictly us-east-1)
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_REGION}"

# 2. Check AWS CLI and Docker availability
if ! command -v aws &> /dev/null; then
    echo "❌ Error: 'aws' CLI is not installed. Please install it first."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Error: 'docker' is not installed or running."
    exit 1
fi

echo "🔍 Validating AWS Learner Lab credentials..."
if ! CALLER_IDENTITY=$(aws sts get-caller-identity 2>&1); then
    echo "❌ Error validating AWS credentials:"
    echo "${CALLER_IDENTITY}"
    echo ""
    echo "⚠️  If using AWS Learner Lab:"
    echo "    1. Go to AWS Academy Learner Lab and click 'Start Lab'"
    echo "    2. Click 'AWS Details' and copy AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN"
    echo "    3. Paste them into backend/.env and re-run this script"
    exit 1
fi

# 3. Retrieve AWS Account ID dynamically
AWS_ACCOUNT_ID=$(echo "${CALLER_IDENTITY}" | grep -o '"Account": "[^"]*' | cut -d'"' -f4)
if [[ -z "${AWS_ACCOUNT_ID}" ]]; then
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
fi

echo "✅ Authenticated as Account: ${AWS_ACCOUNT_ID} in ${AWS_REGION}"

# 4. Configuration
REPO_NAME="gns3-backend"
IMAGE_TAG="${1:-latest}"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${REPO_NAME}:${IMAGE_TAG}"

# 5. Ensure ECR repository exists
echo "📦 Checking ECR repository '${REPO_NAME}'..."
if ! aws ecr describe-repositories --repository-names "${REPO_NAME}" --region "${AWS_REGION}" &> /dev/null; then
    echo "➕ Repository '${REPO_NAME}' not found. Creating repository in ECR..."
    aws ecr create-repository \
        --repository-name "${REPO_NAME}" \
        --image-scanning-configuration scanOnPush=true \
        --region "${AWS_REGION}" > /dev/null
    echo "✅ ECR repository '${REPO_NAME}' created."
else
    echo "✅ ECR repository '${REPO_NAME}' already exists."
fi

# 6. Authenticate Docker with Amazon ECR
echo "🔑 Logging in Docker to Amazon ECR (${REGISTRY})..."
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${REGISTRY}"

# 7. Build Docker image
echo "🔨 Building Docker image (${IMAGE_TAG}) for linux/amd64 (ECS compatible)..."
docker build \
    --platform linux/amd64 \
    -t "${REPO_NAME}:${IMAGE_TAG}" \
    "${BACKEND_DIR}"

# 8. Tag image for ECR
echo "🏷️  Tagging image as ${IMAGE_URI}..."
docker tag "${REPO_NAME}:${IMAGE_TAG}" "${IMAGE_URI}"

# 9. Push image to ECR
echo "🚀 Pushing image to Amazon ECR..."
docker push "${IMAGE_URI}"

echo "=============================================================================="
echo "🎉 Image pushed successfully!"
echo "📍 ECR Image URI: ${IMAGE_URI}"
echo "=============================================================================="
echo "Use this Image URI in your AWS ECS Task Definition Container configuration."

