#!/bin/bash

# MemoGraph MCP Marketplace Publishing Script
# This script automates the process of publishing MemoGraph to PyPI and the MCP marketplace

set -e  # Exit on error

echo "🚀 MemoGraph MCP Marketplace Publishing Script"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: pyproject.toml not found. Are you in the repository root?${NC}"
    exit 1
fi

# Step 1: Check prerequisites
echo "📋 Step 1: Checking prerequisites..."
echo ""

# Check if build tools are installed
if ! command -v python &> /dev/null; then
    echo -e "${RED}Error: Python not found${NC}"
    exit 1
fi

if ! python -c "import build" 2>/dev/null; then
    echo -e "${YELLOW}Installing build tools...${NC}"
    pip install build twine
fi

# Check if tests pass
echo "Running tests..."
if ! pytest; then
    echo -e "${RED}Error: Tests failed. Fix tests before publishing.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Prerequisites check passed${NC}"
echo ""

# Step 2: Version check
echo "📦 Step 2: Version check..."
echo ""

CURRENT_VERSION=$(grep -oP '(?<=version = ")[^"]*' pyproject.toml)
echo "Current version: $CURRENT_VERSION"
echo ""

read -p "Is this the correct version for marketplace release? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Please update version in pyproject.toml and smithery.json"
    exit 1
fi

# Step 3: Clean previous builds
echo "🧹 Step 3: Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info
echo -e "${GREEN}✓ Cleaned${NC}"
echo ""

# Step 4: Build distribution
echo "📦 Step 4: Building distribution..."
python -m build
echo -e "${GREEN}✓ Built${NC}"
echo ""

# Step 5: Check distribution
echo "✅ Step 5: Checking distribution..."
twine check dist/*
echo -e "${GREEN}✓ Check passed${NC}"
echo ""

# Step 6: Upload to Test PyPI (optional)
echo "🧪 Step 6: Upload to Test PyPI (optional)..."
echo ""
read -p "Upload to Test PyPI first? (recommended) (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Uploading to Test PyPI..."
    twine upload --repository testpypi dist/*
    echo -e "${GREEN}✓ Uploaded to Test PyPI${NC}"
    echo ""
    echo "Test installation with:"
    echo "pip install --index-url https://test.pypi.org/simple/ memograph"
    echo ""
    read -p "Press enter to continue..."
fi

# Step 7: Upload to PyPI
echo "📤 Step 7: Upload to PyPI (production)..."
echo ""
read -p "Upload to PyPI? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Skipping PyPI upload. You can upload later with: twine upload dist/*"
    exit 0
fi

twine upload dist/*
echo -e "${GREEN}✓ Uploaded to PyPI${NC}"
echo ""

# Step 8: Create Git tag
echo "🏷️  Step 8: Creating Git tag..."
echo ""
read -p "Create and push Git tag v$CURRENT_VERSION? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git add pyproject.toml CHANGELOG.md smithery.json
    git commit -m "chore: release v$CURRENT_VERSION for MCP marketplace" || true
    git tag -a "v$CURRENT_VERSION" -m "Release v$CURRENT_VERSION"
    git push origin main --tags
    echo -e "${GREEN}✓ Tag created and pushed${NC}"
fi

echo ""
echo "✅ Publishing complete!"
echo ""
echo "Next steps:"
echo "1. Visit https://smithery.ai and submit your server"
echo "2. Or create PR to https://github.com/smithery-ai/servers"
echo "3. Monitor PyPI stats at https://pypistats.org/packages/memograph"
echo "4. Update README with marketplace badge"
echo ""
echo "Your MemoGraph server is now available at:"
echo "  pip install memograph"
echo ""
