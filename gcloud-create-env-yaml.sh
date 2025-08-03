#!/bin/bash

# Create a YAML file from .env.production
echo "# Cloud Run Environment Variables" > gcloud-env.yaml
grep -v '^#' .env | grep '=' | while IFS= read -r line; do
  # Extract key and value
  key=$(echo "$line" | cut -d '=' -f 1)
  value=$(echo "$line" | cut -d '=' -f 2-)
  
  # Remove any leading/trailing quotes from the value
  value=$(echo "$value" | sed 's/^"//;s/"$//;s/^'\''//;s/'\''$//')
  
  # Special handling for CORS_ALLOW_ORIGIN
  if [ "$key" = "CORS_ALLOW_ORIGIN" ]; then
    # If it's a wildcard, we'll handle it specially in the deployment script
    # For now, just write it without extra quotes
    echo "$key: \"$value\"" >> gcloud-env.yaml
  else
    # Write to YAML with proper formatting
    echo "$key: \"$value\"" >> gcloud-env.yaml
  fi
done

echo "Created gcloud-env.yaml from .env" 