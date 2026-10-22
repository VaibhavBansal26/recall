# Stages: deps -> build -> prod (production server) ; dev is last so plain `docker compose build`
# (the local dev stack) keeps using it.
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
# Empty means "same origin": the browser calls /api and /ws on the page's own host (via Caddy).
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

FROM node:20-slim AS prod
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/next.config.mjs ./
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0"]

FROM deps AS dev
COPY . .
EXPOSE 3000
# Dev server: hot reload via the bind mount in docker-compose.yml.
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
