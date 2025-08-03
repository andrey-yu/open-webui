# Open WebUI Cloud Run Deployment Guide

This guide will help you deploy Open WebUI to Google Cloud Run with an external Supabase database and OpenAI API integration. The deployment automatically sets up a remote repository to access the Open WebUI image from GitHub Container Registry.

## 🚀 Quick Start

1. **Clone the repository** (if you haven't already)
2. **Configure environment variables**
3. **Deploy to Cloud Run**
4. **Access your application**

## 📋 Prerequisites

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed and configured
- [Docker](https://docs.docker.com/get-docker/) installed
- A [Supabase](https://supabase.com/) project with PostgreSQL database
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A Google Cloud project with billing enabled
- Artifact Registry API enabled (automatically enabled by the deployment script)

## 🔧 Configuration

### Remote Repository Setup

The deployment automatically creates a remote repository in Google Artifact Registry that points to the Open WebUI image on GitHub Container Registry (`ghcr.io`). This allows Cloud Run to pull the image without needing to rebuild or push it to Google's registry.

The remote repository:
- **Name**: `open-webui-remote`
- **Location**: `us-central1` (same as your Cloud Run service)
- **Source**: `ghcr.io/open-webui/open-webui:main`

This approach is the most efficient as it:
- Uses the official pre-built image
- No need to rebuild or push images
- Follows Google Cloud best practices
- Automatically handles image updates

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
WEBUI_URL=https://your-app-name-xyz-uc.a.run.app
```

## 🚀 Deployment

### Option 1: Using the deployment script (Recommended)

```bash
# Make the script executable
chmod +x deploy-cloud-run.sh

# Set your Google Cloud project ID
export PROJECT_ID="your-gcp-project-id"

# Deploy
./deploy-cloud-run.sh
```

### Option 2: Manual deployment

```bash
# Set your project ID
gcloud config set project your-gcp-project-id

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com

# Create remote repository for GitHub Container Registry
gcloud artifacts repositories create open-webui-remote \
    --repository-format=docker \
    --location=us-central1 \
    --mode=remote-repository \
    --remote-docker-repo=https://ghcr.io \
    --description="Remote repository for Open WebUI from GitHub Container Registry"

# Deploy to Cloud Run using the remote repository
gcloud run deploy open-webui \
  --image us-central1-docker.pkg.dev/your-gcp-project-id/open-webui-remote/open-webui/open-webui:main \
  --platform managed \
  --region us-central1 \
  --port 8080 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --max-instances 10 \
  --min-instances 0 \
  --timeout 300 \
  --concurrency 80 \
  --set-env-vars-from-file .env \
  --set-env-vars="ENABLE_OLLAMA_API=false" \
  --set-env-vars="UVICORN_WORKERS=1"
```

## 🔍 Verification

After deployment, you can:

1. **Check deployment status**:
   ```bash
   ./deploy-cloud-run.sh status
   ```

2. **Get the service URL**:
   ```bash
   ./deploy-cloud-run.sh url
   ```

3. **View logs**:
   ```bash
   gcloud logs tail --service=open-webui --region=us-central1
   ```

## 🌐 Access Your Application

1. Visit the Cloud Run URL provided after deployment
2. Register your first admin account
3. Start chatting with OpenAI models!

## ⚙️ Configuration Options

### Database Connection Pooling

For production deployments, consider adjusting the database connection pool settings:

```bash
DATABASE_POOL_SIZE=10
DATABASE_POOL_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=3600
```

### Resource Limits

The deployment uses these default resource limits:
- **Memory**: 2GB
- **CPU**: 1 vCPU
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

### Using Redis for Session Management

For better session management in production, consider adding Redis:

```bash
# Add Redis URL to your .env file
REDIS_URL=redis://your-redis-host:6379
```

### Image Generation

To enable image generation with DALL-E:

```bash
IMAGES_OPENAI_API_KEY=sk-your-openai-api-key-here
IMAGES_OPENAI_API_BASE_URL=https://api.openai.com/v1
```

### RAG (Retrieval Augmented Generation)

For RAG functionality with Supabase pgvector:

```bash
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_RERANKING_MODEL=ms-marco-MiniLM-L-12-v2
PGVECTOR_DB_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

## 🛠️ Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Verify your Supabase database URL
   - Check if your IP is allowed in Supabase
   - Ensure the database is active

2. **OpenAI API Errors**
   - Verify your API key is correct
   - Check your OpenAI account has sufficient credits
   - Ensure the API key has the necessary permissions

3. **Cloud Run Deployment Failures**
   - Check the deployment logs: `gcloud logs tail --service=open-webui`
   - Verify all required environment variables are set
   - Ensure your Google Cloud project has billing enabled

4. **Remote Repository Issues**
   - If you get errors about the remote repository, try recreating it:
     ```bash
     gcloud artifacts repositories delete open-webui-remote --location=us-central1
     ./deploy-cloud-run.sh
     ```
   - Ensure Artifact Registry API is enabled: `gcloud services enable artifactregistry.googleapis.com`
   - Verify the image format is correct: `us-central1-docker.pkg.dev/PROJECT_ID/open-webui-remote/open-webui/open-webui:main`

5. **Application Not Starting**
   - Check the container logs in Cloud Run console
   - Verify the port configuration (should be 8080)
   - Check if all required environment variables are properly set

### Useful Commands

```bash
# View service details
gcloud run services describe open-webui --region=us-central1

# View recent logs
gcloud logs tail --service=open-webui --region=us-central1

# Update environment variables
gcloud run services update open-webui --region=us-central1 --set-env-vars-from-file .env

# Scale the service
gcloud run services update open-webui --region=us-central1 --max-instances=5
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
gcloud logs tail --service=open-webui --region=us-central1

# Filter logs by severity
gcloud logs tail --service=open-webui --region=us-central1 --min-log-level=ERROR
```

## 🔄 Updates and Maintenance

### Updating the Application

```bash
# Redeploy with the latest image
./deploy-cloud-run.sh

# Or manually
gcloud run services update open-webui --region=us-central1 --image=ghcr.io/open-webui/open-webui:main
```

### Database Migrations

Open WebUI automatically handles database migrations on startup. No manual intervention is required.

## 📞 Support

- **Open WebUI Documentation**: https://docs.openwebui.com/
- **Google Cloud Run Documentation**: https://cloud.google.com/run/docs
- **Supabase Documentation**: https://supabase.com/docs

## 🎉 Congratulations!

You've successfully deployed Open WebUI to Google Cloud Run with external Supabase database and OpenAI API integration. Your application is now scalable, secure, and ready for production use! 