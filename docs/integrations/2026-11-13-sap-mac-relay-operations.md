# Mac只读SAP中转运维

本说明对应SAP测试接入。所有源生产系统仍只读；连接器本身也只允许两个已验证的SAP测试查询。中转不开放任意网络、URL、SOAP、SQL或RFC函数。版本和实际发布结果另见当次验证记录，安装服务不代表已切换线上API。

## 架构及凭据

云API→私有Unix socket→Mac主动建立的SSH反向隧道→Mac127.0.0.1网关→SAP测试环境。SSH使用`-F none`与显式身份、主机密钥文件，防止其他SSH配置附带转发或命令。

SAP账号密码只在Mac私有配置。云端保存独立中转令牌与已登记的来源指纹，不保存SAP密码。查询参数只包含工单/工厂或物料/工厂；来源变更必须重新受控登记，不能自动换系统或环境。不要把中转改为直接暴露SAP端口。

Mac受控运行目录为当前用户的`Library/Application Support/ManufacturingSAPRelay/`，包含固定提交代码、独立Python环境、私有state和运行清单。运行依赖从已验证的本机安装复制并记录散列，不修改全局Python包。服务不依赖开发工作树继续存在。

云端复用现有`/app/data/manufacturing/sap-relay/`私有目录；配置/令牌归UID10001、权限0600。bridge目录由root管理、组10001、权限0750，socket为0660；active.sock只指向同目录本实例socket。配置和令牌在发布前固定散列，socket可以经认证后轮换。

## 查看、停用及恢复

LaunchAgent标签：`com.orbbec.manufacturing.sap-relay.gateway`和`com.orbbec.manufacturing.sap-relay.tunnel`。plist在当前用户`Library/LaunchAgents/`，日志在上述运行目录的state下，均为私有文件。

只停用中转时，先停止tunnel，再停止gateway；这不会停止云端平台或改变SAP业务数据：

```sh
launchctl bootout gui/$(id -u)/com.orbbec.manufacturing.sap-relay.tunnel
launchctl bootout gui/$(id -u)/com.orbbec.manufacturing.sap-relay.gateway
```

恢复时先bootstrap gateway的plist，确认ready已生成，再bootstrap tunnel的plist。不要同时手工启动第二份同标签服务，不要删除其他实例socket或整个bridge目录。需要更新代码/来源时，先保留私有运行清单和审计，再使用经过验证的提交重建并受控切换。

Mac保持内网连接；关闭电脑、手动睡眠或断网会中断中转。caffeinate仅随网关进程存活抑制空闲睡眠，未修改系统电源设置。隧道重连只重新建立传输和认证探测，不重放业务查询。失效时页面应显示Mac中转离线，保留上次成功结果及原读取时间。

## 验证及发布边界

先验证云端应用UID10001的socket访问、真实工单/组件/MRP读取和离线恢复，再进行API-only发布候选验收。生产源业务写入、共享Nginx/SSH服务配置变更、公网端口开放均不属于本方案。

工作流schema从28升级到29后，应保留现有向前修复策略和数据库/WAL；不得拿旧备份覆盖新写入。员工账号与浏览器验收由用户承担，隔离测试身份不冒充员工登录。
