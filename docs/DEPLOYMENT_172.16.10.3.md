# 172.16.10.3 部署说明

应用地址：http://172.16.10.3:18080 （同一内网访问）

部署日期：2026-10-16。

部署目录：`/data_1/ai-nutritionist-h5`

配置文件：`/data_1/ai-nutritionist-h5/.env`，权限 `600`。真实密码和密钥仅保存在服务器配置，不写入源码或 Git。

## 服务与数据

- Compose 项目：`ai-nutritionist-h5`，包含 FastAPI `api` 和 Nginx/Vue `web` 两个容器，设置 `restart: unless-stopped`。
- 对外入口仅为 `172.16.10.3:18080`；API 的 8000 端口仅在项目容器网络内访问。
- MySQL：复用 `172.16.10.3:3306`，新数据库 `ai_nutritionist_h5`，使用配置中的账号连接。应用启动初始化 9 张表及 10 条演示食品数据。
- 图片持久化目录：`/data_1/ai-nutritionist-h5/data/media`，接口鉴权后由 Nginx 内部路径提供文件。
- 模型：`LLM_BASE_URL=http://172.16.10.3:9000/v1`、`LLM_MODEL=Qwen3.8-27B`；Compose 将其映射到应用的 `VLLM_*` 配置。聊天和识图复用该模型。
- 实际服务模式：`DEMO_MODE=false`。10 条食品成分初始数据仍为项目演示数据。
- 按本次要求，`APP_REPORTS_ENABLED=false`、`VITE_REPORTS_ENABLED=false`；首页隐藏报告入口，生成接口返回 503。未安装 BiSheng。
- 构建使用服务器已有 `python:3.12-slim`、`node:24-bookworm-slim`、`nginx:stable-alpine`；PyPI 镜像源由 `.env` 中的 `PIP_INDEX_URL` 配置。
- 页面使用本机中文字体，不依赖外部 Google Fonts 服务，避免内网字体请求影响加载。

本次仅新增应用容器、应用网络和独立数据库，不重建或停止已有 MySQL、模型和其他应用。

## 配置项

在 `.env` 中集中维护以下值：

```dotenv
APP_BIND_IP=172.16.10.3
APP_PORT=18080
APP_ALLOWED_ORIGIN=http://172.16.10.3:18080
APP_DB_ENGINE=mysql
MYSQL_HOST=172.16.10.3
MYSQL_PORT=3306
MYSQL_DATABASE=ai_nutritionist_h5
MYSQL_USER=root
MYSQL_PASSWORD=在服务器配置文件中设置
LLM_BASE_URL=http://172.16.10.3:9000/v1
LLM_MODEL=Qwen3.8-27B
LLM_API_KEY=在服务器配置文件中设置
APP_REPORTS_ENABLED=false
VITE_REPORTS_ENABLED=false
```

含特殊字符的密码使用单引号包裹。修改端口时同步修改 `APP_ALLOWED_ORIGIN`。

## 查看、更新与重启

服务器安装的是独立命令 `docker-compose`（v2.23.0），而非 `docker compose` 子命令。安装脚本兼容两者。

```bash
cd /data_1/ai-nutritionist-h5
sudo docker-compose ps
sudo docker-compose logs --tail=100 api web
curl -f http://172.16.10.3:18080/api/health

# 配置更新后重新创建容器；前端开关与源码变更需重新构建
sudo env DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 bash deploy/install.sh

# 仅重启应用
sudo docker-compose restart api web
```

数据库初始化模块 `python -m app.bootstrap_db` 仅创建配置中指定的数据库（不存在时），不删除数据库。后端默认仍支持 `APP_DB_ENGINE=sqlite` 用于本地开发。

验收脚本 `deploy/verify_deployment.py` 在 API 容器内经过 Nginx 请求真实服务；`prepare` 阶段创建随机测试账号，`resume` 阶段确认重启持久化并移除本次测试账号和记录，`cleanup` 可单独清理未完成的测试。不得在生产用户账号上执行替代清理操作。

## 已完成验收

