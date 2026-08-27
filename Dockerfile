FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# psycopg2-binary já traz libpq; sem build extra necessário.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY deusold ./deusold
COPY dashboard ./dashboard

# Dashboard por padrão; o serviço "collector" sobrescreve o command no compose.
EXPOSE 8501
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false"]
