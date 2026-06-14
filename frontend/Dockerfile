FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite inlines the Supabase config into the bundle at build time. Passed as build
# args (not a baked-in .env) so the image stays config-free; compose supplies
# them from frontend/.env — see docker-compose.yml and the README.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
RUN test -n "$VITE_SUPABASE_URL" && test -n "$VITE_SUPABASE_ANON_KEY" || \
    (echo "ERROR: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY build args are required." \
          "Run: docker compose --env-file frontend/.env up -d --build" && false)
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
RUN npm run build

FROM nginx:1.27-alpine
# Config is rendered at start from a template so the listen port and backend
# upstream can be supplied per environment (compose vs Railway) without a rebuild.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
ENTRYPOINT ["/docker-entrypoint.sh"]
