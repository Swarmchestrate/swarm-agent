# Dockerfile
FROM python:3.12-slim 


# Set working directory
WORKDIR /app

ARG PUCCINI_AMD64_URL="https://github.com/Swarmchestrate/tosca/releases/download/v0.2.4/go-puccini_0.22.7-SNAPSHOT-3e85b40_linux_amd64.deb"
ARG PUCCINI_ARM64_URL="https://github.com/Swarmchestrate/tosca/releases/download/v0.2.4/go-puccini_0.22.7-SNAPSHOT-3e85b40_linux_arm64.deb"
ARG PUCCINI_ARMHF_URL="https://github.com/Swarmchestrate/tosca/releases/download/v0.2.4/go-puccini_0.22.7-SNAPSHOT-3e85b40_linux_armhf.deb"

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install puccini (TOSCA library)
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) puccini_url="$PUCCINI_AMD64_URL" ;; \
        arm64) puccini_url="$PUCCINI_ARM64_URL" ;; \
        armhf) puccini_url="$PUCCINI_ARMHF_URL" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac \
    && if [ -z "$puccini_url" ]; then echo "Missing Puccini download URL for architecture: $arch" >&2; exit 1; fi \
    && wget -q "$puccini_url" -O /tmp/puccini.deb \
    && (dpkg -i /tmp/puccini.deb || apt-get install -f -y) \
    && rm /tmp/puccini.deb

COPY ./requirements.txt /app/requirements.txt

# Install required packages
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

# Verify specific module import
#RUN python -c "from swch_com.swchagent import SwchAgent; print('SwchAgent imported successfully')"

# Always fetch latest lib_comm from GitHub
RUN pip install --no-cache-dir --upgrade git+https://github.com/Swarmchestrate/lib_comm.git@main



# Copy application files
COPY src/main.py .
COPY src/SA.py .
COPY src/utility.py .
COPY src/monitoring_input.py .

# Create config directory
RUN mkdir -p /config

# Create non-root user
#RUN useradd -r -u 1000 swarmuser
#RUN chown -R swarmuser:swarmuser /app /config
#USER swarmuser

# Expose P2P port
EXPOSE 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import SA; print('healthy')" || exit 1

# Run the application
CMD ["python3", "main.py"]
#CMD ["python3", "main.py", "/config/config.yaml", "/config/tosca.yaml"]


