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
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function for error messages
error_exit() {
    echo -e "${RED}Error: $1${NC}" >&2
    exit 1
}

# Helper function for warnings
warn() {
    echo -e "${YELLOW}Warning: $1${NC}" >&2
}

# Helper function for info messages
info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    error_exit "pyproject.toml not found. Are you in the repository root?"
fi

# Step 1: Check prerequisites
echo "📋 Step 1: Checking prerequisites..."
echo ""

# Check for required tools
# Try to find Python (works on Windows, macOS, Linux)
# Prioritize virtual environment Python if active
PYTHON_CMD=""

# Check if we're in a virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    # Try Windows venv paths first
    if [ -f "$VIRTUAL_ENV/Scripts/python.exe" ]; then
        PYTHON_CMD="$VIRTUAL_ENV/Scripts/python.exe"
    elif [ -f "$VIRTUAL_ENV/Scripts/python" ]; then
        PYTHON_CMD="$VIRTUAL_ENV/Scripts/python"
    # Try Unix venv paths
    elif [ -f "$VIRTUAL_ENV/bin/python" ]; then
        PYTHON_CMD="$VIRTUAL_ENV/bin/python"
    elif [ -f "$VIRTUAL_ENV/bin/python3" ]; then
        PYTHON_CMD="$VIRTUAL_ENV/bin/python3"
    fi
fi

# If not in venv or venv python not found, search PATH
if [ -z "$PYTHON_CMD" ]; then
    for cmd in python python3 python.exe python3.exe; do
        if command -v $cmd &> /dev/null; then
            # Verify it has pip (to avoid system Python without pip)
            if $cmd -m pip --version &> /dev/null; then
                PYTHON_CMD=$cmd
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON_CMD" ]; then
    error_exit "Python not found. Please install Python 3.10+ or activate a virtual environment"
fi

if ! command -v git &> /dev/null; then
    error_exit "git not found. Please install git"
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: $PYTHON_VERSION (using $PYTHON_CMD)"

# Check if build tools are installed
if ! $PYTHON_CMD -c "import build" 2>/dev/null; then
    echo -e "${YELLOW}Installing build tools...${NC}"
    $PYTHON_CMD -m pip install build twine
fi

if ! command -v twine &> /dev/null && ! $PYTHON_CMD -c "import twine" 2>/dev/null; then
    echo -e "${YELLOW}Installing twine...${NC}"
    $PYTHON_CMD -m pip install twine
fi

# Check if pytest is available
if ! command -v pytest &> /dev/null && ! $PYTHON_CMD -c "import pytest" 2>/dev/null; then
    warn "pytest not found, skipping tests"
    SKIP_TESTS=true
else
    SKIP_TESTS=false
fi

echo -e "${GREEN}✓ All required tools found${NC}"
echo ""

# Step 2: Git state validation
echo "🔍 Step 2: Git state validation..."
echo ""

# Check if git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    error_exit "Not a git repository"
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    warn "You have uncommitted changes"
    git status --short
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Detect current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
info "Current branch: $CURRENT_BRANCH"

# Check if remote 'origin' exists
if ! git remote | grep -q '^origin$'; then
    warn "Remote 'origin' not found"
fi

echo -e "${GREEN}✓ Git state validated${NC}"
echo ""

# Step 3: Run tests
if [ "$SKIP_TESTS" = false ]; then
    echo "🧪 Step 3: Running tests..."
    echo ""
    if ! pytest; then
        error_exit "Tests failed. Fix tests before publishing."
    fi
    echo -e "${GREEN}✓ Tests passed${NC}"
    echo ""
else
    echo "⚠️  Step 3: Skipping tests (pytest not available)"
    echo ""
fi

# Step 4: Version extraction and validation
echo "📦 Step 4: Version validation..."
echo ""

# Extract version from pyproject.toml (portable method using sed)
# Remove carriage returns and trim whitespace
PYPROJECT_VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1 | tr -d '\r' | xargs)

if [ -z "$PYPROJECT_VERSION" ]; then
    error_exit "Could not extract version from pyproject.toml"
fi

info "Version in pyproject.toml: $PYPROJECT_VERSION"

