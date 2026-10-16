ARG NODE_IMAGE=node:22-alpine
FROM ${NODE_IMAGE} AS build
ARG VITE_REPORTS_ENABLED=true
ENV VITE_REPORTS_ENABLED=${VITE_REPORTS_ENABLED}
WORKDIR /work
COPY package*.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:stable-alpine
COPY --from=build /work/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
