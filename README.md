# Video Download Service

基于 yt-dlp 的视频下载服务，提供 REST API 和 Web 调试界面，支持异步下载和回调通知。

---

## 快速开始

### 方式一：Docker（推荐）

```bash
# 启动所有服务
docker-compose up -d

# 访问 Web 界面
open http://localhost:8000

# 停止服务
docker-compose down
```

### 方式二：本地开发

```bash
# 1. 安装依赖
pip3 install -r requirements.txt
brew install redis ffmpeg  # macOS

# 2. 启动 Redis
brew services start redis

# 3. 启动 API（终端 1）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. 启动 Worker（终端 2）
celery -A app.celery_app worker --loglevel=info

# 5. 访问
open http://localhost:8000
```

---

## 功能特性

- **Web 调试界面** - 可视化提交任务、查看进度、管理下载
- **REST API** - 完整的 API 接口，支持外部系统集成
- **异步下载** - Celery + Redis 任务队列，支持 100+ 并发
- **进度追踪** - 实时显示下载进度、文件大小
- **回调通知** - 下载完成后自动通知指定 URL
- **多站点支持** - yt-dlp 支持 1000+ 视频网站

---

## Web 界面

访问 http://localhost:8000 即可使用：

| 功能 | 说明 |
|------|------|
| **任务提交** | 输入视频 URL，一键下载 |
| **视频预览** | 提交前预览视频信息 |
| **进度显示** | 实时进度条 + 已下载/总大小 |
| **任务管理** | 查看详情、删除任务 |
| **系统状态** | API 状态、队列统计 |

> API 文档: http://localhost:8000/docs

---

## 架构说明

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   客户端     │────▶│   FastAPI   │────▶│    Redis    │
│  (Web/API)  │     │   API 服务   │     │   任务队列   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                    │
                           │                    ▼
                           │            ┌─────────────┐
                           │            │   Celery    │
                           │            │   Worker    │
                           │            └─────────────┘
                           │                    │
                           │                    ▼
                           │            ┌─────────────┐
                           │            │   yt-dlp    │
                           │            │   下载引擎   │
                           │            └─────────────┘
                           │                    │
                           ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   SQLite    │     │  本地文件    │
                    │   任务状态   │     │  (云存储)   │
                    └─────────────┘     └─────────────┘
```

| 组件 | 作用 |
|------|------|
| **FastAPI** | REST API + Web 界面 |
| **Redis** | Celery 消息队列 |
| **Celery Worker** | 后台执行下载任务 |
| **SQLite** | 任务状态持久化 |
| **yt-dlp** | 视频下载引擎 |

---

## 项目结构

```
yt-dlp/
├── app/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置管理
│   ├── models.py            # 数据模型
│   ├── schemas.py           # API 数据结构
│   ├── database.py          # 数据库连接
│   ├── downloader.py        # yt-dlp 封装
│   ├── callback.py          # 回调通知
│   ├── tasks.py             # Celery 任务
│   ├── celery_app.py        # Celery 配置
│   └── static/
│       └── index.html       # Web 调试界面
├── downloads/               # 下载文件目录
├── data/                    # SQLite 数据库
├── docker-compose.yml       # Docker 编排
├── Dockerfile
├── requirements.txt
└── .env.example             # 环境变量示例
```

---

## API 接口

### 提交下载任务

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://www.bilibili.com/video/BV1GJ411x7h7",
    "callback_url": "https://your-server.com/callback"
  }'
```

### 查询任务状态

```bash
curl http://localhost:8000/api/v1/tasks/{task_id}
```

### 获取视频信息（不下载）

```bash
curl -X POST http://localhost:8000/api/v1/video-info \
  -H "Content-Type: application/json" \
  -d '{"video_url": "https://www.bilibili.com/video/BV1GJ411x7h7"}'
```

### 健康检查

```bash
curl http://localhost:8000/api/v1/health
```

---

## 配置说明

复制 `.env.example` 为 `.env`：

```bash
# 下载配置
DOWNLOAD_DIR=./downloads
MAX_CONCURRENT_DOWNLOADS=100
DOWNLOAD_TIMEOUT=3600
MAX_FILE_SIZE=5368709120  # 5GB

# yt-dlp
YTDLP_FORMAT=bestvideo+bestaudio/best
YTDLP_PROXY=  # 可选代理

# Redis
REDIS_URL=redis://localhost:6379/0

# 回调
CALLBACK_TIMEOUT=30
CALLBACK_MAX_RETRIES=3
```

---

## 常见问题

### Q: Docker 启动后无法访问？
检查 Docker Desktop 是否运行，然后执行 `docker-compose up -d`。

### Q: 任务一直 pending？
确保 Worker 正在运行：
- Docker: `docker-compose logs worker`
- 本地: 检查 Celery 终端

### Q: 如何支持 YouTube？
需要 JavaScript 运行时。Docker 镜像已包含 Deno。本地开发：
```bash
curl -fsSL https://deno.land/install.sh | sh
```

### Q: 高并发配置？
```bash
# 使用 gevent 协程池
pip install gevent
celery -A app.celery_app worker --pool=gevent --concurrency=100
```

---

## 支持的网站

yt-dlp 支持 1000+ 网站：

- **国内**: Bilibili、抖音、快手、微博、优酷
- **国外**: YouTube、Twitter/X、TikTok、Instagram、Vimeo

完整列表: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md

---

## 开发计划

- [x] FastAPI REST API
- [x] Celery 异步任务
- [x] SQLite 任务存储
- [x] yt-dlp 下载集成
- [x] 回调通知
- [x] Docker 部署
- [x] Web 调试界面
- [ ] S3/OSS 云存储上传
- [ ] WebSocket 实时进度

---

## License

MIT
