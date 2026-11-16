# 真实MES工单到物料工作台

用户在[线上空数据排查](../../reviews/2026-11-16-online-data-ingestion-audit.md)后明确要求“开始吧”。本设计落实已批准的修复顺序：MES/WMS只读装配、无需第二本台账的源工单浏览、主业务入口展示真实读取，以及准确来源关联。SAP测试读取继续保留独立身份。本轮交付源工单、组件、源优先级和相关IQC的实际可用旅程，不声称已取得正式生产项目归属、分配库存或线边实收。

## 实际依据与选型

本Mac持有启用的生产MES v2只读配置，固定生产域名和受控路径；Mac可达。云服务器不能解析该MES域名。沿用SAP已验证的Mac固定只读RPC＋SSH反向Unix socket方式；不提供TCP/SOCKS代理，不把MES密码送云。云端直接访问缺网络条件；预灌一批快照不能替代按需查询，均不采用。

已有页面JS明确用customCommon query读取M_SHOP_ORDER的SHOP_ORDER和ORDER_DESC，传固定SELECT及params绑定，响应result.MSTATUS/MSG/DATA。历史字典将SITE+SHOP_ORDER标为业务唯一键。新增代码所有的固定查询，在内层按SHOP_ORDER排序、绑定SITE/前缀/after，外层ROWNUM最多5。调用者不能提供SQL、列、表、路径或绑定SITE。只证明工单身份和说明，不填未取得的数量、状态或项目。

工单号重复、跨游标倒退或输入范围不符应拒绝，不静默覆盖。5行满页仅表示可继续请求，下一页为空仍是合法结果，不伪造总数或事务快照。SOURCE是MES生产、站点和稳定namespace；内部SITE与站点码不混用。

## 用户旅程

- 工作台和“工单与执行”可直接浏览/搜索MES源工单。平台工单、项目均为0时仍能读取；正式平台登记与办理保持独立入口，不生成虚拟项目或工单。
- 选择源工单进入“计划与物料”的同一源上下文，查看完整有界组件、需求量、已提量及单位；源优先级/缺口与相关IQC可按组件查看及分页。沿用已有100组件/20页完整采集上限，失败不显示不完整集合为全量。
- 相关IQC只表明该物料的原始检验记录，不据相同物料自动关联本工单/批次，也不计入本单合格可用量。MES已提不等于物流领取或线边实收。缺少的发料/实收链路不制造数据。
- SAP测试浏览仍独立，不按同号/同物料自动与生产MES拼成齐套。不得将观察静默写成正式需求、库存、质量、预留或MRP执行。
- 遵循现有原生SAP全局浏览的权限边界：首期全站点源浏览仅配置管理员且目录身份有效；不放宽项目成员到任意源工单。只读平台身份可读已有观察，刷新须现有可编辑授权/CSRF。员工浏览器验收仍由用户负责。

## 原生MES服务接口

MesAccessService新增read_context()，仅本地配置读取，返回`{source,fingerprint}`；source精确字段为`system=mes, origin=native, fact_role=observation, environment, site_code, namespace`。namespace沿用现有MES规范化来源函数；不得含密码、URL或Cookie。

新增source_orders(prefix, after, actor_id, *, expected_fingerprint=None)，返回`{source,fingerprint,items:[{shop_order,description}],next_cursor,total:null,page_size:5,request_id}`。prefix/after均最长64，去拒控制字符/注入字符；前缀通配符不接受，使用绑定参数；after严格keyset。只读调用前后核对原生指纹。

collect_order_materials(shop_order,actor_id)保留现有返回与完整性。query仅继续使用已审核的order_materials/material_priority/iqc_inspections等固定原生接口；不开放通用路径。新目录profile使用同一已允许customCommon路径，不能扩大SQL能力。

## Mac只读MES中转

独立MES令牌、配置、ready、审计和LaunchAgents；SAP服务不切换。监听仅127.0.0.1。RPC精确请求字段与SAP一致：`{version:1,request_id:<uuid>,operation,actor_hash:<64hex>,expected_fingerprint:<64hex|null>,scope}`；响应`{version,request_id,context,result,error}`，禁止额外字段、重复键、NaN、任意函数/URL。

