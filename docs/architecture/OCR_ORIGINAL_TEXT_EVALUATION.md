# 原图文字反馈的只读评估消费

`original_text_feedback` 的 `visual_transcription` 标签由原消费保存/更正事务产生。G3 的首个下游消费者是本机 Owner 评估读取：它比较已核验区域的原文与已有 OCR 预测，不训练模型、不排序候选、不写入财务事实。

## 调用与固定样本

`GET /owner/learning-maintenance/original-text-evaluation`

参数为明确的 `ledger_id`、`actor_account_id` 和重复参数 `event_public_id`（每次 1–50 个不同 ID）。Owner 原有 loopback 与可管理账本边界继续适用，反馈按账本和本人隔离。批量调用时保留调用前冻结的完整 ID 清单，各批次不得重复或丢掉未评分项。

每次读取都经过原有 `feedback_assessments`，重新检查资格、来源、当前替代关系、撤回和版本隔离。失效或不属于所选范围的 ID 仍返回一行并计入 `cohort_count`；不返回其原文或标签摘要。恢复版本消费后可用同一组 ID 重评。已导出的旧报告是当时快照，不能绕过当前撤回或隔离成为新的学习输入。

## 评分与出处

- 标签必须是 `original-pixel-feedback-v1` 的 `visual_transcription`，同时核验精确区域和原文。未知版本、诊断反馈、点选和未核验区域不能充当文字标签。
- 每次消费重新读取原件并验证 SHA-256；沿用产品 `read_ocr_facts` 的最新非空预测选择和 `original_text_lines` 的原图尺寸、坐标、文字块一致性检查。旧文字或字段候选不能补造缺失的像素证据。
- 只连接完整落在核验区域内的 OCR 行，保持原预测顺序。与边界部分相交的行返回 `partial_line`，不猜测应裁掉哪些字符；有可比像素预测但区域内没有文字时，空预测按漏识别计为不匹配。
- `original-text-evaluation-v1` 仅统一 Unicode NFC、CRLF 换行及首尾空白。大小写、标点和内部空白差异继续保留。当前指标为区域文字 exact match，**不称为字段金额准确率、字符错误率、候选排序收益或真人复核时间**。
- 响应保留固定 cohort 摘要、全部行数、资格分布、可评分数、匹配数，以及每个可比样本的反馈修订、原图 SHA、OCR fact ID/provider、evidence 摘要和规范化文字摘要/字符数。响应不返回原图、原文或财务值，禁止缓存。

比较必须同时报告 `cohort_count`、`qualified_count`、`scored_count` 和 `exact_match_count`，以及不评分原因；不能通过撤回、隔离或减少区域覆盖来提高准确率分母。候选排序、解析字段和文字识别是不同指标，仍由各自冻结基准评估。没有新权重或解析算法变更，也不对最终 holdout 调参。

## 责任与回退

事件/版本/撤回和财务提交沿用原 owner。新增评估服务与 Owner GET 路由仅消费现有数据；没有新表、迁移、队列、标签 writer 或公开网络端点。回退本片只撤下读取路由和评估服务，已有反馈、原件、预测和财务事实保持原样。

`test_original_text_evaluation.py` 通过实际保存 API、PostgreSQL 和 Owner GET 覆盖文字错误/正确、固定分母、撤回、隔离、替代、原件替换/移除/字节损坏、跨账本/操作人、部分行弃权、旧版本/缺像素证据与远程拒绝。真实材料效果、消费者安装包资格及最终主干门禁另按实际执行结果记录，不以这些合成反例冒充识别收益。
