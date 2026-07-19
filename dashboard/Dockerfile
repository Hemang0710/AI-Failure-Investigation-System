FROM python:3.11-slim

WORKDIR /app

# Copy entire project structure
COPY . /app

# Install dashboard dependencies from the requirements file so the image
# stays in sync with dashboard/requirements.txt (streamlit, pandas, httpx,
# matplotlib, python-dotenv, ...)
RUN pip install --no-cache-dir -r /app/dashboard/requirements.txt

# Make run script executable
RUN chmod +x /app/dashboard/run.sh

EXPOSE 8501

# curl is not installed in python:3.11-slim; probe with the stdlib instead
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["/app/dashboard/run.sh"]
