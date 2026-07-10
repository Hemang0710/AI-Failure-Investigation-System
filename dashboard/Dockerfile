FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit pandas httpx

# Copy entire project structure
COPY . /app

# Make run script executable
RUN chmod +x /app/dashboard/run.sh

EXPOSE 8501

# curl is not installed in python:3.11-slim; probe with the stdlib instead
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["/app/dashboard/run.sh"]
