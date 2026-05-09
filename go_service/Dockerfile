FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go .
RUN go get github.com/gorilla/websocket@v1.5.3 && \
    go get github.com/redis/go-redis/v9@v9.7.3 && \
    go mod tidy && \
    go build -o go_bridge .

FROM alpine:3.19
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /app/go_bridge .
EXPOSE 8080
USER appuser
CMD ["./go_bridge"]
