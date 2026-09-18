FROM python:3.13-alpine

RUN addgroup -S provider && adduser -S -G provider provider
WORKDIR /app
COPY server.py /app/server.py
RUN mkdir /data && chown provider:provider /data
USER provider
EXPOSE 8080
CMD ["python", "/app/server.py"]
