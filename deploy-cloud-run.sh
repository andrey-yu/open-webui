#!/bin/bash

# =============================================================================
# Open WebUI Cloud Run Deployment Script
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

export PROJECT_ID="owui-467900"

export STABLE_VERSION="v0.6.18"
#export STABLE_VERSION="main"

# Configuration
PROJECT_ID=${PROJECT_ID:-"your-gcp-project-id"}
SERVICE_NAME=${SERVICE_NAME:-"open-webui"}
REGION=${REGION:-"us-central1"}
ORIGINAL_IMAGE_NAME="ghcr.io/open-webui/open-webui:$STABLE_VERSION"
REMOTE_REPO_NAME="open-webui-remote"
REMOTE_REPO_LOCATION="us-central1"
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
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install it first."
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

# Function to check if .env file exists
check_env_file() {
    if [ ! -f ".env" ]; then
        print_error ".env file not found!"
        print_status "Please copy env.cloud-run.example to .env and configure your values:"
        echo "cp env.cloud-run.example .env"
        echo "nano .env  # or your preferred editor"
        exit 1
    fi
    
    # Check for required environment variables
    source .env
    
    if [ -z "$DATABASE_URL" ]; then
        print_error "DATABASE_URL is not set in .env file"
        exit 1
    fi
    
    if [ -z "$OPENAI_API_KEY" ]; then
        print_error "OPENAI_API_KEY is not set in .env file"
        exit 1
    fi
    
    if [ -z "$WEBUI_SECRET_KEY" ]; then
        print_error "WEBUI_SECRET_KEY is not set in .env file"
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

# Function to setup remote repository for GitHub Container Registry
setup_remote_repository() {
    print_status "Setting up remote repository for GitHub Container Registry..."
    
    # Check if remote repository already exists
    if gcloud artifacts repositories describe $REMOTE_REPO_NAME --location=$REMOTE_REPO_LOCATION &>/dev/null; then
        print_status "Remote repository '$REMOTE_REPO_NAME' already exists"
    else
        print_status "Creating remote repository '$REMOTE_REPO_NAME'..."
        gcloud artifacts repositories create $REMOTE_REPO_NAME \
            --repository-format=docker \
            --location=$REMOTE_REPO_LOCATION \
            --mode=remote-repository \
            --remote-docker-repo=https://ghcr.io \
            --description="Remote repository for Open WebUI from GitHub Container Registry"
        
        print_success "Remote repository created successfully"
    fi
    
    # Set the image name to use the remote repository
    # For remote repositories, we need to use the full image path from the upstream registry
    IMAGE_NAME="$REMOTE_REPO_LOCATION-docker.pkg.dev/$PROJECT_ID/$REMOTE_REPO_NAME/open-webui/open-webui:$STABLE_VERSION"
    
    print_status "Using image: $IMAGE_NAME"
}

# Function to deploy to Cloud Run
deploy_to_cloud_run() {
    print_status "Deploying to Cloud Run..."

    ./gcloud-create-env-yaml.sh
    
    # Update CORS_ALLOW_ORIGIN with the actual service URL for better security
    # Get the expected service URL
    EXPECTED_SERVICE_URL="https://$SERVICE_NAME-$REGION-$PROJECT_ID.a.run.app"
    
    # Update the gcloud-env.yaml file to use the correct CORS origin
    if [ -f "gcloud-env.yaml" ]; then
        # Replace CORS_ALLOW_ORIGIN with the actual service URL
        sed -i.bak "s|CORS_ALLOW_ORIGIN: \".*\"|CORS_ALLOW_ORIGIN: \"$EXPECTED_SERVICE_URL\"|g" gcloud-env.yaml
        rm -f gcloud-env.yaml.bak
        print_status "Updated CORS_ALLOW_ORIGIN to: $EXPECTED_SERVICE_URL"
    fi
    
    # Build and deploy using gcloud run deploy
    gcloud run deploy $SERVICE_NAME \
        --image $IMAGE_NAME \
        --platform managed \
        --region $REGION \
        --port 8080 \
        --allow-unauthenticated \
        --memory 4Gi \
        --cpu 2 \
        --max-instances 10 \
        --min-instances 0 \
        --timeout 300 \
        --concurrency 80 \
        --env-vars-file gcloud-env.yaml \
    
    print_success "Deployment completed!"
}

# Function to get the service URL
get_service_url() {
    print_status "Getting service URL..."
    
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.url)")
    
    if [ -n "$SERVICE_URL" ]; then
        print_success "Your Open WebUI is now available at:"
        echo -e "${GREEN}$SERVICE_URL${NC}"
        echo ""
        print_status "You can now:"
        echo "1. Visit the URL to access Open WebUI"
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
    echo "Open WebUI Cloud Run Deployment"
    echo "=============================================================================="
    echo ""
    
    check_prerequisites
    check_env_file
    authenticate_gcloud
    setup_remote_repository
    deploy_to_cloud_run
    get_service_url
    show_status
    
    echo ""
    echo "=============================================================================="
    print_success "Deployment completed successfully!"
    echo "=============================================================================="
}

# Handle command line arguments
case "${1:-deploy}" in
    "deploy")
        main
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
        echo "  deploy  - Deploy Open WebUI to Cloud Run (default)"
        echo "  status  - Show deployment status"
        echo "  url     - Get the service URL"
        echo "  help    - Show this help message"
        echo ""
        echo "Environment variables:"
        echo "  PROJECT_ID   - Google Cloud Project ID (default: your-gcp-project-id)"
        echo "  SERVICE_NAME - Cloud Run service name (default: open-webui)"
        echo "  REGION       - Google Cloud region (default: us-central1)"
        ;;
    *)
        print_error "Unknown command: $1"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac 