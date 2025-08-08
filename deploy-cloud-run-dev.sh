#!/bin/bash

# =============================================================================
# Open WebUI Cloud Run Dev Deployment Script (Build from Source using Cloud Build)
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

export PROJECT_ID="owui-467900"

# Configuration
PROJECT_ID=${PROJECT_ID:-"your-gcp-project-id"}
SERVICE_NAME=${SERVICE_NAME:-"open-webui-dev"}
REGION=${REGION:-"us-central1"}
REPO_NAME="open-webui-dev"
IMAGE_NAME=""

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if required tools are installed
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI is not installed. Please install it first."
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

# Function to check if .env.dev file exists
check_env_file() {
    if [ ! -f ".env.dev" ]; then
        print_error ".env.dev file not found!"
        print_status "Please copy env.cloud-run.example to .env.dev and configure your values:"
        echo "cp env.cloud-run.example .env.dev"
        echo "nano .env.dev  # or your preferred editor"
        exit 1
    fi
    
    # Check for required environment variables
    source .env.dev
    
    if [ -z "$DATABASE_URL" ]; then
        print_error "DATABASE_URL is not set in .env.dev file"
        exit 1
    fi
    
    if [ -z "$OPENAI_API_KEY" ]; then
        print_error "OPENAI_API_KEY is not set in .env.dev file"
        exit 1
    fi
    
    if [ -z "$WEBUI_SECRET_KEY" ]; then
        print_error "WEBUI_SECRET_KEY is not set in .env.dev file"
        exit 1
    fi
    
    print_success "Environment file validation passed"
}

# Function to authenticate with Google Cloud
authenticate_gcloud() {
    print_status "Authenticating with Google Cloud..."
    
    # Check if already authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        print_warning "Not authenticated with Google Cloud. Please authenticate:"
        gcloud auth login
    fi
    
    # Set the project
    gcloud config set project $PROJECT_ID
    
    # Enable required APIs
    print_status "Enabling required APIs..."
    gcloud services enable run.googleapis.com
    gcloud services enable cloudbuild.googleapis.com
    gcloud services enable artifactregistry.googleapis.com
    
    print_success "Google Cloud authentication completed"
}

# Function to setup Artifact Registry repository
setup_artifact_registry() {
    print_status "Setting up Artifact Registry repository..."
    
    # Check if repository already exists
    if gcloud artifacts repositories describe $REPO_NAME --location=$REGION &>/dev/null; then
        print_status "Repository '$REPO_NAME' already exists"
    else
        print_status "Creating repository '$REPO_NAME'..."
        gcloud artifacts repositories create $REPO_NAME \
            --repository-format=docker \
            --location=$REGION \
            --description="Open WebUI Dev Repository"
        
        print_success "Repository created successfully"
    fi
    
    # Configure Docker to authenticate to Artifact Registry
    print_status "Configuring Docker authentication..."
    gcloud auth configure-docker $REGION-docker.pkg.dev
    
    # Set the image name
    IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/open-webui:dev"
    
    print_status "Using image: $IMAGE_NAME"
}

# Function to build and push Docker image using Google Cloud Build
build_and_push_image() {
    print_status "Building Docker image from source using Google Cloud Build..."
    
    # Generate build timestamp
    BUILD_TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    
    # Build the image using Google Cloud Build with configuration file and live logging
    gcloud beta builds submit \
        --config cloudbuild.yaml \
        --substitutions=_BUILD_HASH=dev-$BUILD_TIMESTAMP,_IMAGE_NAME=$IMAGE_NAME \
        .
    
    print_success "Docker image built and pushed successfully using Google Cloud Build"
}

