# HTTPS Development Setup

This document explains how to run the OpenWebUI backend with HTTPS for local development.

## Quick Start

### Option 1: Use the dedicated HTTPS script (Recommended)
```bash
cd backend
./dev-https.sh
```

### Option 2: Use the existing dev.sh with HTTPS mode
```bash
cd backend
USE_HTTPS=true ./dev.sh
```

## What happens

1. **SSL Certificate Generation**: The script automatically generates self-signed SSL certificates for `localhost` and `127.0.0.1`
2. **HTTPS Server**: Uvicorn starts with SSL configuration on port 8083 (default)
3. **CORS Configuration**: Backend is configured to accept requests from `https://localhost:5173`

## URLs

- **Backend API**: `https://localhost:8083`
- **Frontend**: `https://localhost:5173` (when running frontend with HTTPS)

## Browser Security Warning

Since we're using self-signed certificates, your browser will show a security warning. This is normal for development.

**To proceed:**
1. Click "Advanced" or "Show Details"
2. Click "Proceed to localhost (unsafe)" or similar
3. The site will load normally

## Manual Certificate Generation

If you need to regenerate the SSL certificates:

```bash
cd backend
./generate-ssl-certs.sh
```

Or delete the `ssl-certs/` directory and restart the development server.

## Certificate Details

- **Type**: Self-signed X.509 certificate
- **Valid for**: localhost, 127.0.0.1, ::1
- **Validity**: 365 days
- **Key size**: 4096 bits (RSA)

## Troubleshooting

### Certificate errors
- Delete the `ssl-certs/` directory and restart
- Ensure OpenSSL is installed on your system

### Port conflicts
- Change the port by setting the `PORT` environment variable:
  ```bash
  PORT=8084 ./dev-https.sh
  ```

### Frontend connection issues
- Ensure your frontend is also running with HTTPS
- Check that CORS is properly configured for your frontend URL 