#!/bin/bash
# ============================================================
# Meshtastic AI GUI - Release Build Script
# ============================================================
# This script:
#   1. Updates the VERSION in the source code
#   2. Commits the change and creates a git tag
#   3. Compiles the app for Linux (and Windows if on Windows)
#
# Usage: ./build-release.sh <version>
# Example: ./build-release.sh 2.7.0
# ============================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if version argument provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: No version specified${NC}"
    echo ""
    echo "Usage: ./build-release.sh <version>"
    echo "Example: ./build-release.sh 2.7.0"
    exit 1
fi

VERSION="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_FILE="$SCRIPT_DIR/meshtastic-ai-gui.py"
DIST_DIR="$SCRIPT_DIR/dist"

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  Meshtastic AI GUI - Building Release v${VERSION}${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Step 1: Update version in source code
echo -e "${YELLOW}[1/5] Updating version in source code...${NC}"
if grep -q '^VERSION = "' "$MAIN_FILE"; then
    sed -i "s/^VERSION = \".*\"/VERSION = \"$VERSION\"/" "$MAIN_FILE"
    echo -e "${GREEN}      Version updated to $VERSION in meshtastic-ai-gui.py${NC}"
else
    echo -e "${RED}Error: Could not find VERSION line in $MAIN_FILE${NC}"
    exit 1
fi

# Step 2: Check for uncommitted changes (other than version)
echo -e "${YELLOW}[2/5] Committing version change...${NC}"
git add "$MAIN_FILE"
git commit -m "Release v${VERSION}

- Update VERSION to ${VERSION}
- Prepare for release build"
echo -e "${GREEN}      Committed version change${NC}"

# Step 3: Create git tag
echo -e "${YELLOW}[3/5] Creating git tag v${VERSION}...${NC}"
if git tag -l | grep -q "^v${VERSION}$"; then
    echo -e "${RED}Error: Tag v${VERSION} already exists!${NC}"
    echo "Use a different version number or delete the existing tag with:"
    echo "  git tag -d v${VERSION}"
    exit 1
fi
git tag -a "v${VERSION}" -m "Release version ${VERSION}"
echo -e "${GREEN}      Created tag v${VERSION}${NC}"

# Step 4: Install/check PyInstaller
echo -e "${YELLOW}[4/5] Checking PyInstaller...${NC}"
if ! command -v pyinstaller &> /dev/null; then
    echo "      PyInstaller not found. Installing..."
    pip install pyinstaller
fi
echo -e "${GREEN}      PyInstaller is ready${NC}"

# Step 5: Build the application
echo -e "${YELLOW}[5/5] Building application...${NC}"
mkdir -p "$DIST_DIR"

# Detect OS and build accordingly
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "      Building for Linux..."
    pyinstaller --onefile \
        --name "MeshtasticAI-${VERSION}-linux" \
        --clean \
        --noconfirm \
        "$MAIN_FILE"

    # Move to organized location
    mv "$DIST_DIR/MeshtasticAI-${VERSION}-linux" "$DIST_DIR/" 2>/dev/null || true

    echo -e "${GREEN}      Linux build complete!${NC}"

elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    echo "      Building for Windows..."
    pyinstaller --onefile \
        --name "MeshtasticAI-${VERSION}-windows" \
        --clean \
        --noconfirm \
        "$MAIN_FILE"
    echo -e "${GREEN}      Windows build complete!${NC}"

elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "      Building for macOS..."
    pyinstaller --onefile \
        --name "MeshtasticAI-${VERSION}-macos" \
        --clean \
        --noconfirm \
        "$MAIN_FILE"
    echo -e "${GREEN}      macOS build complete!${NC}"
fi

# Cleanup build artifacts
echo ""
echo -e "${YELLOW}Cleaning up build artifacts...${NC}"
rm -rf "$SCRIPT_DIR/build"
rm -f "$SCRIPT_DIR"/*.spec

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  BUILD COMPLETE!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo -e "Version:     ${BLUE}v${VERSION}${NC}"
echo -e "Git tag:     ${BLUE}v${VERSION}${NC} (created)"
echo -e "Output:      ${BLUE}${DIST_DIR}/${NC}"
echo ""
echo "Files created:"
ls -la "$DIST_DIR"/ 2>/dev/null | grep -E "MeshtasticAI-${VERSION}" || echo "  (check dist/ folder)"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Test the compiled application"
echo "  2. Push the tag to GitHub: git push origin v${VERSION}"
echo "  3. Create a GitHub release and upload the binaries"
echo ""
echo -e "${YELLOW}To build for other platforms:${NC}"
echo "  - Run this script on a Windows machine for Windows builds"
echo "  - Run this script on a Mac for macOS builds"
echo "  - Or use GitHub Actions for automated cross-platform builds"
echo ""
