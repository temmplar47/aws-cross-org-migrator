"""Local web server for the migration UI.

No third-party dependencies: uses stdlib ``http.server`` + SSE for live logs.
Wraps the existing migration modules (invite / accept / move) and exposes a
small JSON API consumed by the single-page frontend in ``index.html``.
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from botocore.exceptions import ProfileNotFound

from ..config import Config, StateStore
from ..invite import Inviter
from ..accept import HandshakeAcceptor
from ..move import AccountMover
from ..sso_cache import get_access_token, SSOCacheError
from .index import INDEX_HTML

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live log hub (SSE)
# ---------------------------------------------------------------------------
class LogHub:
    def __init__(self, maxlen: int = 500):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.history: list[dict] = []
        self.maxlen = maxlen

    def publish(self, level: str, msg: str) -> None:
        entry = {"t": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
        with self._lock:
            self.history.append(entry)
            if len(self.history) > self.maxlen:
                self.history = self.history[-self.maxlen:]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(entry)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        # replay recent history so a late-joining client sees context
        with self._lock:
            for e in self.history:
                try:
                    q.put_nowait(e)
                except queue.Full:
                    break
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


class _HubHandler(logging.Handler):
    def __init__(self, hub: LogHub):
        super().__init__()
        self.hub = hub

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.hub.publish(record.levelname, self.format(record))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------
class AppState:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._ensure_config(config_path)
        self.cfg = Config.from_file(config_path)
        self.state = StateStore(self.cfg.settings.state_file)
        self.hub = LogHub()
        self.lock = threading.Lock()
        self.busy = False
        self.current_task = None

        handler = _HubHandler(self.hub)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        # keep boto/botocore quieter to avoid log noise
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("boto3").setLevel(logging.WARNING)
        if not root.level or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    DEFAULT_CONFIG = """\
# 跨组织 AWS 账户迁移 - 配置
# 复制自 config.example.yaml，首次运行自动生成

new_organization:
  management_account_profile: "mgmt-new"
  management_account_id: "111111111111"
  target_ou_id: ""
  move_poll_timeout: 300

old_organization_sso:
  start_url: "https://my-old-org.awsapps.com/start"
  sso_region: "ap-southeast-1"
  role_name: "AWSAdministratorAccess"
  access_token: ""

target_accounts:
  - id: "222222222222"
    email: "account-2@example.com"
  - id: "333333333333"
    email: "account-3@example.com"
  - id: "444444444444"
    email: "account-4@example.com"

settings:
  region: "us-east-1"
  state_file: "migration_state.json"
  poll_interval: 10
  poll_max_attempts: 30
