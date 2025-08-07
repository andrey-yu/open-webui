#!/bin/bash

# Generate SSL certificates for localhost development
# This script creates certificates that are valid for localhost and 127.0.0.1
# Uses mkcert if available (creates locally-trusted certificates)
# Falls back to OpenSSL self-signed certificates

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "$SCRIPT_DIR" || exit

CERT_DIR="ssl-certs"
KEY_FILE="$CERT_DIR/localhost.key"
CERT_FILE="$CERT_DIR/localhost.crt"

# Create SSL certificates directory if it doesn't exist
mkdir -p "$CERT_DIR"

# Check if certificates already exist
if [ -f "$KEY_FILE" ] && [ -f "$CERT_FILE" ]; then
    echo "SSL certificates already exist at $CERT_DIR/"
    echo "To regenerate, delete the $CERT_DIR/ directory and run this script again."
    exit 0
fi

# Check if mkcert is available (preferred method)
if command -v mkcert &> /dev/null; then
    echo "Using mkcert to generate locally-trusted SSL certificates..."
    
    # Install mkcert root CA if not already installed
    mkcert -install 2>/dev/null || echo "mkcert root CA already installed"
    
    # Generate certificates for localhost
    mkcert -key-file "$KEY_FILE" -cert-file "$CERT_FILE" localhost 127.0.0.1 ::1
    
    if [ $? -eq 0 ]; then
        echo "✅ Locally-trusted SSL certificates generated successfully!"
        echo "   Key file: $KEY_FILE"
        echo "   Cert file: $CERT_FILE"
        echo ""
        echo "Note: These certificates are locally-trusted and should work without browser warnings."
    else
        echo "❌ Failed to generate certificates with mkcert"
        exit 1
    fi
else
    echo "mkcert not found, using OpenSSL to generate self-signed certificates..."
    echo "Note: Your browser will show a security warning for self-signed certificates."
    echo "You can safely proceed by clicking 'Advanced' and 'Proceed to localhost'."
    echo ""
    
    # Generate private key and certificate using OpenSSL
    openssl req -x509 -newkey rsa:4096 -keyout "$KEY_FILE" -out "$CERT_FILE" -days 365 -nodes \
        -subj "/C=US/ST=Development/L=Development/O=OpenWebUI/OU=Development/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,DNS:127.0.0.1,IP:127.0.0.1,IP:::1"
    
    if [ $? -eq 0 ]; then
        echo "✅ Self-signed SSL certificates generated successfully!"
        echo "   Key file: $KEY_FILE"
        echo "   Cert file: $CERT_FILE"
        echo ""
        echo "Note: These are self-signed certificates. Your browser will show a security warning."
        echo "You can safely proceed by clicking 'Advanced' and 'Proceed to localhost'."
    else
        echo "❌ Failed to generate SSL certificates"
        exit 1
    fi
fi 