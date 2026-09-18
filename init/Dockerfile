FROM alpine:3.19

# Install curl and jq for api requests
RUN apk add --no-cache curl jq

WORKDIR /app
COPY init.sh .
RUN chmod +x init.sh

CMD ["/app/init.sh"]
