export CORS_ALLOW_ORIGIN=https://localhost:5173
PORT="${PORT:-8083}"

# Check if HTTPS mode is enabled
if [ "${USE_HTTPS:-false}" = "true" ]; then
    echo "🚀 Starting OpenWebUI backend with HTTPS on port $PORT"
    echo "   Backend URL: https://localhost:$PORT"
    echo "   Frontend URL: https://localhost:5173"
    echo ""
    
    # SSL certificate paths
    CERT_DIR="ssl-certs"
    KEY_FILE="$CERT_DIR/localhost.key"
    CERT_FILE="$CERT_DIR/localhost.crt"
    
    # Check if SSL certificates exist, generate if not
    if [ ! -f "$KEY_FILE" ] || [ ! -f "$CERT_FILE" ]; then
        echo "SSL certificates not found. Generating..."
        ./generate-ssl-certs.sh
        if [ $? -ne 0 ]; then
            echo "Failed to generate SSL certificates. Exiting."
            exit 1
        fi
    fi
    
    echo "Note: Your browser will show a security warning for the self-signed certificate."
    echo "Click 'Advanced' and 'Proceed to localhost' to continue."
    echo ""
    
    # Start uvicorn with SSL configuration
    uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips '*' --reload --ssl-keyfile "$KEY_FILE" --ssl-certfile "$CERT_FILE"
else
    echo "🚀 Starting OpenWebUI backend with HTTP on port $PORT"
    echo "   Backend URL: http://localhost:$PORT"
    echo "   Frontend URL: https://localhost:5173"
    echo ""
    uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips '*' --reload
fi
