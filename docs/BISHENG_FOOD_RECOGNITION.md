# BiSheng 餐食图片识别与食品知识库

餐食识别和健康报告使用独立工作流与配置。启用本功能不会启用健康报告，普通营养咨询仍直接调用现有模型。

## 数据与流程

```mermaid
flowchart LR
 H[H5 上传私有餐食图片] --> A[FastAPI 鉴权]
 A --> I[BiSheng 图片输入]
 I --> V[视觉模型识别菜品与分量]
 V --> K[食品 QA 知识库检索多个候选]
 K --> M[匹配候选编码并保留检索证据]
 M --> D[FastAPI 核对当前食品数据库]
 D --> H
```

知识库只含食品成分表，不导出账号、饮食记录、健康档案或用户图片。每条 QA 答案保留食品编码、每 100 克营养值、做法、别名、来源、模型和批次，以及快照和记录摘要。模型生成的数据始终保留 `source_type=ai_estimate`、`verified=0`，不能作为实验核验数据。

工作流最多识别 8 项食物，分量范围为 5～3000 克。检索相关度仅用于召回；模型不能编造食品编码。服务端还会按当前数据库复核名称、别名、生熟及烹调状态。存在歧义、做法冲突或候选已失效时留空，让用户选择。旧演示数据名称中的“（熟）”仅可用作通用熟食参考，不修改其来源或原有数据。

H5 通过数据库食品编码回显名称、做法和每 100 克热量，按 `数据库 kcal × 重量 / 100` 计算。保存时后端再次读取数据库计算，不采用模型输出的热量。

## 已部署资源

| 资源 | 值 |
|---|---|
| BiSheng 管理平台 | `https://172.16.10.4:3001/build/apps` |
| 食品知识库 | `食光食品营养库-数据库快照`，ID `200` |
| 食品数量 | 2054 条，初次导入已全部完成索引 |
| 图片工作流 | `食光餐食识别与食品热量检索` |
| 工作流 ID | `7494d578a3a34513a31a84ebdeb80335` |
| 视觉及匹配模型 | 现有 `Qwen3.8-27B`，模型 ID `43` |
| 向量模型 | 现有 `Qwen3-Embedding-8B`，模型 ID `31` |

这些标识不含密钥。重新部署时复用已有资源，避免重复建库或重复导入。

## 服务端配置

配置保存在服务器 `/data_1/ai-nutritionist-h5/.env`，权限为 600，不提交 Git：

```dotenv
FOOD_RECOGNITION_PROVIDER=bisheng
BISHENG_RECOGNITION_BASE_URL=http://172.16.10.4:7860
BISHENG_RECOGNITION_WORKFLOW_ID=7494d578a3a34513a31a84ebdeb80335
BISHENG_RECOGNITION_API_KEY=
BISHENG_RECOGNITION_INPUT_FIELD=input
BISHENG_RECOGNITION_IMAGE_KEY=meal_image
BISHENG_RECOGNITION_TIMEOUT=240
```

内置开放接口通过平台的默认操作人执行。仅在前面配置了鉴权网关时填写 API Key，不把管理员登录会话写入应用配置。API 容器必须能访问 BiSheng 7860 端口。图片会传至该内网 BiSheng 服务，应按其上传文件保留策略管理。

调用先获取 `input` 事件，再用同一 `session_id`、`message_id` 和嵌套输入 `{input_meal: {meal_image: [上传返回路径]}}` 继续。此实例实测外层字段为 `input`；部分 OpenAPI 展示的 Python 字段名 `user_input` 不适用于该实例。配置错误或工作流失败返回明确错误，不静默切回直接模型识别。

## 更新知识库与工作流

在 API 的运行环境执行只读导出，输出目录须在 Git 忽略范围内：

```bash
python -m app.knowledge_export --output /data/export/food-knowledge
```

导出生成 `qa_records.jsonl`、`food_documents.jsonl`、`food_catalog.txt` 和 `manifest.json`。QA 导入文件使用“问题”和“答案”两列，答案保留导出 JSON 原文。先完成新快照索引，核对数量、失败记录和摘要，再更新工作流快照；不要对同一知识库反复追加相同导出。

`deploy/bisheng_food_workflow.py` 根据知识库、模型与快照标识生成原生工作流定义，不连接服务器、不自动创建资源：

```bash
python deploy/bisheng_food_workflow.py --help
```

工作流的代码检索节点读取该食品 QA 向量库真实答案，召回多个候选并校验记录摘要及快照；未识别到食物时不检索空查询。当前检索实现依赖 BiSheng v1.3.1 的向量库接口，升级平台前需重新验证。

原始 QA 答案保留在知识库及工作流证据步骤。最终接口只返回食物身份、候选编码和证据摘要，避免将完整食品记录重复写入 BiSheng 的 `chatmessage.message` 文本字段；应用从当前数据库读取营养与来源。生成器测试覆盖整餐 8 项、每项 8 候选的输出容量。

## 验收与限制

验收应覆盖真实餐食图片、无食物图片、服务异常，以及食品编码回显、重量调整后的热量变化。数据库测试必须使用独立的 `test_` 数据库。只有合并提交的 `ci.yml` 通过后才允许部署；部署验收失败恢复上一版镜像。

图片无法可靠判断配方、用油和实际重量；未匹配的项目需要手工确认。食品库主要为未核验的 AI 估算，索引完整不代表营养值经过实验验证。数据库后续修改不会自动同步到 BiSheng，需按上述流程重新导出并验收。
