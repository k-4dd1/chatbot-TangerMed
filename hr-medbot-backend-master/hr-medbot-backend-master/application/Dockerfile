FROM python:3.12-slim

# Install build tools and Postgres client libs for psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /application

# Install Python dependencies first – leverage Docker layer caching
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source code
COPY . .

EXPOSE 8000

ENTRYPOINT ["bash", "scripts/docker-entrypoint.sh"]
