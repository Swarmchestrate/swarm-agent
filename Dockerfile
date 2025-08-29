# Dockerfile
FROM python:3.12-slim 


# Set working directory
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*


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

# Create config directory
RUN mkdir -p /config

# Create non-root user
RUN useradd -r -u 1000 swarmuser
RUN chown -R swarmuser:swarmuser /app /config
USER swarmuser

# Expose P2P port
EXPOSE 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import SA; print('healthy')" || exit 1

# Run the application
CMD ["python3", "main.py"]
#CMD ["python3", "main.py", "/config/config.yaml", "/config/tosca.yaml"]


