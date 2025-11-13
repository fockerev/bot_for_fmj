FROM python:3.12

# Install Node.js 18.x
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright dependencies
RUN apt-get update && apt-get install -y \
    wget \
    fonts-liberation \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ./bot /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Clone and setup MCP server
RUN apt-get update && apt-get install -y git \
    && git clone https://github.com/mrkrsl/web-search-mcp.git /app/mcp-server \
    && cd /app/mcp-server \
    && npm install \
    && npx playwright install chromium \
    && npm run build \
    && apt-get remove -y git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

CMD [ "python3", "./main.py" ]
