FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV DEVICE_LAB_HOST=0.0.0.0 DEVICE_LAB_PORT=8877 DEVICE_LAB_DATABASE=/data/device-lab.db
VOLUME ["/data"]
EXPOSE 8877
HEALTHCHECK --interval=20s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8877/health')"
CMD ["device-lab-api"]

