# WebCodex-Bare

[简体中文](#zh-cn) | [English](#en)

<a id="zh-cn"></a>

## 简体中文

> 提醒：本工具以自用为主，因此测试可能有不及时的地方。有bug可以走issue或者PR，看到就会修（

起因：我的Codex降智了。被迫营业。

原则：我不太喜欢给小工具加太多包装。我喜欢即开即关：用的时候点一下启动，用完点一下关闭。配置写清楚，出了问题能从日志里找到原因，这样就够了。

这个项目把本机文件、Git 和命令执行接到 MCP，让 ChatGPT 能操作指定的工作区。服务用 Python 写，隧道使用 OpenAI 官方的 `tunnel-client`。日常入口就是 `start.pyw` 和 `stop.pyw`。

本项目的想法来源于 [yyjeqhc/webcodex](https://github.com/yyjeqhc/webcodex) ，在这里致谢。

### 安装

首先直接下载整个项目。直接源码运行。（有时间我会release一个zip，但没有本质区别）

准备 Python 3.12 或更新版本。使用 Git 工具时，系统还需要安装 Git，并加入 `PATH`。安装过程会访问 PyPI 和 GitHub。

在项目目录打开终端。Windows 使用命令提示符执行：

```bat
py -3 install.py
copy secrets.example.yaml secrets.yaml
```

安装程序会创建标准 `.venv`，安装 `requirements.txt` 中的依赖，并下载官方隧道客户端。下载内容按官方 `SHA256SUMS.txt` 校验，许可证和来源记录保存在 `bin/<平台>/`。环境、依赖缓存、下载临时文件和运行日志都放在项目目录里。

Linux 的安装命令：

```sh
python3 install.py
cp secrets.example.yaml secrets.yaml
chmod 600 secrets.yaml
chmod +x start stop
```

Windows 已完成实际验证。Linux 提供了启动脚本、文件锁和进程组处理，实际运行仍待验证。支持的 CPU 架构为 x86_64 和 ARM64；本机验证使用 Windows x86_64。

### 获取隧道 ID 和 API key（首次配置）

1. 登录 [OpenAI Platform 隧道设置](https://platform.openai.com/settings/organization/tunnels)，选择要使用的组织，创建隧道，复制完整的 `tunnel_...` ID。
2. 在隧道设置中关联准备用来连接的 ChatGPT 工作区。
3. 打开同一组织的 [API keys 页面](https://platform.openai.com/settings/organization/api-keys)，创建用于 `tunnel-client` 运行的 API key。

创建隧道需要组织级 `Tunnels Read + Manage` 权限，运行隧道和在 ChatGPT 中选择隧道需要 `Tunnels Read + Use`。页面提示 `Tunnels access required` 时，请组织所有者或 RBAC 管理员授予相应权限。具体要求见 [OpenAI 官方隧道说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

把隧道 ID 和运行用的 API key 填入 `secrets.yaml`：

```yaml
tunnel_id: tunnel_你的隧道ID
tunnel_api_key: 你的API密钥
```

凭证以明文保存在本机的 `secrets.yaml` 中。本工具默认你的机器和账户环境是安全的。机器存在安全风险时，请谨慎使用。

#### 首次连接 ChatGPT

保存凭证后，先启动程序：Windows 双击 `start.pyw`，Linux 执行 `./start`，等待本地服务和隧道就绪。

在 [ChatGPT Plugins](https://chatgpt.com/plugins) 中选择 `Add custom MCP server`，连接方式选 `Tunnel`，填写 `secrets.yaml` 中的隧道 ID，认证选 `No authentication`。本地隧道客户端会为服务注入运行令牌。连接后调用 `list_projects`，应能看到配置中的项目。添加权限由账户和工作区设置控制，入口说明见 [OpenAI 官方连接指南](https://developers.openai.com/plugins/deploy/connect-chatgpt)。

ChatGPT 会保留添加好的应用连接，后续日常使用时复用该连接。

升级后若工具列表仍显示旧内容，在应用设置里刷新工具列表，再开始新对话。

本地 MCP 地址默认是 `http://127.0.0.1:8765/mcp`，采用 Bearer 认证。直接连接本地服务时，令牌取自 `runtime/instance.yaml`，每次启动重新生成。

### 日常启动与停止

Windows 双击 `start.pyw`。启动程序会等待本地服务和隧道就绪，成功后退出。重复点击会检查并复用正在运行的实例。启动失败会弹窗，具体原因写入 `runtime/`。

服务就绪后，在 ChatGPT 对话中选择已经添加的应用，即可调用工具。

用完双击 `stop.pyw`。停止程序会等待服务退出，并结束服务管理的任务、子进程和隧道连接。项目文件和日志会保留。

Linux 使用 `./start` 启动，使用 `./stop` 停止。

命令行也可以查看状态或启停：

```sh
python bootstrap.py status
python bootstrap.py start
python bootstrap.py stop
```

### 添加工作区

在 `config.yaml` 的 `projects` 中，每行配置一个工作区。工作区可以位于本机任意位置：

```yaml
projects:
  workspace: ./workspace
  demo: 'D:/code/demo'
  notes: '../notes'
```

文件夹应先创建。绝对路径直接使用，相对路径以 `config.yaml` 所在目录为基准，也支持 `~` 表示当前用户目录。Linux 的绝对路径例如 `/home/user/code/demo`。保存后默认一秒内加载，调用 `list_projects` 可查看各工作区解析后的绝对路径。

工具中的相对路径以所选工作区为基准；绝对路径直接使用，`..` 按实际路径解析。工作区用于定位项目和设置默认工作目录，文件访问规则由下面的 `permissions` 配置控制。`run_python` 使用本项目的 `.venv`。

### 工具与权限

默认配置保持本机账户的完整访问能力：

```yaml
permissions:
  read: ['*']
  write: ['*']
  execute: true
```

`read` 控制文件浏览、读取与搜索，`write` 控制创建和编辑文件。`['*']` 表示当前账户可访问的所有目录，`[]` 表示关闭该类访问。指定目录时每行写一个路径，该目录及其子目录允许访问；绝对路径、相对路径和 `~` 的解析规则与工作区配置相同。程序根据解析后的实际路径检查权限，包括符号链接和 Windows 目录联接的目标。授权目录可独立于 `projects` 配置。

例如，允许读取两个目录，只在第一个目录中编辑，并关闭命令执行：

```yaml
permissions:
  read:
    - 'D:/code/demo'
    - '../notes'
  write:
    - 'D:/code/demo'
  execute: false
```

纯只读使用时，将 `write` 设为 `[]`，`execute` 设为 `false`。编辑已有文件需要该文件的读取权限，以及最近读取返回的 SHA-256。

`execute` 控制 `run_process`、`run_python` 和 `git`。允许执行的命令继承启动账户的系统权限，可以操作该账户可访问的文件、网络和程序。`read`、`write` 的目录规则作用于文件工具；命令的访问范围由操作系统控制。需要把命令也限制在指定目录内时，应使用专门的低权限账户或操作系统隔离环境。

`tools` 列出所有工具的独立开关，例如 `read_file: true`、`git: false`。有效工具列表同时遵循开关和 `permissions`：关闭命令执行后，三个执行工具会从列表移除；文件读取或写入列表为空时，对应文件工具会移除。客户端按缓存的旧工具列表调用时，服务端仍会检查当前配置并明确报错。`cancel_job` 可继续用于取消已有任务，其开关单独控制。

`read_job`、`list_jobs` 控制任务记录与输出的访问。任务记录可能包含之前命令读取的数据；配置文件工具的目录规则时，请同时考虑这两个开关。`get_status_tool` 返回当前权限、有效工具列表和配置版本。操作日志记录工具名、目标路径、配置版本及失败原因。

工具的只读、破坏性、幂等性和外部访问声明由实际实现生成，帮助客户端选择工具和显示确认提示。服务端执行每次调用的工具与路径权限检查。

`mcp` 中的 `name`、`title`、`description`、`instructions` 分别配置服务名称、显示标题、描述与模型使用指引，修改后重新启动。修改工具开关后，ChatGPT 可能需要在应用设置中点击 `Refresh`，再开始新对话。

从旧版本升级时，请先停止服务，将新版 `config.yaml` 中的 `permissions`、`tools`、`mcp` 三节加入现有配置，保留自己的工作区和其他设置，再重新启动。

### 配置和热加载

运行配置放在 `config.yaml`，隧道凭证放在 `secrets.yaml`。Python 依赖由 `requirements.txt` 管理。

| 修改内容 | 生效方式 |
| --- | --- |
| `projects`、`files`、`permissions`、`tools` | 校验通过后，后续工具调用使用新配置 |
| `jobs` | 新任务使用新限制，已有任务沿用启动时的限制 |
| `logging.level`、`reload_seconds` | 校验通过后生效 |
| `server`、`tunnel`、`mcp`、日志轮转大小与数量 | 服务报错并停止，重新启动后应用新配置 |
| `secrets.yaml` | 服务停止，重新启动后使用新凭证 |
| `requirements.txt` | 服务停止，执行 `python install.py` 后重新启动 |

YAML 格式错误、重复字段、未知字段和无效参数会明确报错。热加载失败时服务停止，错误原因写入日志。修改依赖前请先停止服务。

权限和开关变更作用于后续调用，已有任务继续运行。需要结束已有任务时，调用 `cancel_job` 或停止服务。

### 工具

| 用途 | 工具 |
| --- | --- |
| 服务与项目 | `get_status_tool`、`list_projects` |
| 浏览与搜索 | `list_files`、`read_file`、`search_text` |
| 创建与编辑 | `write_file`、`replace_text` |
| 后台执行 | `run_process`、`run_python`、`git` |
| 任务管理 | `read_job`、`list_jobs`、`cancel_job` |

编辑已有文件时，先读取，再传入返回的完整文件 SHA-256。读取大文件和任务输出时，使用 `next_offset` 继续读取。二进制文件支持 `base64`。

命令工具接收参数数组并返回任务编号，通过 `read_job` 查看状态和输出。任务终态包括成功、失败、超时、取消和中断。服务重启时，上次遗留的运行中任务会标记为中断。PowerShell 命令会被拒绝。

### 日志和目录

| 路径 | 内容 |
| --- | --- |
| `runtime/service.log` | 服务状态、配置加载、工具调用和异常堆栈 |
| `runtime/launcher.log`、`runtime/console.log` | 启停入口和启动异常 |
| `runtime/tunnel.log`、`runtime/tunnel-console.log` | 官方隧道客户端日志                     |
| `runtime/jobs/` | 各任务的状态、输入和输出 |
| `.venv/`、`bin/` | 本地 Python 环境和官方隧道程序 |
| `.cache/`、`.tmp/` | 依赖缓存和临时文件 |
| `workspace/`、`projects/` | 本地工作区 |

这些运行目录以及 `secrets.yaml` 已加入 `.gitignore`。仓库只提供凭证示例。

### 常见问题

#### Q1：程序已经启动，ChatGPT 也连接了，为什么工具调用仍然失败？

ChatGPT 可能缓存了旧的工具定义，更新程序后仍按旧列表调用工具。请在应用设置中点击 `Refresh`，刷新工具列表，再新建对话、选择该应用，并调用 `list_projects` 验证。

### 友链与致谢

感谢 [LINUX DO](https://linux.do) 社区，我是在这里了解到 WebCodex 的，也因此有了这个项目。

### 许可与第三方组件

本项目独立实现了 Python 服务、配置、启停和任务管理；隧道组件来自 [OpenAI 官方 tunnel-client](https://github.com/openai/tunnel-client)，固定使用 `v0.0.19`。

本项目采用 [MIT License](LICENSE)。第三方组件的信息见 [THIRD_PARTY.md](THIRD_PARTY.md)。

---

<a id="en"></a>

## English

> A heads-up: this is mainly a personal tool, so testing may lag behind. Report bugs through issues or PRs; I'll fix them when I see them :)

Why this exists: my Codex started acting dumb. So I got to work.

The idea is simple: I like small tools that I can start when I need them and shut down when I'm done. Keep the configuration clear and put enough detail in the logs to explain what went wrong. That's enough for me.

This project exposes local files, Git, and command execution through MCP so ChatGPT can work with selected workspaces on your machine. The service is written in Python, and the tunnel uses OpenAI's official `tunnel-client`. Day to day, you use `start.pyw` and `stop.pyw`.

The idea came from [yyjeqhc/webcodex](https://github.com/yyjeqhc/webcodex). Thanks for the inspiration.

### Installation

Download and extract the source, then run it from the project directory. (I'll put together a release ZIP when I have time; it'll run the same way.)

Install Python 3.12 or newer. The Git tool also needs Git installed and available on `PATH`. Installation accesses PyPI and GitHub.

On Windows, open Command Prompt in the project directory and run:

```bat
py -3 install.py
copy secrets.example.yaml secrets.yaml
```

The installer creates a standard `.venv`, installs the dependencies in `requirements.txt`, and downloads the official tunnel client. It verifies the download against the official `SHA256SUMS.txt` and saves its license and provenance under `bin/<platform>/`. The environment, dependency caches, temporary downloads, and runtime logs stay inside the project directory.

On Linux:

```sh
python3 install.py
cp secrets.example.yaml secrets.yaml
chmod 600 secrets.yaml
chmod +x start stop
```

Windows has been tested on a real machine. Linux has launch scripts, file locking, and process-group handling; testing on a Linux machine is still pending. The installer supports x86_64 and ARM64. Local testing used Windows x86_64.

### Get a tunnel ID and API key (first-time setup)

1. Sign in to [OpenAI Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels), select your organization, create a tunnel, and copy its full `tunnel_...` ID.
2. Associate the tunnel with the ChatGPT workspace you plan to use.
3. Open the same organization's [API keys page](https://platform.openai.com/settings/organization/api-keys) and create an API key for running `tunnel-client`.

Creating tunnels requires organization-level `Tunnels Read + Manage`; running the client and selecting a tunnel in ChatGPT requires `Tunnels Read + Use`. If the page shows `Tunnels access required`, ask an organization owner or RBAC administrator for the required permissions. See the [official OpenAI tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Put the tunnel ID and runtime API key in `secrets.yaml`:

```yaml
tunnel_id: tunnel_YOUR_TUNNEL_ID
tunnel_api_key: YOUR_API_KEY
```

Credentials are stored in plain text in `secrets.yaml` on your machine. This tool assumes your machine and user account are secure. Use it with caution if your machine may be compromised.

#### Connect to ChatGPT for the first time

After saving your credentials, start the program by double-clicking `start.pyw` on Windows or running `./start` on Linux. Wait for the local service and tunnel to become ready.

In [ChatGPT Plugins](https://chatgpt.com/plugins), choose `Add custom MCP server`, select `Tunnel` as the connection type, enter the tunnel ID from `secrets.yaml`, and choose `No authentication`. The local tunnel client injects the service's runtime token. After connecting, call `list_projects` to check the configured projects. Access to custom MCP servers depends on your account and workspace settings; see the [official OpenAI connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).

ChatGPT keeps the app connection you added. Reuse that connection for day-to-day use.

If an upgrade leaves the old tool list visible, refresh the tools in the app settings and start a new conversation.

The local MCP endpoint defaults to `http://127.0.0.1:8765/mcp` and uses Bearer authentication. A client connecting directly to this endpoint needs the token from `runtime/instance.yaml`. A new token is generated on each start.

### Day-to-day start and stop

On Windows, double-click `start.pyw`. The launcher waits for the local service and tunnel to become ready, then exits. Starting it again checks and reuses the running instance. Startup failures appear in a dialog, with details under `runtime/`.

Once the service is ready, select the app you already added in your ChatGPT conversation to use its tools.

When you're done, double-click `stop.pyw`. It waits for the service to exit and ends its managed jobs, child processes, and tunnel connection. Project files and logs are kept.

On Linux, use `./start` and `./stop`.

You can also check status or control the service from a terminal:

```sh
python bootstrap.py status
python bootstrap.py start
python bootstrap.py stop
```

### Add a workspace

Add one workspace per entry under `projects` in `config.yaml`. Workspaces can be anywhere on your machine:

```yaml
projects:
  workspace: ./workspace
  demo: 'D:/code/demo'
  notes: '../notes'
```

Create the directories first. Absolute paths are used directly; relative paths are resolved against the directory containing `config.yaml`. `~` expands to the current user's home directory. A Linux absolute path can look like `/home/user/code/demo`. Changes load within one second by default; call `list_projects` to see the resolved absolute workspace paths.

Tool paths can be absolute or relative to the selected workspace, and `..` is resolved normally. Workspaces identify projects and provide default working directories. The `permissions` settings below control file access. `run_python` uses this project's `.venv`.

### Tools and permissions

The default configuration preserves full access under the current operating-system account:

```yaml
permissions:
  read: ['*']
  write: ['*']
  execute: true
```

`read` controls file listing, reading, and searching. `write` controls file creation and editing. `['*']` allows all directories accessible to the account; `[]` disables that category of file access. To allow specific directories and their descendants, put one path per entry. Absolute paths, relative paths, and `~` follow the workspace configuration's resolution rules. Access checks use resolved paths, including targets of symlinks and Windows junctions. Permission directories can be configured independently of `projects`.

For example, allow reading two directories, editing in the first, and disable command execution:

```yaml
permissions:
  read:
    - 'D:/code/demo'
    - '../notes'
  write:
    - 'D:/code/demo'
  execute: false
```

For read-only use, set `write: []` and `execute: false`. Editing an existing file requires read access to that file and its latest SHA-256.

`execute` controls `run_process`, `run_python`, and `git`. Enabled commands inherit the service account's operating-system permissions and can access its files, network, and programs. The `read` and `write` directory rules apply to file tools; command access is governed by the operating system. To confine commands to particular directories, use a dedicated restricted account or an operating-system isolation environment.

`tools` lists an independent switch for every tool, such as `read_file: true` or `git: false`. The effective tool list follows both the switches and `permissions`: disabling execution removes all three execution tools; an empty read or write list removes the corresponding file tools. Calls made from a client's cached tool list still undergo current server-side checks and return explicit errors when denied. `cancel_job` remains available to cancel existing jobs, subject to its own switch.

`read_job` and `list_jobs` control access to job records and output. Those records can contain data read by earlier commands; consider these switches when restricting file tools. `get_status_tool` returns the current permissions, effective tools, and configuration revision. Operation logs record tool names, target paths, configuration revisions, and failure causes.

Read-only, destructive, idempotent, and open-world annotations are generated from actual tool behavior to help clients choose tools and present confirmations. The server enforces tool and path access checks on each call.

The `mcp` fields `name`, `title`, `description`, and `instructions` configure the service name, display title, description, and model instructions. Restart after changing them. After changing tool switches, ChatGPT may need `Refresh` in the app settings followed by a new conversation.

When upgrading from an earlier version, stop the service, add the `permissions`, `tools`, and `mcp` sections from the new `config.yaml` to your configuration, preserve your workspaces and other settings, and start again.

### Configuration and hot reload

Runtime settings live in `config.yaml`, tunnel credentials in `secrets.yaml`, and Python dependencies in `requirements.txt`.

| Change | Behavior |
| --- | --- |
| `projects`, `files`, `permissions`, `tools` | Subsequent tool calls use the validated settings |
| `jobs` | New jobs use the new limits; running jobs keep their original limits |
| `logging.level`, `reload_seconds` | Applied after validation |
| `server`, `tunnel`, `mcp`, log rotation size or count | The service reports the change and stops; start it again to apply it |
| `secrets.yaml` | The service stops; start it again to use the new credentials |
| `requirements.txt` | The service stops; run `python install.py`, then start it again |

Malformed YAML, duplicate keys, unknown fields, and invalid values produce explicit errors. A failed reload stops the service and logs the cause. Stop the service before changing dependencies.

Permission and tool-switch changes apply to subsequent calls. Existing jobs keep running; use `cancel_job` or stop the service to end them.

### Tools

| Purpose | Tools |
| --- | --- |
| Service and projects | `get_status_tool`, `list_projects` |
| Browse and search | `list_files`, `read_file`, `search_text` |
| Create and edit | `write_file`, `replace_text` |
| Background execution | `run_process`, `run_python`, `git` |
| Job management | `read_job`, `list_jobs`, `cancel_job` |

Before editing an existing file, read it and pass the returned full-file SHA-256. Use `next_offset` to continue reading a large file or job output. Binary files support `base64`.

Command tools accept argument arrays and return a job ID. Use `read_job` to check status and output. Terminal states are `succeeded`, `failed`, `timed_out`, `cancelled`, and `interrupted`. On restart, unfinished jobs from the previous service instance are marked `interrupted`. PowerShell commands are rejected.

### Logs and directories

| Path | Contents |
| --- | --- |
| `runtime/service.log` | Service state, configuration reloads, tool calls, and exception tracebacks |
| `runtime/launcher.log`, `runtime/console.log` | Launcher output and startup failures |
| `runtime/tunnel.log`, `runtime/tunnel-console.log` | Official tunnel client logs |
| `runtime/jobs/` | Job status, input, and output |
| `.venv/`, `bin/` | Local Python environment and official tunnel executable |
| `.cache/`, `.tmp/` | Dependency caches and temporary files |
| `workspace/`, `projects/` | Local workspaces |

These runtime directories and `secrets.yaml` are covered by `.gitignore`. The repository includes example credentials only.

### FAQ

#### Q1: The program is running and ChatGPT is connected. Why do tool calls still fail?

ChatGPT may have cached the old tool definitions and may still use them after an update. Open the app settings and click `Refresh`, then start a new conversation, select the app, and call `list_projects` to verify the connection.

### Community and thanks

Thanks to the [LINUX DO](https://linux.do) community, where I discovered WebCodex and got the inspiration for this project.

### License and third-party components

The Python service, configuration, lifecycle, and job management are independently implemented. The tunnel component comes from [OpenAI's official tunnel-client](https://github.com/openai/tunnel-client), pinned to `v0.0.19`.

This project uses the [MIT License](LICENSE). Third-party details are in [THIRD_PARTY.md](THIRD_PARTY.md).
