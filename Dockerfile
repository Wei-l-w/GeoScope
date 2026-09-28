FROM python:3.12-slim

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app/GeoAgent.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