# Function to deploy to Cloud Run
deploy_to_cloud_run() {
    print_status "Deploying to Cloud Run..."

    export ENV_FILE=".env.dev"
    ./gcloud-create-env-yaml.sh

    # if image name is not set, set it to the default
    if [ -z "$IMAGE_NAME" ]; then
        IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/open-webui:dev"
    fi
    
    # Update CORS_ALLOW_ORIGIN with the actual service URL for better security
    # Get the expected service URL
    #EXPECTED_SERVICE_URL="https://$SERVICE_NAME-$REGION-$PROJECT_ID.a.run.app"
    
    # Update the gcloud-env.yaml file to use the correct CORS origin
    #if [ -f "gcloud-env.yaml" ]; then
        # Replace CORS_ALLOW_ORIGIN with the actual service URL
        #sed -i.bak "s|CORS_ALLOW_ORIGIN: \".*\"|CORS_ALLOW_ORIGIN: \"$EXPECTED_SERVICE_URL\"|g" gcloud-env.yaml
        #rm -f gcloud-env.yaml.bak
        #print_status "Updated CORS_ALLOW_ORIGIN to: $EXPECTED_SERVICE_URL"
    #fi
    
    # Build and deploy using gcloud run deploy
    gcloud run deploy $SERVICE_NAME \
        --image $IMAGE_NAME \
        --platform managed \
        --region $REGION \
        --port 8080 \
        --allow-unauthenticated \
        --memory 8Gi \
        --cpu 4 \
        --max-instances 15 \
        --min-instances 0 \
        --timeout 1800 \
        --concurrency 30 \
        --env-vars-file gcloud-env.yaml \
    
    print_success "Deployment completed!"
}

# Function to get the service URL
get_service_url() {
    print_status "Getting service URL..."
    
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.url)")
    
    if [ -n "$SERVICE_URL" ]; then
        print_success "Your Open WebUI Dev is now available at:"
        echo -e "${GREEN}$SERVICE_URL${NC}"
        echo ""
        print_status "You can now:"
        echo "1. Visit the URL to access Open WebUI Dev"
        echo "2. Register your first admin account"
        echo "3. Start chatting with OpenAI models"
    else
        print_error "Failed to get service URL"
        exit 1
    fi
}

# Function to show deployment status
show_status() {
    print_status "Checking deployment status..."
    
    gcloud run services describe $SERVICE_NAME --region=$REGION --format="table(status.conditions[0].type,status.conditions[0].status,status.conditions[0].message)"
}

# Main deployment flow
main() {
    echo "=============================================================================="
    echo "Open WebUI Cloud Run Dev Deployment (Build from Source)"
    echo "=============================================================================="
    echo ""
    
    check_prerequisites
    check_env_file
    authenticate_gcloud
    setup_artifact_registry
    build_and_push_image
    deploy_to_cloud_run
    get_service_url
    show_status
    
    echo ""
    echo "=============================================================================="
    print_success "Dev deployment completed successfully!"
    echo "=============================================================================="
}

# Handle command line arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "deploy-only")
        deploy_to_cloud_run
        ;;
    "build")
        check_prerequisites
        authenticate_gcloud
        setup_artifact_registry
        build_and_push_image
        ;;
    "status")
        show_status
        ;;
    "url")
        get_service_url
        ;;
    "help"|"-h"|"--help")
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  deploy  - Deploy Open WebUI Dev to Cloud Run (default)"
        echo "  deploy-only  - Deploy Open WebUI Dev to Cloud Run (without building)"
        echo "  build   - Build and push Docker image only"
        echo "  status  - Show deployment status"
        echo "  url     - Get the service URL"
        echo "  help    - Show this help message"
        echo ""
        echo "Environment variables:"
        echo "  PROJECT_ID   - Google Cloud Project ID (default: your-gcp-project-id)"
        echo "  SERVICE_NAME - Cloud Run service name (default: open-webui-dev)"
        echo "  REGION       - Google Cloud region (default: us-central1)"
        echo ""
        echo "This script builds the Docker image from source using Google Cloud Build and deploys to a -dev service."
        ;;
    *)
        print_error "Unknown command: $1"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac 