# Open WebUI Developer Guide 🚀

This guide covers local development setup for Open WebUI, including HTTPS configuration and database connection management.

## Prerequisites

- **Node.js** (v18 or higher)
- **Python** (3.11 or higher)
- **Git**
- **OpenSSL** (for HTTPS certificates)

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/open-webui/open-webui.git
cd open-webui
```

### 2. Install Dependencies

```bash
# Install frontend dependencies
npm install

# Install backend dependencies
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./dev-https.sh

(deactivate)
```

## Local Development with HTTPS 🔒

Open WebUI now supports HTTPS for local development, providing a more secure and production-like environment.

### Backend HTTPS Setup

The backend includes built-in HTTPS support with automatic SSL certificate generation.

#### Option 1: Use the dedicated HTTPS script (Recommended)

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate
./dev-https.sh
```

#### Option 2: Use the existing dev.sh with HTTPS mode

```bash
cd backend
USE_HTTPS=true ./dev.sh
```

#### What happens automatically:

1. **SSL Certificate Generation**: Self-signed certificates are generated for `localhost` and `127.0.0.1`
2. **HTTPS Server**: Uvicorn starts with SSL configuration on port 8083 (default)
3. **CORS Configuration**: Backend accepts requests from `https://localhost:5173`

### Frontend HTTPS Setup

The frontend supports HTTPS through Vite's built-in HTTPS configuration.

```bash
# Run frontend with HTTPS
npm run dev:https
```

This will:
- Generate SSL certificates in `.vite-certs/` directory
- Start the development server on `https://localhost:5173`
- Configure CORS to work with the HTTPS backend

### Complete HTTPS Development Setup

To run both frontend and backend with HTTPS:

1. **Start the backend with HTTPS**:
   ```bash
   cd backend
   python3.11 -m venv venv
   source venv/bin/activate
   ./dev-https.sh
   ```

2. **In a new terminal, start the frontend with HTTPS**:
   ```bash
   npm run dev:https
   ```

3. **Access your application**:
   - Frontend: https://localhost:5173
   - Backend API: https://localhost:8083

### Browser Security Warnings

Since we're using self-signed certificates, your browser will show security warnings. This is normal for development.

**To proceed:**
1. Click "Advanced" or "Show Details"
2. Click "Proceed to localhost (unsafe)" or similar
3. The site will load normally

## Database Configuration 🗄️

### Supabase Connection Pooling

When using Supabase as your database, it's **crucial** to connect via Session Pooler URL rather than directly. This ensures proper connection management.

Locate Your Connection String: Go to your Supabase project dashboard, navigate to Database, and then select Connection String.

Select the Session Pooler: In the "Connection info" section, choose the Connection pooler tab.

Copy the URI: Copy the URI provided.

#### Environment Variables

Configure your database connection using these environment variables:

```bash
#DIrect do not use
#DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres

#Pool connection
DATABASE_URL=postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres

```

#### Connection Pooling Configuration

For production-like performance, configure the connection pool:

```bash
# Database Connection Pooling (recommended for production)
DATABASE_POOL_SIZE=10
DATABASE_POOL_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=3600
```

### Local Development Database

For local development, you can use SQLite (default) or PostgreSQL:

```bash
# SQLite (default for local development)
DATABASE_URL=sqlite:///./data/open-webui.db

# PostgreSQL (for production-like testing)
DATABASE_URL=postgresql://user:password@localhost:5432/openwebui
```

## Session Management 🔐

### Session Pool Configuration

Open WebUI uses session pools for managing user sessions and WebSocket connections:

#### Redis-based Session Pool (Recommended for Production)

```bash
# Enable Redis for session management
REDIS_URL=redis://localhost:6379
WEBSOCKET_MANAGER=redis
```

#### In-Memory Session Pool (Default for Development)

For local development, sessions are stored in memory by default.

### Session Pool Types

1. **SESSION_POOL**: Manages active user sessions
2. **USER_POOL**: Tracks user connections
3. **USAGE_POOL**: Monitors model usage and cleanup

## Development Scripts 📜

### Backend Scripts

```bash
cd backend

# Development with HTTP
./dev.sh

# Development with HTTPS
./dev-https.sh

# Generate SSL certificates manually
./generate-ssl-certs.sh
```

### Frontend Scripts

```bash
# Development with HTTP
npm run dev

# Development with HTTPS
npm run dev:https

# Build for production
npm run build

# Preview production build
npm run preview
```

## Environment Configuration ⚙️

### Required Environment Variables

Create a `.env` file in the backend directory:

```bash
# Database Configuration
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres

# Security
WEBUI_SECRET_KEY=your-secret-key-here

# OpenAI API (if using)
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_API_BASE_URL=https://api.openai.com/v1

# Ollama (if using)
OLLAMA_BASE_URL=http://localhost:11434

# Redis (optional, for session management)
REDIS_URL=redis://localhost:6379
```

### Development-specific Variables

```bash
# Enable development mode
ENV=dev

# CORS configuration for HTTPS
CORS_ALLOW_ORIGIN=https://localhost:5173

# Enable debug logging
SRC_LOG_LEVELS={"DB": "DEBUG", "API": "DEBUG"}
```

## Troubleshooting 🔧

### HTTPS Issues

**Certificate errors:**
```bash
# Delete existing certificates and regenerate
rm -rf backend/ssl-certs/
rm -rf .vite-certs/
# Restart development servers
```

**Port conflicts:**
```bash
# Change backend port
PORT=8084 ./dev-https.sh

# Change frontend port
npm run dev:https -- --port 5174
```

### Database Connection Issues

**Supabase connection problems:**
1. Verify your Supabase database URL
2. Check if your IP is allowed in Supabase
3. Ensure connection pooling is properly configured
4. Verify database credentials

**Connection pool exhaustion:**
```bash
# Increase pool size for high-traffic development
DATABASE_POOL_SIZE=20
DATABASE_POOL_MAX_OVERFLOW=40
```

### Frontend Connection Issues

**CORS errors:**
- Ensure both frontend and backend are running with HTTPS
- Check CORS configuration in backend
- Verify the frontend URL matches the CORS allow origin

## Development Workflow 🔄

### Typical Development Session

1. **Start backend with HTTPS**:
   ```bash
   cd backend
   ./dev-https.sh
   ```

2. **Start frontend with HTTPS**:
   ```bash
   npm run dev:https
   ```

3. **Access the application**:
   - Open https://localhost:5173 in your browser
   - Accept the security warning for the self-signed certificate

4. **Development**:
   - Backend auto-reloads on file changes
   - Frontend hot-reloads on file changes
   - Both servers use HTTPS for secure communication

### Code Quality

```bash
# Lint frontend code
npm run lint:frontend

# Lint backend code
npm run lint:backend

# Format code
npm run format
npm run format:backend

# Type checking
npm run check
```

## Advanced Configuration 🛠️

### Custom SSL Certificates

For development with custom certificates:

```bash
# Backend custom certificates
KEY_FILE=/path/to/your/key.pem
CERT_FILE=/path/to/your/cert.pem

# Frontend custom certificates
# Place certificates in .vite-certs/key.pem and .vite-certs/cert.pem
```

### Database Migrations

```bash
cd backend
# Run migrations
python -m open_webui.migrations.script
```

### Testing

```bash
# Frontend tests
npm run test:frontend

# E2E tests
npm run cy:open
```

## Performance Tips ⚡

### Development Performance

1. **Use connection pooling** for database connections
2. **Enable Redis** for session management in multi-user scenarios
3. **Configure appropriate pool sizes** based on your development needs
4. **Use HTTPS** to catch security-related issues early

### Database Optimization

```bash
# Optimize for development
DATABASE_POOL_SIZE=5
DATABASE_POOL_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=1800
```

## Contributing 🤝

1. Follow the existing code style
2. Run linting and tests before submitting
3. Test with both HTTP and HTTPS configurations
4. Ensure database connection pooling is properly configured
5. Update this documentation for any new features

## Support 💬

- **Documentation**: [Open WebUI Docs](https://docs.openwebui.com/)
- **Discord**: [Open WebUI Community](https://discord.gg/5rJgQTnV4s)
- **Issues**: [GitHub Issues](https://github.com/open-webui/open-webui/issues)

---

Happy coding! 🎉 