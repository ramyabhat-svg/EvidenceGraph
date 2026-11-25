FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
ENV VITE_API_BASE_URL=/api/v1/workspace
RUN npm run build

FROM nginx:alpine
COPY infra/docker/web.conf /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
