# 项目总览持续加载修复上线记录

2026-11-11已发布，18:07完成随后独立宿主更新后的复核。当前产测应用 `43a893ddbda1e30f2fd50e4b0f70888d6371fffc`，服务健康、重启0。刷新浏览器页面加载修复代码；原先首次进入后再点项目总览的永久加载路径已由组件回归覆盖。

原因是共用读取hook遗漏逻辑身份key的effect依赖：点击当前总览时读取身份改变、查询起止时间未变，没有发出替换请求，页面却一直等待新身份的数据。修复仅加入该依赖，取消旧请求并启动新读取；相同身份再次点击不会重复请求。没有增加页面说明、延长超时或改动源查询。复现与206项回归见[验证记录](verification/production-overview-loading-fix-2026-11-11.md)。

## 版本与并行发布

| 项目 | 本次修复切换 | 随后的当前宿主 |
| --- | --- | --- |
| MF应用 | `43a893ddbda1e30f2fd50e4b0f70888d6371fffc` | 同一提交，144个制品文件按本次Git清单逐项核验一致 |
| PF宿主 | `f8f362596ed81cac8360c0aa202acb545509ea21` | `d32a3b1bed8e480ba16ed02653d65d9c9e4a3e52` |
| 镜像 | `sha256:c6ebf87da70839debd71824991f0b543113bad953b72dea63489eb8b5855e878` | `sha256:f1d1058feb71cbaf5d5e344f26dca2edc23273c0c60ec1e7e74878460a97fb7e` |
| API容器 | `1ec5def28af8bd726be64d80ee68039e4f90abf0e009bd1ce80c10d69e0576e8` | `63f378f9f7a2c6596683da9ff2927607afb6235428372a8020816407a2c116f0` |
| 完整有序输入 | 原67项保留、追加为68项 | 另一工程资料平台发布再追加为69项，原68项完整保留 |

并行宿主更新发生在本次切换/保全检查完成之后。本次原定final-runtime检查因实际宿主已改变而失败；工作站原静态资源检查因新PF资产不在旧清单中失败。这两份首次失败完整保留，未覆写、未自动重试到通过，也没有回退或覆盖另一会话发布。

随后单独锁定新宿主ID/镜像/提交，核验MF仍为43a893d、144个MF文件和两项资产仍与本次准确Git导出一致、只读挂载仍指向本次源目录。重新验证当前目录管理员策略、15项目完整概览、七类窄窗分析、27次固定SELECT/0失败，以及21个配置处理器匿名401/no-store。新PF登录/制造壳及两个引用静态资源按锁定新宿主文件完整字节比对，工作站公网HTTPS与健康200复核通过；不把这些检查称为新PF镜像的完整36候选。

## 发布与保全

本次修复目标镜像实际36/36候选通过，0失败/跳过，含实际React E30和OEM流程；归档24,727文件在服务器及本地逐项校验，SHA256 `2a80696d582ad17771fe1d7ff58edf365dc15382d74eb21bf65813c44310869b`。制造后台、发布工具、依赖未变；保留既有462项原生/API证据，本次未重跑。

本次切换前排除额外写入者，三个分别一致的在线备份已校验；切换后的三个库内容、schema24、6个模拟制造项目/45台SN保持。后续宿主复核确认真实源配置字节/inode/属主/模式、SDK完整清单、16挂载/4网络、其他34个容器ID/镜像及Nginx配置保持。没有创建员工会话、没有源业务写入或Nginx检查/重载。当前API无原生配置/协议、Traceback或权限错误标记。

| MF资产 | 字节 | SHA256 |
| --- | ---: | --- |
| manufacturing.js | 662748 | `c224c62e4a5508aab7f4ed4e24e3424e44fbda06ba3a7349aaac7d7abd05eca7` |
| manufacturing.css | 75752 | `015fd2b459481a4b175b1d26895ffc8fbf275f4a8e75b290f9e0049bc948dcb5` |

本次68项切换清单为 `/opt/orbbec-agent-platform/staging/manufacturing-overview-fix-20261111-r1/future-maintenance.json`，SHA256 `dd857675150b4187f7e2278b61ba2fb3af307b05f8f20ce7f80fc6fe369130dc`。**它只记录本次切换，不能单独用作当前69项宿主基线。** 当前维护还须纳入 `/opt/orbbec-agent-platform/private/engineering-knowledge-20261111-d32a3b1bed8e480ba16ed02653d65d9c9e4a3e52-20261111T095637Z/transaction/compose.candidate.json` 及其同目录apply.complete.json（SHA256 `adfd70d1214f52b8fadd3c17971eba2df56103f01916af0aa4612280eba34ffb`），重新核对实际PF/MF、镜像和全部有序输入。

私有stage及本地 `.superpowers/releases/manufacturing-overview-fix-20261111-r1` 保留候选、备份、首次失败和当前宿主14份收据；当前收据各哈希均已核验。后续文档提交不改变运行应用提交。浏览器真实页面、员工登录和现场业务验收仍由用户完成。
