# --------------------------------------------------------------------------- #
#  Build stage                                                                 #
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# --------------------------------------------------------------------------- #
#  Runtime stage                                                               #
# --------------------------------------------------------------------------- #
FROM python:3.12-slim

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
