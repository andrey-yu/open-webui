# Open WebUI Cloud Run Dev Deployment Guide (Build from Source using Cloud Build)

This guide explains how to deploy Open WebUI to Google Cloud Run using a custom image built from source using Google Cloud Build, specifically for development environments.

## 🚀 Quick Start

1. **Clone the repository** (if you haven't already)
2. **Configure environment variables**
3. **Deploy to Cloud Run Dev**
4. **Access your application**

## 📋 Prerequisites

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed and configured
- A [Supabase](https://supabase.com/) project with PostgreSQL database
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A Google Cloud project with billing enabled
- Artifact Registry API enabled (automatically enabled by the deployment script)
- Cloud Build API enabled (automatically enabled by the deployment script)

## 🔧 Configuration

### Cloud Build Configuration

The development deployment uses a `cloudbuild.yaml` file to configure the Docker build process. This file:
- Defines the build steps for creating the Docker image
- Sets build arguments for customization
- Handles platform-specific builds (linux/amd64)
- Automatically pushes the image to Artifact Registry

### Dev vs Production Deployment

This deployment approach differs from the production deployment in several key ways:

| Aspect | Production (`deploy-cloud-run.sh`) | Dev (`deploy-cloud-run-dev.sh`) |
|--------|-----------------------------------|----------------------------------|
| **Image Source** | GitHub Container Registry (pre-built) | Built from source locally |
| **Service Name** | `open-webui` | `open-webui-dev` |
| **Repository** | Remote repository pointing to ghcr.io | Local Artifact Registry repository |
| **Build Process** | No local build required | Cloud Build from source |
| **Use Case** | Production deployments | Development/testing deployments |
| **Update Frequency** | Uses stable releases | Can deploy any local changes |

### Step 1: Set up your environment variables

```bash
# Copy the example environment file
cp env.cloud-run.example .env

# Edit the .env file with your actual values
nano .env
```

### Step 2: Configure required variables

#### Database Configuration (Supabase)

Get your Supabase database URL from your Supabase dashboard:
- Go to **Settings** → **Database**
- Copy the **Connection string** (URI format)

```bash
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

#### OpenAI API Configuration

```bash
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_API_BASE_URL=https://api.openai.com/v1
```

#### Security Configuration

Generate a secure secret key:

```bash
# Generate a secure random key
openssl rand -hex 32
```

Add it to your `.env` file:

```bash
WEBUI_SECRET_KEY=your-generated-secret-key-here
```

#### Application URL

After deployment, update your `.env` file with the actual Cloud Run URL:

```bash
WEBUI_URL=https://open-webui-dev-xyz-uc.a.run.app
```

## 🚀 Deployment

### Using the dev deployment script

```bash
# Make the script executable
chmod +x deploy-cloud-run-dev.sh

# Set your Google Cloud project ID
export PROJECT_ID="your-gcp-project-id"

# Deploy (builds from source and deploys)
./deploy-cloud-run-dev.sh
```

### Build image only (without deploying)

```bash
# Build and push the Docker image only
./deploy-cloud-run-dev.sh build
```

### Manual deployment

```bash
# Set your project ID
gcloud config set project your-gcp-project-id

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com

# Create Artifact Registry repository
gcloud artifacts repositories create open-webui-dev \
    --repository-format=docker \
    --location=us-central1 \
    --description="Open WebUI Dev Repository"

# Build and push the image using Cloud Build
gcloud builds submit \
    --config cloudbuild.yaml \
    --substitutions=_BUILD_HASH=dev-$(date +%Y%m%d-%H%M%S),_IMAGE_NAME=us-central1-docker.pkg.dev/your-gcp-project-id/open-webui-dev/open-webui:dev \
    .

# Deploy to Cloud Run
gcloud run deploy open-webui-dev \
  --image us-central1-docker.pkg.dev/your-gcp-project-id/open-webui-dev/open-webui:dev \
  --platform managed \
  --region us-central1 \
  --port 8080 \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 2 \
  --max-instances 10 \
  --min-instances 0 \
  --timeout 300 \
  --concurrency 80 \
  --set-env-vars-from-file .env
```

## 🔍 Verification

After deployment, you can:

1. **Check deployment status**:
   ```bash
   ./deploy-cloud-run-dev.sh status
   ```

2. **Get the service URL**:
   ```bash
   ./deploy-cloud-run-dev.sh url
   ```

3. **View logs**:
   ```bash
   gcloud logs tail --service=open-webui-dev --region=us-central1
   ```

## 🌐 Access Your Application

1. Visit the Cloud Run URL provided after deployment
2. Register your first admin account
3. Start chatting with OpenAI models!

## ⚙️ Configuration Options

### Resource Limits

The dev deployment uses these resource limits:
- **Memory**: 4GB (increased from production for development)
- **CPU**: 2 vCPU (increased from production for development)
- **Max Instances**: 10
- **Concurrency**: 80 requests per instance

You can adjust these in the deployment command or script.

### Environment Variables Reference

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DATABASE_URL` | ✅ | Supabase PostgreSQL connection string | - |
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key | - |
| `WEBUI_SECRET_KEY` | ✅ | Secret key for JWT tokens | - |
| `WEBUI_URL` | ❌ | Your application URL | - |
| `ENABLE_SIGNUP` | ❌ | Enable user registration | `true` |
| `REDIS_URL` | ❌ | Redis for session storage | - |
| `WHISPER_MODEL` | ❌ | Speech-to-text model | `base` |
| `RAG_EMBEDDING_MODEL` | ❌ | RAG embedding model | `all-MiniLM-L6-v2` |

## 🔧 Advanced Configuration

### Custom Build Arguments

You can customize the Cloud Build by modifying the `cloudbuild.yaml` file:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '--platform'
      - 'linux/amd64'
      - '--build-arg'
      - 'BUILD_HASH=${_BUILD_HASH}'
      - '--build-arg'
      - 'USE_CUDA=false'
      - '--build-arg'
      - 'USE_OLLAMA=false'
      - '--build-arg'
      - 'USE_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2'
      - '-t'
      - '${_IMAGE_NAME}'
      - '.'
```

### Using Different Dockerfile

If you have a custom Dockerfile for development, modify the `cloudbuild.yaml` file:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '--platform'
      - 'linux/amd64'
      - '--build-arg'
      - 'BUILD_HASH=${_BUILD_HASH}'
      - '-f'
      - 'Dockerfile.dev'
      - '-t'
      - '${_IMAGE_NAME}'
      - '.'
```

## 🛠️ Troubleshooting

### Common Issues

1. **Cloud Build Failures**
   - Ensure you have sufficient quota for Cloud Build
   - Check that all required files are present in the repository
   - Verify Cloud Build API is enabled

2. **Artifact Registry Issues**
   - Ensure Artifact Registry API is enabled
   - Check that you have proper permissions to create repositories
   - Verify Docker authentication is configured correctly

3. **Cloud Run Deployment Failures**
   - Check the deployment logs: `gcloud logs tail --service=open-webui-dev`
   - Verify all required environment variables are set
   - Ensure your Google Cloud project has billing enabled

4. **Image Push Failures**
   - Check Cloud Build permissions: `gcloud projects describe your-project-id --format="value(projectNumber)"`
   - Verify repository exists: `gcloud artifacts repositories describe open-webui-dev --location=us-central1`
   - Check Cloud Build logs: `gcloud builds list --limit=5`

### Useful Commands

```bash
# View service details
gcloud run services describe open-webui-dev --region=us-central1

# View recent logs
gcloud logs tail --service=open-webui-dev --region=us-central1

# Update environment variables
gcloud run services update open-webui-dev --region=us-central1 --set-env-vars-from-file .env

# Scale the service
gcloud run services update open-webui-dev --region=us-central1 --max-instances=5

# List images in repository
gcloud artifacts docker images list us-central1-docker.pkg.dev/your-project-id/open-webui-dev
```

## 🔒 Security Considerations

1. **Environment Variables**: Never commit your `.env` file to version control
2. **API Keys**: Use Google Secret Manager for sensitive data in production
3. **Database**: Ensure your Supabase database has proper access controls
4. **HTTPS**: Cloud Run automatically provides HTTPS
5. **Authentication**: Consider implementing additional authentication layers

## 📊 Monitoring

### Cloud Run Metrics

Monitor your application using Google Cloud Console:
- **CPU and Memory usage**
- **Request count and latency**
- **Error rates**
- **Instance count**

### Application Logs

```bash
# View application logs
gcloud logs tail --service=open-webui-dev --region=us-central1

# Filter logs by severity
gcloud logs tail --service=open-webui-dev --region=us-central1 --min-log-level=ERROR
```

## 🔄 Updates and Maintenance

### Updating the Application

```bash
# Redeploy with latest source changes
./deploy-cloud-run-dev.sh

# Or manually rebuild and deploy
./deploy-cloud-run-dev.sh build
gcloud run services update open-webui-dev --region=us-central1 --image=us-central1-docker.pkg.dev/your-project-id/open-webui-dev/open-webui:dev
```

### Database Migrations

Open WebUI automatically handles database migrations on startup. No manual intervention is required.

### Cleanup

To clean up old images:

```bash
# List images
gcloud artifacts docker images list us-central1-docker.pkg.dev/your-project-id/open-webui-dev

# Delete old images
gcloud artifacts docker images delete us-central1-docker.pkg.dev/your-project-id/open-webui-dev/open-webui:dev
```

## 📞 Support

- **Open WebUI Documentation**: https://docs.openwebui.com/
- **Google Cloud Run Documentation**: https://cloud.google.com/run/docs
- **Supabase Documentation**: https://supabase.com/docs

## 🎉 Congratulations!

You've successfully deployed Open WebUI to Google Cloud Run with a custom image built from source. This setup is perfect for development and testing environments where you need to deploy local changes quickly! 