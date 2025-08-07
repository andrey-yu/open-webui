# Open WebUI Deployment Options

This document provides an overview of the different deployment options available for Open WebUI on Google Cloud Run.

## 🚀 Quick Start

Run the comparison script to see all available options:

```bash
./compare-deployments.sh
```

## 📋 Available Deployment Options

### 1. Production Deployment (`deploy-cloud-run.sh`)

**Best for:** Production environments, stable releases, quick deployments

**Key Features:**
- Uses pre-built images from GitHub Container Registry
- Fast deployment (no local build required)
- Stable and tested releases
- Lower resource usage (2GB RAM, 1 vCPU)
- Remote repository approach

**Usage:**
```bash
./deploy-cloud-run.sh
```

**Documentation:** [CLOUD-RUN-DEPLOYMENT.md](CLOUD-RUN-DEPLOYMENT.md)

### 2. Development Deployment (`deploy-cloud-run-dev.sh`)

**Best for:** Development environments, testing local changes, custom builds

**Key Features:**
- Builds Docker image from source using Google Cloud Build
- Deploys to `-dev` service
- Higher resource allocation (4GB RAM, 2 vCPU)
- Can deploy any local changes
- Local Artifact Registry repository
- No local Docker required
- Uses `cloudbuild.yaml` for build configuration

**Usage:**
```bash
./deploy-cloud-run-dev.sh
```

**Documentation:** [CLOUD-RUN-DEV-DEPLOYMENT.md](CLOUD-RUN-DEV-DEPLOYMENT.md)

## 🔄 Comparison Table

| Aspect | Production | Development |
|--------|------------|-------------|
| **Image Source** | GitHub Container Registry | Built from source |
| **Service Name** | `open-webui` | `open-webui-dev` |
| **Repository** | Remote (ghcr.io) | Local Artifact Registry |
| **Build Time** | Fast (no build) | Medium (Cloud Build) |
| **Resource Usage** | 2GB RAM, 1 vCPU | 4GB RAM, 2 vCPU |
| **Update Frequency** | Stable releases | Any local changes |
| **Use Case** | Production | Development/Testing |

## 🛠️ Common Commands

### Check Status
```bash
# Production
./deploy-cloud-run.sh status

# Development
./deploy-cloud-run-dev.sh status
```

### Get Service URL
```bash
# Production
./deploy-cloud-run.sh url

# Development
./deploy-cloud-run-dev.sh url
```

### View Logs
```bash
# Production
gcloud logs tail --service=open-webui --region=us-central1

# Development
gcloud logs tail --service=open-webui-dev --region=us-central1
```

## 🔧 Prerequisites

Both deployment options require:

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
- Google Cloud project with billing enabled
- Supabase database
- OpenAI API key

## 📁 Configuration

1. **Copy environment template:**
   ```bash
   cp env.cloud-run.example .env
   ```

2. **Configure your `.env` file:**
   ```bash
   nano .env
   ```

3. **Set your project ID:**
   ```bash
   export PROJECT_ID="your-gcp-project-id"
   ```

## 🎯 When to Use Each Option

### Use Production Deployment When:
- Deploying to production environment
- Want fast, reliable deployments
- Using stable releases
- Need lower resource costs
- Don't need custom modifications

### Use Development Deployment When:
- Testing local changes
- Developing new features
- Need custom builds
- Want higher resource allocation
- Working on development/staging environment

## 🔒 Security Notes

- Never commit your `.env` file to version control
- Use Google Secret Manager for sensitive data in production
- Ensure proper database access controls
- Consider additional authentication layers

## 📞 Support

- **Open WebUI Documentation**: https://docs.openwebui.com/
- **Google Cloud Run Documentation**: https://cloud.google.com/run/docs
- **Supabase Documentation**: https://supabase.com/docs

## 🎉 Getting Started

1. **Choose your deployment type** based on your needs
2. **Configure your environment** variables
3. **Run the appropriate deployment script**
4. **Access your application** at the provided URL

For detailed instructions, refer to the specific documentation for each deployment option. 