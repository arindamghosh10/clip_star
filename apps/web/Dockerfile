FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
RUN npm ci --workspace apps/web --include-workspace-root
COPY apps/web apps/web
RUN rm -f apps/web/.env.development apps/web/.env.local
# Same origin: the Caddy proxy routes /api to the backend.
ENV NEXT_PUBLIC_API_BASE="" NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace apps/web

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app /app
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--workspace", "apps/web"]