# Check version in smithery.json if it exists
if [ -f "smithery.json" ]; then
    # Extract version from smithery.json (handles both with and without quotes)
    # Remove carriage returns and trim whitespace
    SMITHERY_VERSION=$($PYTHON_CMD -c "import json; print(json.load(open('smithery.json'))['version'])" 2>/dev/null | tr -d '\r' | xargs)

    if [ -n "$SMITHERY_VERSION" ]; then
        info "Version in smithery.json: $SMITHERY_VERSION"

        # Trim both versions and remove any remaining carriage returns
        PYPROJECT_VERSION=$(echo "$PYPROJECT_VERSION" | tr -d '\r' | xargs)
        SMITHERY_VERSION=$(echo "$SMITHERY_VERSION" | tr -d '\r' | xargs)

        if [ "$PYPROJECT_VERSION" != "$SMITHERY_VERSION" ]; then
            error_exit "Version mismatch! pyproject.toml ($PYPROJECT_VERSION) != smithery.json ($SMITHERY_VERSION)"
        fi
        echo -e "${GREEN}✓ Versions are consistent${NC}"
    else
        warn "Could not extract version from smithery.json"
    fi
else
    info "smithery.json not found (optional)"
fi

echo ""
CURRENT_VERSION="$PYPROJECT_VERSION"

# Step 5: Pre-flight summary
echo "✈️  Step 5: Pre-flight summary"
echo "=============================="
echo ""
echo "  Version:       $CURRENT_VERSION"
echo "  Branch:        $CURRENT_BRANCH"
echo "  Repository:    $(git remote get-url origin 2>/dev/null || echo 'No remote')"
echo "  Last commit:   $(git log -1 --pretty=format:'%h - %s' 2>/dev/null || echo 'No commits')"
echo ""
read -p "Is this correct? Proceed with publishing? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Publishing cancelled."
    exit 0
fi

# Step 6: Clean previous builds
echo ""
echo "🧹 Step 6: Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info
echo -e "${GREEN}✓ Cleaned${NC}"
echo ""

# Step 7: Build distribution
echo "📦 Step 7: Building distribution..."
$PYTHON_CMD -m build
echo -e "${GREEN}✓ Built${NC}"
echo ""

# Step 8: Check distribution
echo "✅ Step 8: Checking distribution..."
$PYTHON_CMD -m twine check dist/*
echo -e "${GREEN}✓ Check passed${NC}"
echo ""

# Step 9: Upload to Test PyPI (optional)
echo "🧪 Step 9: Upload to Test PyPI (optional)..."
echo ""
info "Testing on Test PyPI first is highly recommended"
read -p "Upload to Test PyPI first? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Uploading to Test PyPI..."
    if $PYTHON_CMD -m twine upload --repository testpypi dist/*; then
        echo -e "${GREEN}✓ Uploaded to Test PyPI${NC}"
        echo ""
        echo "Test installation with:"
        echo "  pip install --index-url https://test.pypi.org/simple/ memograph"
        echo ""
        read -p "Press enter to continue to production PyPI..."
    else
        error_exit "Test PyPI upload failed"
    fi
fi

# Step 10: Upload to PyPI
echo ""
echo "📤 Step 10: Upload to PyPI (production)..."
echo ""
warn "This will publish to production PyPI and cannot be undone!"
read -p "Upload to PyPI? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Skipping PyPI upload. You can upload later with:"
    echo "  $PYTHON_CMD -m twine upload dist/*"
    exit 0
fi

if $PYTHON_CMD -m twine upload dist/*; then
    echo -e "${GREEN}✓ Uploaded to PyPI${NC}"
else
    error_exit "PyPI upload failed"
fi

echo ""

# Step 11: Create Git tag
echo "🏷️  Step 11: Creating Git tag..."
echo ""
read -p "Create and push Git tag v$CURRENT_VERSION? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Only commit if there are changes
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        echo "Committing version bump..."
        git add pyproject.toml CHANGELOG.md smithery.json 2>/dev/null || true
        if git commit -m "chore: release v$CURRENT_VERSION for MCP marketplace"; then
            echo -e "${GREEN}✓ Changes committed${NC}"
        else
            warn "Nothing to commit (already committed?)"
        fi
    fi

    # Create tag
    if git tag -a "v$CURRENT_VERSION" -m "Release v$CURRENT_VERSION"; then
        echo -e "${GREEN}✓ Tag created${NC}"

        # Push to remote
        if git remote | grep -q '^origin$'; then
            echo "Pushing to $CURRENT_BRANCH and tags..."
            if git push origin "$CURRENT_BRANCH" --tags; then
                echo -e "${GREEN}✓ Tag and commits pushed to origin${NC}"
            else
                warn "Failed to push to remote. You may need to push manually:"
                echo "  git push origin $CURRENT_BRANCH --tags"
            fi
        else
            warn "No remote 'origin' found. Push manually when ready:"
            echo "  git push <remote> $CURRENT_BRANCH --tags"
        fi
    else
        warn "Tag creation failed. It may already exist."
    fi
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
