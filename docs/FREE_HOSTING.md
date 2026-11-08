# 免费固定地址：Render + TiDB Cloud Free

目标是保留现有 Python 服务与 MySQL 协议，用免费额度提供固定 HTTPS 地址。
Render 服务与 TiDB Free 实例都不启用付费套餐、不增加信用卡或付费扩容。
百炼模型调用仍按用户原百炼账户计费，托管免费不代表模型调用免费。

## 已核实的限制

- Render Free 在15分钟无流量后休眠，再次访问约需一分钟唤醒。
  免费实例本地文件会在重启/部署/休眠后丢失，因此不能用它保存 SQLite 与用户照片。
- TiDB Cloud Starter 必须选择 **Free instance**，不选 Scalable，不开启非零 Spending Limit。
  每个符合条件的 Free 实例有5GiB行存储、5GiB列存储及每月5000万 RU。
  免费额度用尽后限流，等待重置，不启用付费扩容。
- 这是受平台条款、额度与账户状态约束的固定地址，不能承诺永久不变或全天候在线。

官方资料：
- https://render.com/docs/free
- https://render.com/docs/web-services
- https://www.pingcap.com/tidb-cloud-starter-pricing-details/

## 部署

1. 登录 Render 和 TiDB Cloud，创建一个 TiDB **Free** MySQL-compatible 实例。
2. 用根目录 `render.yaml` 创建 Render **Free** Web Service，根目录 Dockerfile 构建前后端。
3. 在平台受限环境配置中填写 MySQL 主机、用户名、密码及百炼接口与密钥。
   `MYSQL_SSL_ENABLED=true` 验证证书和主机名；不关闭 TLS 验证。
4. 数据库名使用 `nutrition_app`，启动只创建这个配置指定的数据库与缺失表。
5. 默认 `APP_IMAGE_STORAGE=database`，处理后的餐图与图片元数据原子保存到数据库。
   本地文件仅为识别缓存，丢失时可恢复；图片仍验证登录和所有权，不公开成静态文件。
6. 前端由 FastAPI 同源提供，`APP_NGINX_ACCEL=false`。直接 SSE，不再依赖临时隧道。
   可选预填账号通过明确的 VITE_DEFAULT_LOGIN_* 构建参数提供；只用于公开的共享体验账号。
7. 必须先合并到 main 且 `ci.yml` 通过。Render 的自动部署设为 After CI Checks Pass。
   候选镜像先只监听 loopback，通过 hosted_acceptance 后才绑定公开端口。
   失败退出，让平台保留上一正常部署；首次部署失败则不发布可用版本。

每次启动验收前端、版本、登录、记餐、汇总和照片在缓存丢失后的回读。
每个版本及模型配置的首次验收调用一次文字和一次视觉接口，之后休眠唤醒复用数据库中的验收凭据，
避免每次唤醒重复消耗百炼额度。验收只清理自己创建的临时账号和记录。

## 原数据迁移

保留旧云实例直到新服务验收与迁移完成。不要以空数据库替代旧数据并宣称迁移完成。
需要迁移旧数据库所有用户、会话、餐食、识别收据、估算来源、聊天和图片。
图片写入 image_payloads 后把对应 images.path 改为 db:<image_id>，逐张校验内容散列。
迁移文件、数据库、照片和服务密钥不得提交 Git。先备份、核对源/目标记录数与图片散列；
目标已有数据时必须先报告冲突，不能清空或覆盖。

本次免费方案不使用现有 101.42.140.70 服务器，也不修改其现有网站和证书。
