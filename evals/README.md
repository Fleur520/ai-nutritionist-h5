# Ragas / DeepEval 离线评测

评测已捕获的回答与检索片段，不连接应用数据库、不调用线上业务接口。
依赖与运行服务分离，推荐 Python 3.11/3.12 独立虚拟环境：

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv/Scripts/Activate.ps1
python -m pip install -r evals/requirements.txt
python -m evals.run --dataset evals/examples/nutrition.jsonl --validate-only
```

在仓库根目录运行。配置通过进程环境变量传入；密钥留在服务器 `.env`，
本工具不会自动读取应用 `.env` 或继承业务模型配置。部署脚本无需改动。

```bash
export EVAL_JUDGE_BASE_URL=http://your-vllm-host:8000/v1
export EVAL_JUDGE_MODEL=your-served-model-name
export EVAL_JUDGE_API_KEY=your-key
python -m evals.run --dataset evals/examples/nutrition.jsonl --framework both --threshold 0.7
```

PowerShell 使用 `$env:EVAL_JUDGE_MODEL='your-served-model-name'` 等方式赋值。
无鉴权的内网 vLLM 可不设置 API key；模型需支持 JSON 对象输出。
评测会向指定 judge 发送样本内容。建议使用独立 judge 模型，避免与被测模型相同导致自评偏差。

## 数据与指标

JSONL 每行一个对象，字段如下（examples 中全是合成数据）：

| 字段 | 含义 |
| --- | --- |
| `id` | 唯一、非空样本编号 |
| `user_input` | 用户问题或识别任务描述 |
| `response` | 被测系统的实际文本回答 |
| `retrieved_contexts` | 实际检索到的原文片段列表，无检索时为 `[]` |
| `reference` | 可选的人工审核参考答案，用于召回评测 |

普通咨询未使用 RAG，建议 `--framework deepeval`，只运行回答相关性。
BiSheng 检索任务需要在本地准备对应的实际检索原文；应用当前保留的编码、来源 ID
不能代替原文，工具也不会自动提取生产记录。报告可将实际传入的统计摘要作为依据。
不要将参考答案伪装成检索片段。图片识别准确率、重量和营养数值误差仍需专门基准，
本工具只评估文本与依据的一致性。

| 框架 / 指标 | 所需字段 |
| --- | --- |
| Ragas Faithfulness | 问题、回答、非空检索原文 |
| Ragas ContextRecall | 问题、人工参考、非空检索原文 |
| DeepEval AnswerRelevancy | 问题、回答 |
| DeepEval Faithfulness | 问题、回答、非空检索原文 |

缺少上下文/参考时相应指标记录 `skipped`。某样本在某框架下没有任何适用指标则失败，
纯咨询示例在 `evals/examples/chat.jsonl`，请使用 `--framework deepeval`；混合数据推荐分别运行。
每项已运行指标均需达到阈值，默认 0.7，仅为初始工程阈值，需以人工标注校准。
分数不能代替医学安全评审，也不表示食品成分已经验证。

输出默认为已忽略的 `test-results/ai-eval.json`，只保留样本 ID、分数、跳过原因、
错误类型、judge 名称与 SDK 版本，不保存问题、回答、检索原文或密钥。
退出码：0 通过（或仅数据校验成功），1 指标未通过/评测错误，2 配置/输入/依赖错误。
每样本每框架默认超时 180 秒，可通过 `--timeout` 调整。

Ragas/DeepEval 遥测在导入前关闭；使用 standalone metric API，不调用云端上传接口。
脱敏样本可放在 `.delivery/`，报告放在 `test-results/`，均被 Git 忽略。
不要提交真实用户健康数据、图片、审计导出或模型生成的食品库。

## 验证

```bash
python -m unittest discover -s evals/tests -v
```

默认 CI 运行无模型的校验与回归测试，不使用密钥、不产生 judge 费用。
真实评测手动运行；本次接入不修改部署验收或上线门槛。

API 参考：[Ragas Faithfulness](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/faithfulness/)、
[DeepEval Answer Relevancy](https://deepeval.com/docs/metrics-answer-relevancy)。
