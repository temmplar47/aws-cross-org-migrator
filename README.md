# AWS 跨组织账户迁移系统 / Cross-Org AWS Account Migration

从一个**旧组织（old org）** 把多个 AWS 账户批量迁移到一个**新组织（new org）**。
核心思路：

1. **新组织管理账户** 批量向目标账户发出组织邀请（`InviteAccountToOrganization`）。
2. **旧组织的 IAM Identity Center 用户** 登录 AWS 访问门户（access portal），
   本地 AWS CLI v2 会在 `~/.aws/sso/cache` 缓存一个 SSO `accessToken`。
3. 系统读取该 SSO token，对每个目标账户调用 `sso:get_role_credentials`
   取得**针对该账户的临时凭证**，再以此凭证调用 `organizations:AcceptHandshake`
   —— 也就是**以目标账户的身份**接受邀请、加入新组织。

这正是「用旧组织 IAM Identity Center 用户登录门户 → 拿到各账户临时凭证 →
分别接受邀请」的自动化实现。

---

## 目录结构

```
aws-cross-org-migrator/
├── config.example.yaml          # 配置示例
├── requirements.txt
├── policy/
│   └── sso-permission-set.json   # 旧组织 IAM Identity Center 角色所需权限
└── aws_cross_org_migrator/
    ├── __init__.py
    ├── config.py                 # 配置加载 + 状态持久化
    ├── sso_cache.py              # 读取 ~/.aws/sso/cache 中的 SSO token
    ├── invite.py                 # 新组织管理账户：发邀请
    ├── accept.py                 # 以目标账户身份：接受邀请（核心）
    ├── move.py                   # 可选：接受后移入 OU
    ├── web/                      # 友好前端（零依赖，标准库 HTTP + 原生 JS）
    │   ├── server.py             # 本地 Web 服务 + SSE 实时日志 + JSON API
    │   └── index.py              # 单页前端 HTML/CSS/JS + YAML 序列化
    └── main.py                   # CLI 入口（invite/accept/move/status/run/web）
```

---

## 前置条件

### 1. 新组织（接收方）
- 一个 AWS CLI profile（如 `mgmt-new`），对应**新组织管理账户**，具备：
  `organizations:InviteAccountToOrganization`、`organizations:MoveAccount`（若启用 OU）等。

### 2. 旧组织（供体）IAM Identity Center
- 在旧组织的 **IAM Identity Center** 中，把目标账户 + 某个 Permission Set
  授权给"用来执行迁移的"用户/用户组。该 Permission Set 的 IAM 角色必须包含
  `organizations:AcceptHandshake`（以及 `sso:GetRoleCredentials` 由服务自动授予）。
  参考 `policy/sso-permission-set.json`。
- 用 `aws configure sso` 配好一个 SSO profile（如 `sso-old`），并先登录一次：
  ```powershell
  aws sso login --profile sso-old
  ```
  登录成功后会生成 `~/.aws/sso/cache/<sha1>.json`，本系统从中读取 `accessToken`。

### 3. 配置文件
复制 `config.example.yaml` 为 `config.yaml` 并填写：
- 新组织管理账户 profile / ID
- 旧组织 SSO 的 `start_url`、`sso_region`、`role_name`
- `target_accounts` 列表（账户 ID + 邮箱）

---

## 使用

### 方式 A：命令行（CLI）
```powershell
pip install -r requirements.txt

# 1) 新组织批量发邀请
python -m aws_cross_org_migrator invite -c config.yaml

# 2) 确保旧组织 Identity Center 用户已登录门户（生成 SSO token）
aws sso login --profile sso-old

# 3) 以各目标账户身份接受邀请（临时凭证来自 SSO）
python -m aws_cross_org_migrator accept -c config.yaml

# 4) （可选）把已接受的账户移入指定 OU
python -m aws_cross_org_migrator move -c config.yaml

# 查看进度
python -m aws_cross_org_migrator status -c config.yaml

# 或者一键跑完（会在 accept 前提示你确认已登录）
python -m aws_cross_org_migrator run -c config.yaml
```

### 方式 B：友好前端（推荐，零额外依赖）
启动一个本地网页控制台，可在浏览器里完成：配置编辑、分步/一键执行、
实时日志、各账户状态看板。无需安装任何前端依赖（纯 Python 标准库 + 原生 JS）。

```powershell
python -m aws_cross_org_migrator web -c config.yaml
# 默认 http://127.0.0.1:8787 ，会自动打开浏览器
# 选项：--host 0.0.0.0 --port 9000 --no-browser
```

前端功能：
- **配置卡片**：可视化编辑新组织 / 旧组织 SSO / 目标账户（含增删账户行），保存即写回 YAML。
- **执行卡片**：SSO token 状态指示灯 + 四个按钮（①发邀请 / ④接受邀请 / ⑤移入 OU / 一键运行）。
- **账户状态表**：实时展示每个账户的「邀请 / 握手ID / 接受 / 移入OU」徽章。
- **实时日志**：通过 SSE（Server-Sent Events）流式推送，颜色分级（INFO/WARNING/ERROR）。

> 网页与 CLI 共用同一套迁移逻辑与 `migration_state.json` 状态文件，可混用。

---

## 关键实现说明

- **为什么要以目标账户身份接受？**
  `AcceptHandshake` 必须由**被邀请账户**调用（或其被授权的主体）。
  通过旧组织 IAM Identity Center 把账户+角色授权给迁移用户，再以
  `sso:get_role_credentials` 取得该账户的临时凭证，等价于"以该账户身份"操作。
- **SSO token 来源**：直接从 AWS CLI v2 的 `~/.aws/sso/cache` 读取，无需再次交互登录。
  也可在配置里显式填入 `access_token` 绕过缓存。
- **握手发现**：若未记录 handshake id，会按 `Action=INVITE` 且来源为
  新组织管理账户，在目标账户侧自动查找 OPEN 握手。
- **状态持久化**：每一步结果写入 `migration_state.json`，可断点续跑。

---

## 注意事项 / 限制

- 账户需满足年龄要求：新组织须存在 ≥7 天；由组织创建的成员账户须创建 ≥4 天
  （受邀账户不受此限）。
- SSO 临时凭证默认有效期较短（受 Permission Set 会话时长限制），大批量账户时
  若中途失效需重新 `aws sso login`。
- 接受邀请不会改变账户的账单关系，直到握手 `ACCEPTED` 且账户在新组织可见。
- 本系统只负责"邀请 + 以目标账户接受"。账户从**旧组织移除**由 AWS 在接受后
  自动处理（跨组织迁移会自动把账户从原组织脱离）；如有自定义 SCP/OU 依赖请先评估。
