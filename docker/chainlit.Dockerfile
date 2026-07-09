
FROM python:3.11-slim

WORKDIR /app

COPY chainlit_app/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt  

COPY chainlit_app/app.py app.py
COPY chainlit_app/.chainlit/ .chainlit/

RUN addgroup --system appgroup \
 && adduser --system --ingroup appgroup --no-create-home appuser \
 && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8080"]   

