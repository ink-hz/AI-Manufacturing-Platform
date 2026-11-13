# Mac只读SAP测试中转

用户已认可“云平台→加密反向隧道→Mac只读连接器→SAP测试环境”，并明确要求开始。目标是让已开发的工单→组件→MRP查询能在线上使用。SAP凭据留Mac；生产源只读规则不变，不开放任意内网代理、URL或RFC函数。

## 结构

Mac以固定环回HTTP服务提供 `/v1/read`，只接受带共享随机令牌的固定JSON命令 `describe`、`production_order`、`stock_requirements`。调用现有SapAccessService及固定请求/解析/500组件、50MRP条数上限，不产生源业务写入。账号、目标和SOAP字段均来自Mac私有配置。不存在上传SOAP、SQL、路径、函数名或目标地址的入口。

Mac主动向现有云服务器建立SSH反向Unix socket转发，远端每次使用独立socket，认证探测通过后原子切换active.sock。API通过现有私有数据挂载访问socket目录和自身relay配置，按现有UID10001权限连接，不新增挂载。所有监听均为Mac127.0.0.1或云Unix socket；不改共享Nginx/SSH服务配置，不开放公网端口。认证令牌是独立中转令牌，不是SAP密码。

云端增加延迟选择的SAP服务工厂：原有soap_http保持兼容；mac_read_relay使用独立严格配置与Unix socket客户端。构造服务不读文件或联网。read_context/configuration_matches只访问本地受控配置，禁止在workflow数据库事务里触发远端网络。

## 固定来源

部署时describe取得Mac真实source（system/origin/fact_role/environment/system_id/client/namespace）和原生配置指纹，钉定到云私有配置。每次查询都携带expected_fingerprint，Mac在原生调用前后核对，云客户端核对响应request_id、context及作用域。Mac源配置变化需重新受控登记，不能悄悄接受另一个系统或环境。

云read_context的fingerprint由本地relay配置及令牌派生；它与Mac原生fingerprint区分，云workflow传入的期望首先约束实际使用的云连接配置。随后RPC携带固定的Mac原生fingerprint。source namespace仍使用真实SAP身份，不把Mac或云socket当成SAP系统。

已接纳观察沿用现有模型：最终DB写锁内的本地配置核对为接纳点，之后不做追溯撤销。中转离线不妨碍GET已保存的观察；POST失败明确提示Mac连接状态，保留成功快照和原时间，不回落mock。

## 协议与界限

请求精确字段：`{version:1,request_id:<uuid>,operation:<enum>,actor_hash:<64hex>,expected_fingerprint:<64hex|null>,scope:<object>}`。describe的scope={}、expected_fingerprint=null；两查询必须提供指纹，scope分别{number,plant}及{material,plant}。工单使用原生1–12位数字规范化；物料和工厂复用现有输入校验。

响应精确字段：`{version:1,request_id,context:{source,fingerprint}|null,result:<object>|null,error:{code}|null}`。成功describe的result={}，context来自真实原生服务。查询result为已有原生结果，error仅固定安全码，不带异常原文、凭据或回显令牌。上下文必须完全匹配部署登记值。

认证先于JSON解析和源配置读取；重复字段、额外字段、NaN、错误类型、任意URL/函数/方法均拒绝。请求上限2048字节，响应上限2MiB，最多4个并发源查询；客户端独立子进程提供70秒硬期限，body与headers有界。服务仅本机监听，HTTP原始访问日志关闭；私有云审计与Mac原生审计通过请求关联，不保存业务原文。框架不重试源查询。

## 进程与上线

Mac使用当前用户LaunchAgent管理连接器与隧道，服务文件和固定代码放受控目录；仅进程存活期间抑制空闲睡眠，不改系统电源设置。断网由隧道监督器重新建立连接，重新连接不重放业务请求。退出时只清理本实例socket，不能删新实例或其他服务。

发布前先验证真实云→Mac→SAP查询、容器UID10001访问及停机失败行为，再按现有API-only发布流程捕获完整Compose输入/挂载/静态资源/其他容器，运行隔离Linux候选验收、schema29迁移及向前兼容回滚检查。共享Nginx、MES/WMS和SAP源生产业务无写入。员工浏览器验收仍由用户承担。
