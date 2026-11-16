# 制造协同闭环Logo应用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** 将用户明确选定的v2蓝白工件闭环标志应用到制造平台。

**Architecture:** 保持用户PNG原始字节；独立图形用于窄栏/应用图标，完整Logo用于展开导航。通过制造平台现有受保护asset路由的两个固定文件名提供图片，避免把2MiB图片内联进JS；不改共享平台品牌或源系统接口。

**Tech Stack:** 既有React/TypeScript/Python/Vite，无新依赖。

## Global Constraints

- 用户本轮明确要求应用v2，覆盖设计说明旧稿“待评估、不替换生产”的状态。不重绘、不换色，不使用通用M/O字母替代。
- 两原始PNG各自SHA与用户assets.json一致，保留白底；用CSS布局处理留白，不编辑图像。
- MES/WMS与SAP/MRP生产只读继续；子代理无源、SSH、Docker、launchctl或浏览器权限，运维由父代理。
- 不改共享Nginx、PF公司统一登录品牌/共享静态；确认制造专属入口能换则换，不能把共享公司Logo替换成应用Logo。
- 可访问名称为“奥比制造管理”；展开、收起、手机导航均可用。图标链接有界同源，不放开任意文件或公共权限。
- 保留根三个用户修改；制造工单及组件25b0133修复已先切换且正在验收，不回退。

### Task1: 资产与应用入口

- [x] 读取设计依据/尺寸/哈希；原样复制到受版本控制的webui/public固定PNG文件名，Vite构建按原字节输出。
- [x] 先验证必要的asset接口边界（新两个PNG可读、媒体类型、授权/发布保护/未知文件拒绝保持），最小扩展固定媒体清单。
- [x] 导航使用完整Logo和独立图标、中文可访问名及响应式布局；检查共享入口所有权：MF挂载不能可靠区分宿主前后台，保留共享页签图标、标题和应用入口，详见发布记录。
- [x] 相关组件/生命周期回归与构建、原PNG哈希核对；不为纯样式/资产内容写镜像测试。独立评审后精确提交。

### Task2: 受控发布

- [x] 原工单修复验收完毕后归并新Logo主线，构建精确版本，固定37+OEM候选与既有数据保全。
- [x] 只切换制造API资源，核对新JS/CSS/两PNG字节与授权、媒体类型/健康；保存版本证据，员工浏览器验收仍用户完成。

2026-11-16已发布MF `05d640d0`，宿主仍为实际在线的PF `08ec59d7`。发布范围、验证与维护索引见[发布记录](../../reviews/2026-11-16-manufacturing-brand-v2-rollout.md)。
