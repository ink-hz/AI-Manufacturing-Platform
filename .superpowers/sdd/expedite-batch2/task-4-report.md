# Task4 — 实际 HTTP 走查与 preview 支持

范围：独立私有 preview 的实际回环 socket HTTP 走查；未连接源系统使用既有类型化 mock。root 实现。

## RED / GREEN

1. 合成角色选择：先写两项测试，观察 build_app 不支持 actor_id 的预期 TypeError；增加仅私有 manifest 合成身份可选的 serve --actor-id，管理员身份仅授予 manifest admin_id。原默认行为保留。专项19通过。
2. mock 源库重启：实际操作后旧 load_owned 拒绝 mock-systems 目录。先补回归，观察 Unexpected preview directory；只允许本 dataset 固定 SYSTEM_IDS 的源数据库/SQLite sidecar 与 UUID guard锁文件，仍拒绝未知目录/文件及软硬链接。最终preview专项25通过（2.69秒），包含真实socket、CSRF/Host/Origin及renderer检查。
3. 实际HTTP脚本先遇到SAP未收到精确BOM确认，保留失败，按既有query推动耐久因果投递而不改前置条件；随后在缺少B标记、缺少C操作处依次失败，feature完成后通过。SRM严格输入曾拒绝多余material_id，修正调用而不放松模型。WMS原事实sap_posted为空时，改查其精确cause对应的SAP子事实，分别断言阶段，不合并成功含义。
4. C提交2a6eb9a后最终TCP运行退出0：根 /Users/neo/.codex/worktrees/814b/expedite-http-verified；输出 .superpowers/sdd/expedite-batch2/verified。包含SRM供料链、所有A–E步骤、WMS/SAP精确来源证据、双人交接、四状态和按需求分页、关闭清理、MES来源开案、重复投影、进程重启。快照包括workflow数量表、所有legacy authority表及WMS/SAP源facts。CSRF token不落证据。

所有业务写入经HTTP。唯一直接维护写是在HTTP创建新项目后、任何业务意图前，调用已有assign_profile绑定demo-only不可变档案，单列于走查记录。

文件：scripts/preview_manufacturing.py；scripts/verify_expedite_batch2.py；tests/workflow/test_preview_manufacturing.py；接口验证契约、文档口径补充、交付说明及此记录。

整体full-backend.log和最终全分支审查是收尾门；本报告不把局部socket验证称作真实外部系统或现场业务验收。

全量环境补充：第一次已提交代码的完整回归在 E29 两个真实宿主场景失败，授权矩阵断言本身已完成，失败原因是新 worktree 缺少被忽略的 Vitest 包。按锁文件在该工作区 webui 执行 npm ci（未改动原目录或任何跟踪文件），两场景覆盖重跑2通过，各自实际组件报告37通过、0失败。没有修改业务代码、权限或测试断言。最终完整回归将在依赖齐全的环境重跑，首轮失败日志另存并保留。
