# WebCodex Local

我不太喜欢给小工具加太多包装。我喜欢即开即关：用的时候点一下启动，用完点一下关闭。配置写清楚，出了问题能从日志里找到原因，这样就够了。

这个项目把本机文件、Git 和命令执行接到 MCP，让 ChatGPT 能操作指定的工作区。服务用 Python 写，隧道使用 OpenAI 官方的 `tunnel-client`。日常入口就是 `start.pyw` 和 `stop.pyw`。

## 安装

准备 Python 3.12 或更新版本。使用 Git 工具时，系统还需要安装 Git，并加入 `PATH`。安装过程会访问 PyPI 和 GitHub。

在项目目录打开终端。Windows 使用命令提示符执行：

```bat
py -3 install.py
copy secrets.example.yaml secrets.yaml
```

打开 `secrets.yaml`，填入自己的 OpenAI MCP 隧道 ID 和 API key：

```yaml
tunnel_id: tunnel_你的隧道ID
tunnel_api_key: 你的API密钥
```

安装程序会创建标准 `.venv`，安装 `requirements.txt` 中的依赖，并下载官方隧道客户端。下载内容按官方 `SHA256SUMS.txt` 校验，许可证和来源记录保存在 `bin/<平台>/`。环境、依赖缓存、下载临时文件和运行日志都放在项目目录里。

Linux 的安装和启停命令：

```sh
python3 install.py
cp secrets.example.yaml secrets.yaml
# 编辑 secrets.yaml，填入凭证。
chmod 600 secrets.yaml
chmod +x start stop
./start
./stop
```

Windows 已完成实际验证。Linux 提供了启动脚本、文件锁和进程组处理，实际运行仍待验证。支持的 CPU 架构为 x86_64 和 ARM64；本机验证使用 Windows x86_64。

## 启动、连接、停止

Windows 双击 `start.pyw`。启动程序会等待本地服务和隧道就绪，成功后退出。重复点击会检查并复用正在运行的实例。启动失败会弹窗，具体原因写入 `runtime/`。

在 ChatGPT 的开发者模式中创建应用，连接方式选 Tunnel，填写 `secrets.yaml` 中的隧道 ID，认证选 `No authentication`。本地隧道客户端会为服务注入运行令牌。连接后调用 `list_projects`，应能看到配置中的项目。

升级后若工具列表仍显示旧内容，在应用设置里刷新工具列表，再开始新对话。

用完双击 `stop.pyw`。停止程序会等待服务退出，并结束服务管理的任务、子进程和隧道连接。项目文件和日志会保留。

命令行也可以查看状态或启停：

```sh
python bootstrap.py status
python bootstrap.py start
python bootstrap.py stop
```

本地 MCP 地址默认是 `http://127.0.0.1:8765/mcp`，采用 Bearer 认证。直接连接本地服务时，令牌取自 `runtime/instance.yaml`，每次启动重新生成。

## 添加工作区

把项目放进程序目录内，例如创建 `projects/demo/`，然后修改 `config.yaml`：

```yaml
projects:
  workspace: ./workspace
  demo: ./projects/demo
```

文件夹应先创建，路径相对于程序目录。保存后默认一秒内加载，调用 `list_projects` 就能看到 `demo`。

文件工具会校验项目路径。命令使用当前账户的权限执行，以所选项目作为工作目录。`run_python` 使用本项目的 `.venv`。

## 配置和热加载

运行配置放在 `config.yaml`，隧道凭证放在 `secrets.yaml`。Python 依赖由 `requirements.txt` 管理。

| 修改内容 | 生效方式 |
| --- | --- |
| `projects`、`files` | 校验通过后，后续工具调用使用新配置 |
| `jobs` | 新任务使用新限制，已有任务沿用启动时的限制 |
| `logging.level`、`reload_seconds` | 校验通过后生效 |
| `server`、`tunnel`、日志轮转大小与数量 | 服务报错并停止，重新启动后应用新配置 |
| `secrets.yaml` | 服务停止，重新启动后使用新凭证 |
| `requirements.txt` | 服务停止，执行 `python install.py` 后重新启动 |

YAML 格式错误、重复字段、未知字段和无效参数会明确报错。热加载失败时服务停止，错误原因写入日志。修改依赖前请先停止服务。

## 工具

| 用途 | 工具 |
| --- | --- |
| 服务与项目 | `get_status_tool`、`list_projects` |
| 浏览与搜索 | `list_files`、`read_file`、`search_text` |
| 创建与编辑 | `write_file`、`replace_text` |
| 后台执行 | `run_process`、`run_python`、`git` |
| 任务管理 | `read_job`、`list_jobs`、`cancel_job` |

编辑已有文件时，先读取，再传入返回的完整文件 SHA-256。读取大文件和任务输出时，使用 `next_offset` 继续读取。二进制文件支持 `base64`。

命令工具接收参数数组并返回任务编号，通过 `read_job` 查看状态和输出。任务终态包括成功、失败、超时、取消和中断。服务重启时，上次遗留的运行中任务会标记为中断。PowerShell 命令会被拒绝。

## 日志和目录

| 路径 | 内容 |
| --- | --- |
| `runtime/service.log` | 服务状态、配置加载、工具调用和异常堆栈 |
| `runtime/launcher.log`、`runtime/console.log` | 启停入口和启动异常 |
| `runtime/tunnel.log`、`runtime/tunnel-console.log` | 官方隧道客户端日志 |
| `runtime/jobs/` | 各任务的状态、输入和输出 |
| `.venv/`、`bin/` | 本地 Python 环境和官方隧道程序 |
| `.cache/`、`.tmp/` | 依赖缓存和临时文件 |
| `workspace/`、`projects/` | 本地工作区 |

这些运行目录以及 `secrets.yaml` 已加入 `.gitignore`。仓库只提供凭证示例。

## 来源与许可

想法来自 [yyjeqhc/webcodex](https://github.com/yyjeqhc/webcodex)。本项目独立实现了 Python 服务、配置、启停和任务管理；隧道组件来自 [OpenAI 官方 tunnel-client](https://github.com/openai/tunnel-client)，固定使用 `v0.0.19`。

本项目采用 [MIT License](LICENSE)。第三方组件的信息见 [THIRD_PARTY.md](THIRD_PARTY.md)。
