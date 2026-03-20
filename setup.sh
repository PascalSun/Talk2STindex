#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }
echo_step() { echo -e "${BLUE}==>${NC} $1"; }

INSTALL_MCP=""
for arg in "$@"; do
    case $arg in
        --mcp) INSTALL_MCP="true" ;;
        --help|-h)
            echo "Usage: ./setup.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --mcp     Install with MCP server support"
            echo "  --help    Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./setup.sh              # Basic installation"
            echo "  ./setup.sh --mcp        # With MCP server"
            exit 0
            ;;
        *)
            echo_error "Unknown argument: $arg"
            echo_info "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo_step "Starting Talk2STIndex development environment setup..."
echo ""

# Check Python
echo_step "Step 1: Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
        echo_info "Python $PYTHON_VERSION detected (3.11+ supported)"
    else
        echo_error "Python 3.11+ required, but found $PYTHON_VERSION"
        exit 1
    fi
else
    echo_error "Python 3 not found. Please install Python 3.11 or higher."
    exit 1
fi
echo ""

# Check uv
echo_step "Step 2: Checking uv package manager..."
if ! command -v uv &> /dev/null; then
    echo_warn "uv is not installed. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        echo_error "Failed to install uv. Please install manually:"
        echo_info "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    echo_info "uv installed successfully!"
else
    echo_info "uv is already installed"
fi
echo ""

# Create venv
echo_step "Step 3: Creating virtual environment..."
if [ ! -d ".venv" ]; then
    echo_info "Creating virtual environment with uv..."
    uv venv
else
    echo_warn "Virtual environment already exists, skipping..."
fi
echo ""

# Install
echo_step "Step 4: Installing Talk2STIndex..."
source .venv/bin/activate

if [ "$INSTALL_MCP" = "true" ]; then
    EXTRAS="mcp,dev"
    echo_info "Installing with MCP server support"
else
    read -p "Install with MCP server support? (Y/n): " -n 1 -r </dev/tty
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        EXTRAS="mcp,dev"
        echo_info "Installing with MCP server support"
    else
        EXTRAS="dev"
        echo_info "Installing basic version"
    fi
fi

uv pip install -e ".[$EXTRAS]"
echo ""

# Config
echo_step "Step 5: Setting up configuration..."
if [ ! -f "config.yml" ] && [ -f "config.example.yml" ]; then
    cp config.example.yml config.yml
    echo_info "Created config.yml from example"
else
    echo_warn "config.yml already exists, skipping..."
fi

if [ ! -f "config.mcp.yml" ] && [ -f "config.mcp.example.yml" ]; then
    cp config.mcp.example.yml config.mcp.yml
    echo_info "Created config.mcp.yml from example"
    echo_warn "  Remember to update OAuth credentials in config.mcp.yml"
fi
echo ""

# Verify
echo_step "Step 6: Verifying installation..."
if python -c "import talk2stindex" 2>/dev/null; then
    VERSION=$(python -c "import talk2stindex; print(talk2stindex.__version__)")
    echo_info "Talk2STIndex v$VERSION successfully installed!"
else
    echo_warn "Package import test failed. Please check the installation."
fi

if python -c "import talk2stindex.mcp" 2>/dev/null; then
    echo_info "MCP server support available"
fi
echo ""

echo_step "=========================================="
echo_step "Setup complete!"
echo_step "=========================================="
echo ""
echo_info "To activate the environment:"
echo "  source .venv/bin/activate"
echo ""
echo_info "Quick start commands:"
echo "  talk2stindex-mcp sse --port 8014    # Start MCP server"
echo ""

if python -c "import talk2stindex.mcp" 2>/dev/null; then
    echo_info "MCP Server commands:"
    echo "  talk2stindex-mcp sse --config config.mcp.yml --host 127.0.0.1 --port 8014"
    echo "  talk2stindex-mcp sse --port 8014  # Custom port"
    echo ""
    echo_info "Next steps for MCP:"
    echo "  1. Edit config.mcp.yml with your OAuth credentials"
    echo "  2. Start the MCP server"
    echo ""
fi

echo_info "Run tests:"
echo "  pytest tests/"
echo ""
echo_step "=========================================="
