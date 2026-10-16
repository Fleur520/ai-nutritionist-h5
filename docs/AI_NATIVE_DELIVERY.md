# AI Native 最小交付闭环

## 提交与自动检查

Agent 在独立分支修改代码并创建 Pull Request。仓库的 `.github/workflows/ci.yml` 在 PR 和 main 更新时运行：

1. Python 3.12 安装锁定依赖，运行 SQLite 与 MySQL 5.7 后端测试；MySQL 使用临时 `test_nutrition_ci` 库。
2. 运行发布、回滚与下载解包检查。
3. Node 24 使用 `npm ci` 安装锁定依赖，执行 Vue/TypeScript 和 Vite 生产构建。
4. 构建 API 与 Web 两个 Docker 镜像。
5. 上传测试结果，保留 14 天。

依赖更新后必须同步更新锁文件。CI 数据库密码仅用于一次性容器；服务器密码不进入 GitHub。

## 合并后的部署

172.16.10.3 无需向公网开放 SSH。服务器上的 `nutrition-delivery.service` 每 300 秒主动读取公开仓库 main 和指定 `ci.yml` 的结果。只有同一完整提交 SHA、main 分支、push 事件的成功检查才能触发部署；PR 检查本身不会触发部署。

控制程序固定安装在 `/data_1/ai-nutritionist-h5/.delivery/bin/`，配置为 `.delivery/controller.json`。它下载精确提交，使用不可变的本地镜像标签构建新版本，再启动容器。运行时配置始终来自服务器 `.env`，食物库和用户数据使用原持久化目录。首次发布会保存当前容器镜像作为回滚基线。

验收经过 Nginx 检查首页、健康状态、完整版本 SHA、注册登录、食物列表、餐食保存、能量汇总和真实模型流式回复。验收使用随机临时账号，结束后只清理该账号的数据。全部通过才更新 `active.json`。

构建失败保持当前服务；切换后的验收失败自动恢复上一组 API/Web 镜像并再次验收。失败 SHA 暂停重试，防止持续切换；修复后提交新 SHA 即可重新进入流程。每次发布记录位于 `.delivery/reports/<SHA>.json`，详细构建日志位于 `.delivery/deployment.log`。

## 运维与边界

```bash
sudo systemctl status nutrition-delivery
sudo journalctl -u nutrition-delivery --since today
sudo cat /data_1/ai-nutritionist-h5/.delivery/controller-status.json
curl -f http://172.16.10.3:18080/api/version
```

修改服务器 `.env` 后需重新发布对应配置。控制程序或服务文件的修改需单独安装，应用更新不会自动替换正在执行的控制程序。

本流程回滚应用镜像，不回滚业务数据库。当前初始化仅新增表、索引或基础数据；未来涉及不兼容的数据库变更时，应先设计兼容迁移并备份。自动验收验证可用性，不代表食物识别准确率或营养建议的医学有效性。模型生成的食品数据仍标注为估算，未标记为权威验证数据。

GitHub 检查记录、PR 与服务器发布记录是验收依据。只有实际合并后，通过 main 检查并成功部署，才算完成一次真实的合并交付。

## 2026-10-16 独立环境演练

在同一服务器的独立 Compose 项目 `ai-nutritionist-delivery-test`、回环地址 `127.0.0.1:18081`、独立 SQLite 数据目录演练，未连接业务 MySQL：

- 完整构建 API/Web 镜像并发布测试版本，8 项验收通过，包括临时账号清理。
- 给下一版本注入必定失败的验收脚本，真实启动容器后触发回滚。
- 发布报告为 `rolled-back`；恢复前一组镜像后再次通过验收，HTTP `/api/version` 返回前一测试版本。

演练使用重复字符组成的测试版本标识，不是 Git 提交。报告保存在服务器 `.delivery/rollback-lab/.delivery/reports/`。真实模型通过主站此前的功能验收验证；本次独立回滚演练未调用模型。
