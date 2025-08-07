#!/bin/bash

# =============================================================================
# Open WebUI Deployment Comparison Script
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}==============================================================================${NC}"
echo -e "${CYAN}Open WebUI Deployment Comparison${NC}"
echo -e "${CYAN}==============================================================================${NC}"
echo ""

echo -e "${BLUE}Available Deployment Options:${NC}"
echo ""

echo -e "${GREEN}1. Production Deployment (deploy-cloud-run.sh)${NC}"
echo -e "   ${YELLOW}Purpose:${NC} Production deployments using stable releases"
echo -e "   ${YELLOW}Image Source:${NC} GitHub Container Registry (ghcr.io/open-webui/open-webui)"
echo -e "   ${YELLOW}Service Name:${NC} open-webui"
echo -e "   ${YELLOW}Repository:${NC} Remote repository pointing to ghcr.io"
echo -e "   ${YELLOW}Build Process:${NC} No local build required"
echo -e "   ${YELLOW}Update Frequency:${NC} Uses stable releases (v0.6.18, main)"
echo -e "   ${YELLOW}Resource Limits:${NC} 2GB RAM, 1 vCPU"
echo ""

echo -e "${GREEN}2. Development Deployment (deploy-cloud-run-dev.sh)${NC}"
echo -e "   ${YELLOW}Purpose:${NC} Development/testing deployments with custom builds"
echo -e "   ${YELLOW}Image Source:${NC} Built from source using Cloud Build"
echo -e "   ${YELLOW}Service Name:${NC} open-webui-dev"
echo -e "   ${YELLOW}Repository:${NC} Local Artifact Registry repository"
echo -e "   ${YELLOW}Build Process:${NC} Cloud Build from source"
echo -e "   ${YELLOW}Update Frequency:${NC} Can deploy any local changes"
echo -e "   ${YELLOW}Resource Limits:${NC} 4GB RAM, 2 vCPU"
echo ""

echo -e "${CYAN}==============================================================================${NC}"
echo -e "${BLUE}Quick Commands:${NC}"
echo ""

echo -e "${GREEN}Production Deployment:${NC}"
echo "  ./deploy-cloud-run.sh"
echo ""

echo -e "${GREEN}Development Deployment:${NC}"
echo "  ./deploy-cloud-run-dev.sh"
echo ""

echo -e "${GREEN}Check Status:${NC}"
echo "  ./deploy-cloud-run.sh status      # Production"
echo "  ./deploy-cloud-run-dev.sh status  # Development"
echo ""

echo -e "${GREEN}Get Service URL:${NC}"
echo "  ./deploy-cloud-run.sh url         # Production"
echo "  ./deploy-cloud-run-dev.sh url     # Development"
echo ""

echo -e "${CYAN}==============================================================================${NC}"
echo -e "${BLUE}Key Differences Summary:${NC}"
echo ""

echo -e "${YELLOW}✓ Production:${NC} Fast deployment, stable image, lower resources"
echo -e "${YELLOW}✓ Development:${NC} Custom builds, higher resources, Cloud Build"
echo ""

echo -e "${CYAN}==============================================================================${NC}"
echo -e "${BLUE}Documentation:${NC}"
echo ""
echo -e "Production: ${GREEN}CLOUD-RUN-DEPLOYMENT.md${NC}"
echo -e "Development: ${GREEN}CLOUD-RUN-DEV-DEPLOYMENT.md${NC}"
echo ""

echo -e "${CYAN}==============================================================================${NC}" 