# 0016 性能与稳定性基线

## 状态

已采纳。

## 背景

小票夹进入真机联调后，性能瓶颈不在复杂计算，而在几个会随数据量线性放大的路径：

- 后端已确认账单分页、月份筛选、分类筛选和统计不能整表拉回 Python 后再处理。
- Android 每次请求不能重复创建 Retrofit 和 OkHttpClient，否则连接池和对象缓存无法复用。
- Room confirmed 同步不能每笔账单一次查询再一次写入。
- 待确认截图缩略图不能完全串行加载，也不能每张图更新一次 UI 状态导致列表频繁重组。

## 决策

后端：

- confirmed 查询必须在 SQL 层完成筛选、排序、分页和 count。
- 月度统计必须在 SQL 层按月份和分类聚合，再在服务层做少量分类归一。
- SQLite schema 迁移必须为常用查询字段创建索引。
- 不引入额外数据库或后台任务框架，继续保持 Windows 本地 SQLite 部署简单。

Android：

- Repository 复用绑定后的 ApiService，避免每个接口调用重新创建 Retrofit 和 OkHttpClient。
- GET 请求允许对 502、503、504 做一次透明重试，用于缓解 Cloudflare 或瞬时网络抖动。
- Room confirmed 同步先批量查询已有 serverId，再批量 insert/update。
- 待确认缩略图使用有限并发加载，并批量合并 UI 状态。

## 不允许回退

- 不允许把后端 confirmed 分页和统计改回 Python 整表过滤。
- 不允许每次 Repository 调用都重新创建 Retrofit/OkHttpClient。
- 不允许 confirmed 同步回到逐条 SELECT + 写入。
- 不允许待确认缩略图无限并发或完全串行加载。

