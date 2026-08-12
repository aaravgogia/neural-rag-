# Multi-stage build: compile static assets in a full Node image, then ship
# only the built output + a minimal static server. The previous version of
# this file ran `npm run dev` in production, which referenced an npm script
# that didn't exist in package.json -- it would have crashed on `docker run`.

FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_API_URL
ARG VITE_WS_URL
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_WS_URL=$VITE_WS_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
RUN npm install -g serve
RUN addgroup -S appgroup && adduser -S appuser -G appgroup \
    && mkdir -p /app/dist \
    && chown -R appuser:appgroup /app
COPY --from=build --chown=appuser:appgroup /app/dist ./dist
USER appuser
EXPOSE 3000
CMD ["serve", "-s", "dist", "-l", "3000"]
