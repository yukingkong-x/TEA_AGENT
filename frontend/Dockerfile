# 前端控制台镜像（PRD 21.2 一键启动的 ui 服务）
#
# 两段式：node 里 build 出 dist，再塞进 nginx。运行镜像里没有 node/npm，
# 也不留源码，镜像小、启动快。
FROM node:22-alpine AS build
WORKDIR /app

# 先只拷依赖清单：依赖没变就命中这层缓存，改业务代码不必重装 2 分钟
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
# build = tsc --noEmit && vite build，类型错误会在这里把镜像构建打断（故意的）
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
# 编排里 backend 的 healthcheck 有 30s start_period；这里只要静态资源能出就算活
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