- 前端 Vue/TypeScript 与 Vite 生产构建通过；修复原项目的接口类型错误。
- 本地原有 6 项自动测试通过；当前服务器镜像内的 14 项自动测试全部通过。
- 用户电脑访问首页返回 HTTP 200；API 返回 `status=ok`、`demo=false`。
- Edge 浏览器中登录页正常渲染，390px 手机视口无水平溢出，页面、脚本和样式均返回 200，无 JavaScript 异常；匿名用户 `/api/auth/me` 的 401 为预期状态。
- 在真实 MySQL 上验证注册、重复注册 409、登录、中文和 emoji 档案保存、食品初始化、餐食保存与当日营养汇总。
- 经过 Nginx 验证图片上传、鉴权读取和账号隔离；使用空白测试图验证真实视觉模型接口与 JSON 解析，不代表餐食识别准确率评估。
- 验证真实 Qwen 流式咨询完成、回复非空且保存到 MySQL。
- 验证报告生成返回停用状态。
- 重启 API 后，会话、餐食、图片和聊天记录均能继续读取；随后清理验收账号与记录。

未进行 GPU 并发压测；报告按要求未启用。

## 2026-10-16 真实餐食照片识别修复

真实照片暴露了旧识图参数的问题：模型默认启用思考，800 个输出 token 耗尽时返回 `finish_reason=length`、正文 `content=null`，原解析逻辑因此返回 502。现通过 `.env` 配置 `VLLM_VISION_ENABLE_THINKING=false`、`VLLM_VISION_MAX_TOKENS=1536`，让识图直接生成 JSON；后端明确检查截断、空正文和缺失候选，避免把无效结果当作识别成功。重新选择同一张照片也可再次触发上传识别。

使用用户提供的原始餐盘照片，经过 Nginx 的真实上传、图片预处理和识别接口连续验证两次，均返回 200，识别出酸奶、米饭、炒肉片、冬瓜炒鸭血、花生烧鸡块、紫薯共 6 项候选。候选名称和重量仍需人工确认，不代表识别准确率评估。

新增 8 项识图回归测试，包括思考开关、输出预算、截断正文、空正文和空候选响应；服务器共 14 项测试通过。`deploy/verify_food_photo.py` 可在容器内对包含多种食物的真实餐盘图片复测，并清理自己创建的临时账号和上传文件。此次未修改用户已有账号、图片和记录。

## 2026-10-16 能量计算展示说明

能量按下拉框选择的标准食物计算：各项每 100 克能量 × 确认重量 ÷ 100，然后求和；照片识别名称本身不提供成分数据。旧页面未提示未匹配项目不计入，将部分小计标为整餐能量，容易造成修改未匹配项目的重量却不变的误解。

现已增加每项能量公式、未计入原因、已计入项数和“已匹配食物小计”标签；全部项目选好标准食物且重量有效时才显示“本餐估算能量”并允许保存。显示保留至 1 位小数，手动新增不再自动套用食品列表第一项。

已用独立浏览器和模拟餐食数据验证页面交互：米饭 150g 为 174 kcal，加苹果 150g 为 252 kcal；苹果改为 200g 后为 278 kcal，再切换为米饭后为 406 kcal。12 项页面验收通过，包括实时更新、未匹配提示、无效重量校验、完整性保存校验及 390px 手机视口无横向溢出。此次未创建账号或修改用户餐食记录。

## 2026-10-16 食品库与交付流程

基础食品库现有 2054 条，其中 2044 条为模型生成估算、10 条为原有演示数据，覆盖 72 个生成类别。估算数据保留每 100 克口径、烹饪状态、别名、来源模型与批次，`verified=0`。生成原始响应、校验记录及 JSON/CSV 导出保存在服务器 `data/food_catalog/qwen-foods-20261016/`，不提交到 Git。生成与复用方式见 [食品库说明](FOOD_CATALOG.md)。

新增的 PR 检查、服务器主动部署、自动验收与真实回滚演练见 [AI Native 交付说明](AI_NATIVE_DELIVERY.md)。当前食品库版本后端测试为 30 项；交付流程另有独立测试。

## 备份说明

同时备份 MySQL 的 `ai_nutritionist_h5` 库和 `data/media` 图片。配置文件也需保存在受限位置；请勿输出 `.env` 到日志或提交到 Git。当前入口使用内网 HTTP，Cookie 配置为 `APP_COOKIE_SECURE=false`。
