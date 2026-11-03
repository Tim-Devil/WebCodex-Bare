# 第三方组件

本项目自身的 Python 代码采用 MIT License。安装时获取的第三方软件遵循各自的许可证。

## 官方隧道客户端

- 项目：[openai/tunnel-client](https://github.com/openai/tunnel-client)
- 固定版本：[v0.0.19](https://github.com/openai/tunnel-client/releases/tag/v0.0.19)
- 完整性校验：发布附件中的 `SHA256SUMS.txt`
- 安装记录：`bin/<平台>/provenance.yaml`
- 上游许可证和声明：下载时一并保存到 `bin/<平台>/` 的 `LICENSE`、`NOTICE` 等文件

仓库分发安装代码，客户端可执行程序由 `install.py` 从上述官方发布地址下载。

## Python 依赖

直接依赖和固定版本见 `requirements.txt`。各组件的许可证随其 Python 安装包提供。

| 组件 | 上游 |
| --- | --- |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| PyYAML | https://github.com/yaml/pyyaml |
| psutil | https://github.com/giampaolo/psutil |
| HTTPX | https://github.com/encode/httpx |
| Uvicorn | https://github.com/encode/uvicorn |
| Pydantic | https://github.com/pydantic/pydantic |
| Starlette | https://github.com/encode/starlette |

pip 会同时安装这些包所需的间接依赖，对应许可保留在各自安装包内。
