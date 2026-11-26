# 个股研究 V1.2：一次性网关配置

V1.2 前端仍然沿用原固定 RADAR_KEY、本机加密草稿及后台加密协议。无网关时手动同步仍然可用。请勿清除网站数据、重置密钥或选择采用后台观察池来升级。

## 1. GitHub 创建最小权限令牌
在 https://github.com/settings/personal-access-tokens/new 创建 fine-grained personal access token；Repository access 仅选 investment-cockpit；Repository permissions 仅 Actions: Read and write（Metadata Read 为系统默认）；设置合理到期时间。不要选择 Contents write、其他仓库或 classic PAT。该令牌仍有此仓库的 Actions 权限，必须只存服务端。

## 2. Cloudflare 一次性账号配置
在 https://dash.cloudflare.com/ 注册/登录，在 Workers & Pages 启用 workers.dev 子域（若尚未启用）。账户 ID 在 Cloudflare 控制台账户概览中。创建账户范围的 API Token，权限 Account / Workers Scripts / Edit，限定本人账户；部署如因账户读取权限不足而失败，再按 Cloudflare 提示补充 Account Settings Read。不要使用 Global API Key。

## 3. 在 GitHub Actions Secrets 中添加三个配置
https://github.com/winterous-bot/investment-cockpit/settings/secrets/actions
- WATCHLIST_DISPATCH_TOKEN：第1步的 fine-grained token
- CLOUDFLARE_API_TOKEN：第2步的 API token
- CLOUDFLARE_ACCOUNT_ID：本人 Cloudflare Account ID
现有 RADAR_KEY 和 TUSHARE_TOKEN 不要修改。不要把任何 Token 发给聊天、写入代码或 URL。

## 4. 部署
打开 https://github.com/winterous-bot/investment-cockpit/actions/workflows/watchlist-sync-gateway-deploy.yml ，选择 main，Run workflow。常规部署由主动运行触发；明确标记的网关修复提交也可触发。成功后从 Deploy 日志复制 investment-watchlist-sync.<本人子域>.workers.dev 的 HTTPS 根网址（不要复制日志中的其他内容）。部署脚本使用现有 RADAR_KEY 在 runner 内派生独立 HMAC 密钥，Cloudflare 仅保存派生密钥和 Actions 令牌；不保存原始 RADAR_KEY。

## 5. 手机
关闭并重新打开驾驶舱（不清理数据），个股研究 → 一键同步设置 → 保存网关 → 测试连接 → 一键同步观察池。等待后台完成后页面自动检查；原加密草稿直到后台清单验证一致才清除。手动同步作为备用。连接测试不触发研究，只验证签名及 GitHub 工作流可读；实际提交才能证明 Actions 写权限。后台可能排队、接口失败或部分公司报告未完成，提交接收不代表报告完成。

## 安全及维护
- 网关仅接受指定网页 origin、120秒有效期 HMAC 签名及有界加密请求。签名不能代替后端原 AES-GCM 认证与版本冲突检查。
- Durable Object 记录请求 ID 和摘要以阻止重复派发（24小时、最多约64项），每分钟最多新提交一次；不保存股票明文或请求密文。重复请求返回之前结果，未知结果必须人工检查。GitHub 并发规则仍有效；任务取消/失败保留草稿。
- 原密钥轮换后需重新运行部署任务更新派生密钥；PAT 到期前更新 Secret 后重部署。Cloudflare 权限不足、网络不可达或服务费用/限额变化时可回退手动同步。
- 首次部署后须验证真实网关、iOS 端到端同步、全部待研究股票及自动更新。离线模拟测试不能替代这些生产验证。
