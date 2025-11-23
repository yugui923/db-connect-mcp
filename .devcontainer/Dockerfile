FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# Install system dependencies needed for development
RUN apt-get update
RUN apt-get install -y \
    # Build essentials for native extensions
    build-essential \
    # SSL/crypto libraries
    libssl-dev libffi-dev \
    # Database clients (for MCP servers)
    sqlite3 postgresql-client mysql-client \
    # Python build dependencies
    libbz2-dev libreadline-dev libsqlite3-dev \
    zlib1g-dev liblzma-dev \
    # Useful utilities
    jq curl wget git unzip zip
RUN apt-get clean

# Switch to vscode user for tool installation
USER vscode

# Install mise (runtime version manager)
RUN curl https://mise.run | sh
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Configure mise to auto-activate
RUN echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc && \
    echo 'eval "$(~/.local/bin/mise activate zsh)"' >> ~/.zshrc

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/home/vscode/.cargo/bin:${PATH}"

# Pre-install common Python and Node versions via mise
RUN mise install python@3.13 && \
    mise install node@22

# Install global npm packages
RUN mise exec node -- npm install -g \
    @anthropic-ai/claude-code \
    typescript \
    tsx \
    prettier \
    eslint

# Install global Python tools via uv
RUN uv tool install ruff && \
    uv tool install black && \
    uv tool install mypy && \
    uv tool install pytest

WORKDIR /workspace
