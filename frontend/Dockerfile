# =============================================
# AutoCVE Frontend Docker 构建
# =============================================
# 使用 Nginx 提供静态文件和反向代理 (支持 SSE 流式传输)

FROM node:22.19-bookworm-slim AS builder

WORKDIR /app

ARG VITE_ENABLE_CHECKMARX_SCAN=false
ARG VITE_APP_VERSION

# Registry and build proxy settings are supplied by the deployment environment.
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG PNPM_VERSION=9.15.9
RUN npm config set registry "${NPM_REGISTRY}" && \
    npm install -g "pnpm@${PNPM_VERSION}" && \
    pnpm config set registry "${NPM_REGISTRY}"

# 复制依赖文件
COPY package.json pnpm-lock.yaml ./

# 限制安装并发，兼容较小内存的 ARM / x86 主机
RUN pnpm config set network-timeout 300000 && \
    pnpm config set fetch-retries 5 && \
    pnpm install --frozen-lockfile --network-concurrency 1

# 复制源码
COPY . .

# 🔥 构建时使用占位符 - 实现 Build Once Run Anywhere
ENV VITE_API_BASE_URL=__API_BASE_URL__
ENV VITE_ENABLE_CHECKMARX_SCAN=${VITE_ENABLE_CHECKMARX_SCAN}
ENV VITE_APP_VERSION=${VITE_APP_VERSION}

# 构建生产版本
RUN pnpm build

# =============================================
# 生产镜像 - 使用 Nginx (支持 SSE 反向代理)
# =============================================
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置 (包含 SSE 反向代理配置)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制启动脚本
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
