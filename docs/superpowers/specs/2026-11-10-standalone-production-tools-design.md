# 独立产测数据接入设计

用户已确认：暂不关联制造项目，产测独立查询，首期仅平台管理员访问；SAP/MES/WMS 由另一个会话负责。本文件记录该决定，替代原生接入设计中「制造项目映射是查询前提」的部分。底层原生读取及其资源、安全和语义限制继续有效。

## 问题与职责调整

已发布实现把制造项目成员授权、源项目范围与后续业务关联放进同一个 binding；因此即使源连接已验证，启用真实查询仍被制造项目映射阻塞。页面、API、快照和配置都依赖该假设，只删除页面选择或制造一个虚拟项目无法消除耦合。

采用独立的产测源项目范围。平台身份决定用户能否使用产测模块；源数据库项目目录决定可查询的源项目；制造项目关联保留为后续业务能力。首期管理员读取已配置源账号可见的产测项目，普通成员即使有制造项目权限也不能访问。已有制造角色、授权、业务库与 SAP/MES/WMS 集成保持原职责。

## 接口与产品

左侧「产测管理」只向 `configuration_admin=true` 的平台管理员显示；后端对每个请求独立执行同一权限检查，普通成员返回403，匿名由宿主返回401。只读管理员仍可读取。无制造项目的管理员也能查询产测。

页面先加载全局配置状态及产测项目目录，项目名称来自 MySQL `projuectlists`，不创建本平台项目。按源项目、时间、精确 SN、工具/设备及记录类型查询；保留四个页签、日志下载、记录统计和快照。项目列表按 ID 倒序，每页100条，有明确的继续读取按钮，不循环拉取全库。查询换项时清空旧数据并取消/忽略旧响应。

路由继续由既有受保护制造宿主承载，前缀 `/api/v1/manufacturing/workflow/production-tools`，精确九条 GET：

- `/status`：仅报告配置能力，不声称实时连通。
- `/projects`：仅 `before_id` 参数，返回 `items:[{id:string,name:string}]`、`limit:100`、`has_more:boolean`、`next_before_id:string|null`。
- `/projects/{source_project_id}/status`。
- `/projects/{source_project_id}/observations`。
- `/projects/{source_project_id}/catalog/{kind}`。
- `/projects/{source_project_id}/evidence`。
- `/projects/{source_project_id}/evidence/{source_log_id}/content`。
- `/projects/{source_project_id}/statistics`。
- `/projects/{source_project_id}/snapshots/{snapshot_id}`。

源项目/源日志 ID 为1至20位十进制正整数字符串，不能按 JavaScript number 传输。查询参数白名单、重复参数拒绝及既有各类查询字段限制保持。旧 `/projects/{manufacturing_project_id}/production-tools/...` 路径撤除，不实现自动改路或虚拟绑定。

## 原生边界与配置 v2

新增固定的目录 SQL：`SELECT id, name FROM projuectlists WHERE del = 0 ORDER BY id DESC LIMIT %s`、带 `AND id < %s` 的后续页、带 `AND id = %s` 的单项目检查。列表最多读取101条（100加哨兵）；单项最多2条用于验证唯一性。所有语句进入既有精确 SQL 登记，连接与查询限制保持。源不存在返回404，源错误返回明确503，不能返回伪造的成功空列表。

`SourceScope` 只含 `source_namespace`、`source_project_id`、`revision`、`object_prefix`，没有制造 UUID 或制造数据集。`ProductionToolsConfig` 包含 source、source_namespace、revision、object_prefixes、snapshot_path。新的 `ProductionToolsService(config, *, clock)` 不接收 WorkflowStore；其 source 项目目录、查询、快照和日志均按源项目范围执行。源查询和日志下载前校验源项目存在，下载仍从该项目的 MySQL 元数据解析日志。快照读取依赖当前管理员身份与配置指纹，不要求源在线，不能跨源项目续读。

私有配置严格采用版本2：

```json
{
  "version": 2,
  "source_namespace": "orbbec-native-production",
  "revision": "standalone-v2",
  "mysql": {"host":"example.invalid","port":3306,"user":"readonly-example","password":"EXAMPLE-ONLY","database":"example"},
  "questdb": {"host":"example.invalid","port":8812,"user":"readonly-example","password":"EXAMPLE-ONLY","dbname":"qdb"},
  "objects": {"endpoint":"https://example.invalid","bucket":"example","access_key_id":"EXAMPLE-ONLY","access_key_secret":"EXAMPLE-ONLY","allowed_host":"example.invalid"},
  "object_prefixes": {"10001":"logs/10001/"}
}
```

仅配置可用的传输；没有经确认对象前缀的源项目仍能查询记录，但不能下载对象。前缀不能从项目名猜测。禁止 bindings、dataset_id、制造 project_id、未知字段和重复键；命名空间及 revision 为最多96字符的字母数字/下划线/短横线标识。`build_native_config(config_path,snapshot_path)` 为两参数工厂，模块导出 `NATIVE_PRODUCTION_PROTOCOL=2`；宿主显式检查该协议再调用。错误配置只关闭可选产测连接。

## 快照与鉴权

快照库为独立 v2 schema，以产测命名空间、源项目 ID、revision、对象前缀的指纹绑定。元数据不使用制造 demo 数据集；API 返回 `source_namespace`、`source_project_id`，不返回制造 project_id。禁止自动升级、复用或改写旧 v1 快照；当前线上未配置产测且没有待迁移的原生快照。宿主仍验证快照路径不能别名到三类制造库或私有配置。

保留每次捕获1000行/2MiB、分页100、每源项目100份未过期快照、24小时过期与有界清理、源错误不伪装为空、既有精度/截断游标/半开时间区间规则。管理员身份按宿主每次请求解析；被降权后的新请求包括快照和下载都被拒绝，查询没有放开普通项目成员权限。所有响应保持 `private, no-store`。

## 验证与交付

以测试先行验证：零制造项目管理员读取源目录和记录；普通制造项目成员零源I/O；匿名401；跨源项目快照404；新请求管理员降权后快照和下载403；配置revision变化失效；源项目目录分页/删除/错误/超界ID；日志前缀与大小限制；切换筛选清除过时响应。保留已有底层精度、SQL只读、截断、日志与过期回归。

真实验证直接使用已有私有连接资料，先有限 SELECT 确认目录和记录，再经过宿主 HTTP 验证。测试身份、生产管理员身份及浏览器验收分别记录。无源系统写入、旧平台业务 API、业务事实自动投影、制造 schema24 迁移或 demo 数据删除。源读取结果不会自动生成测试单、质量放行、库存、工单完工等事实。

功能先在隔离 MF/PF 分支实现、审查并归并主线；发布按已有不可变导出、真实镜像、九条路由白名单、候选验收、数据保留与生产连接验证执行。历史发布记录保持原样，新记录明确已启用/未启用能力。不得改另一会话的 SAP/MES/WMS 适配器、集成路由或用户资料。