允许操作仅describe、source_orders、order_materials、material_priority、iqc_inspections；后两者只接受精确工单+物料或精确物料及页码/最多5行。describe不访问MES网络。其余操作必须原生配置指纹一致。请求2048字节、响应2MiB，最多4个并发源操作；原生业务调用在独立子进程硬截止65秒，云worker截止70秒，超时不重试，进程退出不继续翻页。认证先于源配置与网络。安全错误码、意图/结果审计，无原始HTTP访问日志。

云端mes_access工厂改为无I/O的selector，支持原生v2配置与精确v1 mac_read_relay配置。云配置仅含version/transport/enabled/read_only/environment/socket_path/token_path/expected_context/timeout_seconds/max_response_bytes；不含MES凭据或URL。云binding由配置及令牌派生，native fingerprint另行钉定，禁止混用。read_context/configuration_matches只读本地文件，不能在SQLite事务里联网。结果验证operation、UUID、来源、作用域和有界native-shaped内容；错误或原文不得公开。

共享Unix HTTP worker可复用；SSH supervisor以静态MES profile复用已验证的生命周期逻辑，默认SAP行为不变。MES profile固定目录`/data/orbbec-agent-platform/manufacturing/data/mes-relay/bridge`，禁止任意目录。SSH维持-F none、显式身份/known_hosts、无其他转发；每会话唯一socket、authenticated describe后切换active.sock，仅清理己方实例。MES source context验证不能放宽SAP配置/上下文校验。

## 平台观察与HTTP

新增mes_source_observations表，沿用SAP观察的配置指纹＋kind＋精确scope＋refresh_seq接纳模式，失败保留成功快照及原时间；不改正式projects/work_orders/requirements。配置切换不继承其他来源缓存，来源网络I/O在数据库事务外；最终写锁内只做本地指纹核对。

固定前缀`/api/v1/manufacturing/workflow/material-control/mes-source`，9项精确路由：GET status；GET/POST orders、order-materials、priority、iqc。status本地返回configured/source/can_refresh及安全错误。GET只读已存观察；POST读取源并保存本地观察，拒绝请求体及额外/重复参数。orders scope={prefix,after}，order-materials={shop_order}，priority={shop_order,material,page}，iqc={material,page}，每页最多5。统一响应`{snapshot:null|{id,kind,scope,source,collected_at,data},refresh_error:null|{code,message}}`。

首次页面加载先读status/cache，在有刷新权限且从未读取时主动执行一次固定查询；不循环重试。已存在缓存时先展示时间，刷新明确触发。真实空、未查询、失败、未取全分别显示。前端跨工单/物料/配置/账号的异步结果必须隔离，不串单。

主页显示现场源工单卡片；工单页和物料页默认源浏览入口，有权用户不必进入本地项目。保留原正式台账办理为次级模式。不要把源页“已加载5条”改写成全站总工单数或正式项目数；错误不会静默当0。

## 发布与验收

生产源只读AGENTS规则持续有效；本轮只源查询、平台本地缓存和已有授权协同，无生产源业务写入。凭据/业务原始证据仅私有600/700。保留根用户三处修改。共享Nginx/SSH daemon和其他容器不改。

云复用现有数据bind，mes-relay目录UID10001/700、config/token/audit为600、bridge root:10001/750、socket660。受控发布仅新增两项MES config/audit环境变量，保留SAP及产测配置和既有挂载。release_guard显式校验MES私有配置/来源/令牌与桥接元数据并钉定散列，不能通过通用env透传。

分支评审后归并两仓主线并推送；按现有API-only流程捕获动态Compose全部输入、精确overlay、运行Linux37项/OEM候选与schema29→30副本迁移保全，再受控切换。schema前进后采用现有向前修复策略，不能恢复旧库覆盖后续记录。

真实验收必须从云UID10001及实际宿主HTTP路由验证：零平台项目下列表两页及去重→真实组件完整读取→相关优先级/IQC→私有审计关联→停止己方MES隧道后保留快照/原时间并明确离线→恢复后新读取成功。独立测试身份/库不得冒充员工验收，不靠填样例或直接入库制造页面成功。最后核对实际线上配置、来源和业务页数据API；未完成部分明确报告。
