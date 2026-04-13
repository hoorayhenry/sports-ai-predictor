FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Final stage — just the built files (nginx serves them via volume)
FROM alpine:3.19
WORKDIR /dist
COPY --from=builder /app/dist .
CMD ["sh", "-c", "echo 'Frontend built. Files are in /dist.' && ls -la"]