"""

    def _ensure_config(self, config_path: Path) -> None:
        if config_path.exists():
            return
        # Try to copy from config.example.yaml in the same directory
        example = config_path.with_name("config.example.yaml")
        if example.exists():
            import shutil
            shutil.copy(example, config_path)
            print("\n  [OK] config.yaml not found, copied from config.example.yaml.\n")
        else:
            config_path.write_text(self.DEFAULT_CONFIG, encoding="utf-8")
            print("\n  [OK] config.yaml not found, created default. Edit it and restart.\n")


# ---------------------------------------------------------------------------
# Action runner
# ---------------------------------------------------------------------------
def _run_action(app: AppState, action: str) -> None:
    with app.lock:
        if app.busy:
            app.hub.publish("WARNING", "另一个任务正在进行中，已忽略本次请求。")
            return
        app.busy = True
        app.current_task = action

    try:
        cfg, state, hub = app.cfg, app.state, app.hub
        ids = [a["id"] for a in cfg.target_accounts]

        if action in ("invite", "run"):
            hub.publish("INFO", f"==> 新组织开始批量邀请 {len(ids)} 个账户 ...")
            inviter = Inviter(cfg.new_org.management_account_profile, region=cfg.settings.region)
            results = inviter.invite_all(ids)
            for acc, hs_id in results.items():
                state.set(acc, handshake_id=hs_id, invited=bool(hs_id))
                hub.publish("INFO", f"    {acc}: {'邀请成功 -> ' + hs_id if hs_id else '失败/已邀请'}")

        if action in ("accept", "run"):
            # token check
            try:
                get_access_token(start_url=cfg.sso.start_url, access_token=cfg.sso.access_token)
            except SSOCacheError as e:
                hub.publish("ERROR", "未找到 SSO access token。请先在终端运行 "
                                     "`aws sso login --profile <sso-profile>` 再重试接受步骤。")
                hub.publish("ERROR", str(e))
                return

            hub.publish("INFO", f"==> 以各目标账户身份接受邀请（SSO 临时凭证）...")
            acceptor = HandshakeAcceptor(
                start_url=cfg.sso.start_url,
                role_name=cfg.sso.role_name,
                sso_region=cfg.sso.sso_region,
                new_mgmt_account_id=cfg.new_org.management_account_id,
                access_token=cfg.sso.access_token,
                orgs_region=cfg.settings.region,
                poll_interval=cfg.settings.poll_interval,
                poll_max_attempts=cfg.settings.poll_max_attempts,
            )
            results = acceptor.accept_all(ids, {a: state.get(a).get("handshake_id") for a in ids})
            for r in results:
                state.set(r.account_id, accepted=r.accepted, accept_error=r.error)
                hub.publish("INFO", f"    {r.account_id}: {'已接受' if r.accepted else '失败'}")

        if action in ("move", "run") and cfg.new_org.target_ou_id:
            hub.publish("INFO", f"==> 将已接受账户移入 OU {cfg.new_org.target_ou_id} ...")
            mover = AccountMover(
                cfg.new_org.management_account_profile,
                region=cfg.settings.region,
                timeout=cfg.new_org.move_poll_timeout,
            )
            for acc in ids:
                if state.get(acc).get("accepted"):
                    ok = mover.move(acc, cfg.new_org.target_ou_id)
                    state.set(acc, moved=ok)
                    hub.publish("INFO", f"    {acc}: {'已移入 OU' if ok else '移动失败'}")
        elif action == "move":
            hub.publish("WARNING", "未配置 target_ou_id，跳过移动步骤。")

        hub.publish("INFO", "==> 任务完成。")
    except ProfileNotFound as e:
        app.hub.publish("ERROR", f"AWS CLI profile 不存在: {e}")
        app.hub.publish(
            "ERROR",
            "本机 ~/.aws 中没有该 profile。请在「配置」卡片输入新组织管理账户的 "
            "AK/SK 并点「自动识别」（会自动在本机创建 profile），或在终端运行 "
            "`aws configure --profile <profile名>` 后重试。",
        )
    except Exception as e:  # pragma: no cover - defensive
        LOG.exception("action failed")
        app.hub.publish("ERROR", f"任务异常: {e}")
    finally:
        with app.lock:
            app.busy = False
            app.current_task = None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    app: AppState  # set as class attribute below via factory

    def __init__(self, *args, app: AppState = None, **kwargs):
        self.app = app
        super().__init__(*args, **kwargs)

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/config":
            self._json(self._config_payload())
            return
        if path == "/api/status":
            self._json(self._status_payload())
            return
        if path == "/api/token":
            self._json(self._token_payload())
            return
        if path == "/api/sso-login-status":
            self._json(self._sso_login_status_payload())
            return
        if path == "/api/logs":
            self._sse()
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            data = {}

        path = self.path.split("?", 1)[0]
        if path == "/api/config":
            self._json(self._save_config(data))
            return
        if path == "/api/action":
            action = data.get("action")
            if action not in ("invite", "accept", "move", "run"):
                self._json({"ok": False, "error": "unknown action"}, 400)
                return
            threading.Thread(target=_run_action, args=(self.app, action), daemon=True).start()
            self._json({"ok": True, "action": action})
            return
        if path == "/api/resolve-credentials":
            self._json(self._resolve_credentials(data))
            return
        if path == "/api/parse-accounts":
            self._json(self._parse_accounts(data))
            return
        if path == "/api/sso-login":
            self._json(self._do_sso_login())
            return
        if path == "/api/clear":
            self._json(self._clear_all())
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    # -- payloads -----------------------------------------------------------
    def _config_payload(self):
        cfg = self.app.cfg
        return {
            "new_org": {
                "management_account_profile": cfg.new_org.management_account_profile,
                "management_account_id": cfg.new_org.management_account_id,
                "target_ou_id": cfg.new_org.target_ou_id,
            },
            "sso": {
                "start_url": cfg.sso.start_url,
                "sso_region": cfg.sso.sso_region,
                "role_name": cfg.sso.role_name,
                "aws_profile": getattr(cfg.sso, "aws_profile", ""),
            },
            "settings": {"region": cfg.settings.region},
            "target_accounts": cfg.target_accounts,
        }

    def _status_payload(self):
        accounts = []
        for a in self.app.cfg.target_accounts:
            st = self.app.state.get(a["id"])
            accounts.append({
                "id": a["id"],
                "email": a.get("email", ""),
                "invited": st.get("invited"),
                "handshake_id": st.get("handshake_id"),
                "accepted": st.get("accepted"),
                "accept_error": st.get("accept_error"),
                "moved": st.get("moved"),
            })
        return {
            "busy": self.app.busy,
            "current_task": self.app.current_task,
            "accounts": accounts,
        }

    def _token_payload(self):
        try:
            get_access_token(
                start_url=self.app.cfg.sso.start_url,
                access_token=self.app.cfg.sso.access_token,
            )
            return {"present": True}
        except SSOCacheError:
            return {"present": False}

    # ----------------------------------------------------------------------
    # POST /api/resolve-credentials
    # ----------------------------------------------------------------------
    def _resolve_credentials(self, data):
        """Validate AK/SK via STS, return account ID and org membership."""
        ak = (data.get("access_key_id") or "").strip()
        sk = (data.get("secret_access_key") or "").strip()
        if not ak or len(ak) < 16:
            return {"ok": False, "error": "Invalid Access Key ID"}
        if not sk:
            return {"ok": False, "error": "Secret Access Key is required"}
        try:
            import boto3
            creds = {"aws_access_key_id": ak, "aws_secret_access_key": sk}
            region = data.get("region", "us-east-1")
            sts = boto3.client("sts", region_name=region, **creds)
            identity = sts.get_caller_identity()
            account_id = identity["Account"]
            arn = identity["Arn"]
            in_org = False
            org_master = False
            try:
                orgs = boto3.client("organizations", region_name="us-east-1", **creds)
                orgs.list_accounts(MaxResults=1)
                in_org = True
                try:
                    mgnt = orgs.describe_organization()["Organization"]["MasterAccountId"]
                    org_master = (mgnt == account_id)
                except Exception:
                    pass
            except Exception:
                pass
            profile = f"aws-mgmt-{account_id}"
            profile_created = self._write_aws_profile(profile, ak, sk, region)
            return {
                "ok": True,
                "account_id": account_id,
                "arn": arn,
                "in_org": in_org,
                "org_master": org_master,
                "suggested_profile": profile,
                "profile_created": profile_created,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _write_aws_profile(profile: str, ak: str, sk: str, region: str) -> bool:
        """Persist the validated AK/SK as a named profile in ~/.aws.

        Without this the auto-recognition only fills the profile NAME into the
        config, and the invite step later fails with ProfileNotFound.
        Returns True if newly written, False if the profile already existed.
        """
        aws_dir = Path.home() / ".aws"
        aws_dir.mkdir(parents=True, exist_ok=True)
        cred_path = aws_dir / "credentials"
        cfg_path = aws_dir / "config"
        created = False

        cred_text = cred_path.read_text(encoding="utf-8") if cred_path.exists() else ""
        if f"[{profile}]" not in cred_text:
            with open(cred_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{profile}]\naws_access_key_id = {ak}\naws_secret_access_key = {sk}\n")
            created = True

        cfg_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
        prof_sec = f"[profile {profile}]"
        if prof_sec not in cfg_text:
            with open(cfg_path, "a", encoding="utf-8") as f:
                f.write(f"\n{prof_sec}\nregion = {region}\n")
            created = True
        return created

    # ----------------------------------------------------------------------
    # POST /api/parse-accounts
    # ----------------------------------------------------------------------
    def _parse_accounts(self, data):
        """Parse bulk account ID text/csv. Returns list of {id, email}."""
        content = (data.get("content") or "").strip()
        fmt = data.get("format", "auto")
        if not content:
            return {"ok": False, "accounts": [], "error": "No content provided"}
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        accounts = []
        errors = []

        def valid_id(s):
            s = s.strip().strip('"').strip("'")
            return len(s) == 12 and s.isdigit(), s

        if fmt == "csv" or (
            fmt == "auto"
            and any("," in l for l in lines)
            and not all(l[0].isdigit() and len(l.split(",")) == 1 for l in lines)
        ):
            for i, line in enumerate(lines):
                parts = [p.strip().strip('"').strip("'") for p in line.split(",")]
                if i == 0 and len(parts) == 1 and parts[0].isdigit() and len(parts[0]) != 12:
                    continue
                acct_id = parts[0] if parts else ""
                email = parts[1] if len(parts) > 1 else ""
                ok, acct_id = valid_id(acct_id)
                if ok:
                    accounts.append({"id": acct_id, "email": email})
                elif acct_id:
                    errors.append(f"Line {i+1}: invalid ID '{acct_id}'")
        else:
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                sep = "," if "," in line else "\t" if "\t" in line else None
                parts = [p.strip() for p in line.split(sep)] if sep else line.split()
                acct_id = parts[0]
                email = parts[1] if len(parts) > 1 else ""
                ok, acct_id = valid_id(acct_id)
                if ok:
                    accounts.append({"id": acct_id, "email": email})
                elif acct_id:
                    errors.append(f"Line {i+1}: invalid ID '{acct_id}'")
        return {"ok": True, "accounts": accounts, "errors": errors[:10]}

    # ----------------------------------------------------------------------
    # POST /api/sso-login
    # ----------------------------------------------------------------------
    def _do_sso_login(self):
        """Spawn a new visible terminal running `aws sso login` for the old org SSO profile."""
        import platform
        # Read the AWS CLI profile name from old_organization_sso.aws_profile
        import yaml
        raw = self.app.config_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw) or {}
        profile = (
            parsed.get("old_organization_sso", {}).get("aws_profile")
            or parsed.get("old_organization_sso", {}).get("profile")
            or ""
        )
        if not profile:
            return {
                "ok": False,
                "error": (
                    "请先在配置中填写「旧组织 SSO」的 AWS CLI Profile 名称（如 sso-old），"
                    "然后再点「运行 SSO Login」。"
                ),
                "need_profile": True,
            }
        try:
            if platform.system() == "Windows":
                CREATE_NEW_CONSOLE = 0x00000010
                subprocess.Popen(
                    [
                        "cmd", "/c",
                        f"title AWS SSO Login --profile {profile} && "
                        f"echo Logging in with profile: {profile} && "
                        f"aws sso login --profile {profile} && "
                        f"echo. && echo Done! Close this window and refresh the page. && pause"
                    ],
                    creationflags=CREATE_NEW_CONSOLE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["x-terminal-emulator", "-e", f"aws sso login --profile {profile}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return {
                "ok": True,
                "profile": profile,
                "hint": "新终端窗口已打开，请在窗口中完成浏览器登录。完成后回到本页面点击「刷新 token」。",
            }
        except FileNotFoundError as e:
            return {"ok": False, "error": f"找不到终端: {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _sso_login_status_payload(self):
        import yaml
        raw = self.app.config_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw) or {}
        profile = (
            parsed.get("old_organization_sso", {}).get("aws_profile")
            or parsed.get("old_organization_sso", {}).get("profile")
            or ""
        )
        return {"profile": profile or None, "has_profile": bool(profile)}

    # ----------------------------------------------------------------------
    # POST /api/clear
    # ----------------------------------------------------------------------
    def _clear_all(self):
        """One-click reset: empty the target account list and all per-account state."""
        if self.app.busy:
            return {"ok": False, "error": "任务运行中，请等待完成后再清空。"}
        try:
            self.app.cfg.target_accounts = []
            from .index import config_to_yaml
            self.app.config_path.write_text(config_to_yaml(self.app.cfg), encoding="utf-8")
            self.app.state.data = {}
            self.app.state.save()
            self.app.hub.publish("INFO", "已清空目标账户列表与全部账户迁移状态。")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _save_config(self, data):
        try:
            cfg = self.app.cfg
            no = data.get("new_org", {})
            sso = data.get("sso", {})
            if no.get("management_account_profile"):
                cfg.new_org.management_account_profile = no["management_account_profile"]
            if no.get("management_account_id"):
                cfg.new_org.management_account_id = no["management_account_id"]
            cfg.new_org.target_ou_id = no.get("target_ou_id") or None
            if sso.get("start_url"):
                cfg.sso.start_url = sso["start_url"]
            if sso.get("sso_region"):
                cfg.sso.sso_region = sso["sso_region"]
            if sso.get("role_name"):
                cfg.sso.role_name = sso["role_name"]
            aws_profile = sso.get("aws_profile", "")
            if aws_profile:
                setattr(cfg.sso, "aws_profile", aws_profile)
            if data.get("settings", {}).get("region"):
                cfg.settings.region = data["settings"]["region"]
            if isinstance(data.get("target_accounts"), list):
                cfg.target_accounts = data["target_accounts"]

            # persist to YAML
            from .index import config_to_yaml
            self.app.config_path.write_text(
                config_to_yaml(cfg), encoding="utf-8"
            )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- SSE ----------------------------------------------------------------
    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = self.app.hub.subscribe()
        try:
            while True:
                try:
                    entry = q.get(timeout=30)
                except queue.Empty:
                    # heartbeat
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                line = json.dumps(entry, ensure_ascii=False)
                self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.app.hub.unsubscribe(q)

    def log_message(self, *args):  # silence default stderr logging
        pass


def run_server(config_path: str | Path, host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True):
    config_path = Path(config_path)
    app = AppState(config_path)

    def make_handler(*args, **kwargs):
        return Handler(*args, app=app, **kwargs)

    server = ThreadingHTTPServer((host, port), make_handler)

    url = f"http://{host}:{port}/"
    LOG.info("Migration UI serving at %s", url)
    print(f"\n  AWS 跨组织迁移 · 友好前端已启动： {url}\n  (Ctrl+C 退出)\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
