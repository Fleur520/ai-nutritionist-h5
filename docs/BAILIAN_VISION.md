# 百炼 Qwen3.7-Flash 食品识图

使用现有 direct 识图适配器。无需部署本地 GPU 或 BiSheng，不增加运行依赖。
显式选择 `bailian` 请求风格，按官方 OpenAI 兼容协议把 `enable_thinking=false`
放在 JSON 顶层；原有 vLLM 的嵌套参数保持默认。

## 开通和保存密钥

1. 登录 https://bailian.console.aliyun.com/ 并按控制台要求开通模型服务。
2. 选择地域、业务空间，创建该地域的 API Key，确认可调用 `qwen3.7-flash`。
3. 从控制台复制对应的 OpenAI 兼容 API 地址。Key、地域和业务空间须匹配。
4. 密钥只保存在运行环境的受限 `.env` 中，不放入前端、Git、截图或聊天。
   云端配置界面可由用户本人输入环境变量或限定目标域名的 HTTP 密钥；
   HTTP 密钥必须确认代理能替换 Authorization 中的占位值后才能使用。

创建指引：https://help.aliyun.com/zh/model-studio/get-api-key

## 服务端配置

以下是北京地域工作空间地址示例，替换真实业务空间 ID。
其他地域请使用控制台提供的地址，不要仅替换模型名或复用其他地域的 Key。

```dotenv
DEMO_MODE=false
FOOD_RECOGNITION_PROVIDER=direct
VLLM_VISION_API_STYLE=bailian
VLLM_VISION_URL=https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions
VLLM_VISION_MODEL=qwen3.7-flash
VLLM_VISION_API_KEY=
VLLM_VISION_ENABLE_THINKING=false
VLLM_VISION_MAX_TOKENS=1536
```

`VLLM_VISION_API_KEY` 由运维或用户在服务端填写真实值。没有 Key 时不切换运行中的演示服务。
`DEMO_MODE=true` 会返回固定演示食物，不能用来验收真实模型。
关闭全局演示模式也会让文字咨询与报告退出演示；它们需各自配置服务，
仅有上述视觉配置时不要宣称文字咨询或报告也已接通。
报告无独立服务时设置 `APP_REPORTS_ENABLED=false`、前端构建 `VITE_REPORTS_ENABLED=false`。

修改后重启 API。云环境须在官方网络设置中允许实际工作空间 API 主机；
出站域名放行不等于已配置密钥。不要修改原服务器的数据库、图片目录和其他服务配置。

## 验证

先运行项目后端回归测试（包括模拟百炼响应的适配器测试），再在已配置 Key 的环境中
用合成或用户明确授权的餐图通过 `/api/images` 上传和 `/api/meals/recognize` 验证。
真实请求按百炼账单计费；没有真实餐图调用结果时只能称为“协议接入已完成”。

返回的模型营养值仍按每100克存储，保留做法、模型来源，
使用 `source_type=ai_estimate`、`verified=false`，不会升级成已核验食品成分。
识图份量是估算，用户确认后再按实际克重换算；食品库匹配和保存凭据继续走原有链路。

协议参考：https://help.aliyun.com/zh/model-studio/vision
