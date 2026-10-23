FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fieldagent ./fieldagent
COPY mock_ticketing ./mock_ticketing
COPY evals ./evals
COPY corpus ./corpus

RUN useradd --create-home --uid 10001 agent
USER agent

ENTRYPOINT ["python", "-m", "fieldagent"]
CMD ["--help"]
