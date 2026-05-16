# Build from repository root:
#   docker build -f web/Dockerfile \
#     --build-arg NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000 \
#     --build-arg NEXT_PUBLIC_LANGFUSE_PUBLIC_URL=https://cloud.langfuse.com \
#     -t querymesh-web:local .
#
# NEXT_PUBLIC_* is inlined at build time. Use URLs your *browser* can reach (API on host → 127.0.0.1:8000).

FROM node:20-alpine AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
ARG NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_LANGFUSE_PUBLIC_URL=
ENV NEXT_PUBLIC_QUERYMESH_URL=$NEXT_PUBLIC_QUERYMESH_URL
ENV NEXT_PUBLIC_LANGFUSE_PUBLIC_URL=$NEXT_PUBLIC_LANGFUSE_PUBLIC_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs
RUN mkdir -p ./public
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
