FROM python:3.12.12-slim
WORKDIR /app
COPY server.py .
RUN mkdir /data && chown 65532:65532 /data
USER 65532:65532
EXPOSE 8090
CMD ["python", "server.py"]
