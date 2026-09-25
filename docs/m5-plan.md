# M5：基于 smolagents 变种的单 Agent 有界修复闭环方案

状态：M5 已完成。2026-09-20 使用真实 DeepSeek 工具调用模型及真实
MatIEC/OpenPLC Runtime 完成端到端验收。

编写依据：仓库当前的 M0-M4 实现、`docs/architecture.md`、`plc_tools/` 公开契约，以及仓库内 `smolagents` 源码（当前版本标记为 `1.27.0.dev0`）。

## 1. M5 要解决的具体问题

“根据现有架构，对 smolagent 进行变种”不能直接作为开发要求，因为它没有说明：

- Agent 接收什么输入、返回什么结果；
- LLM 负责哪些工作，确定性代码负责哪些工作；
- 候选 ST 如何进入 MatIEC/OpenPLC；
- 什么时候算编译成功，什么时候算行为成功；
- 编译错误和行为错误如何反馈给 LLM；
- 修复循环最多执行多少次；
- 没有 LLM 凭据、运行时不可用、模型输出不合法时如何失败；
- 如何证明 M5 使用了真实 LLM，而不是 mock 或固定答案；
- `smolagents` 的通用能力如何被限制在 PLC-Agent 的架构边界内。

因此，本方案把 M5 定义为一个可以测试、可以失败、可以验收的产品能力：

> 给定一条自然语言 PLC 需求，单个真实 LLM Agent 生成 IEC 61131-3 Structured Text 和可执行行为测试计划；系统使用已有的 `plc_tools` 进行真实检查、编译、启动和行为验证；如果失败，向同一个 Agent 提供结构化反馈，在固定次数内修复候选程序；只有真实行为验证通过，M5 才返回成功。

M5 不是通用编程 Agent，不是聊天机器人，不是多 Agent 系统，也不是只把 `smolagents` 的示例代码接到 CLI 上。

## 2. 当前基线和必须遵守的边界

### 2.1 当前仓库已有能力

- `plc_tools.check_st_text()`：对内存中的 ST 文本调用真实 MatIEC 检查，并返回结构化诊断；
- `plc_tools.compile_st()`：调用 MatIEC、生成并上传运行时程序，并等待真实 OpenPLC Runtime 的 GCC/link 结果；
- `plc_tools.start_plc()` / `stop_plc()`：控制真实运行时；
- `plc_tools.verify_plan()`：对已运行的程序执行输入 force、等待扫描周期、读取输出、比较期望值，并在 `finally` 中释放 force；
- `runtime/`：封装 MatIEC、Docker、OpenPLC REST 和 Socket.IO/debug 协议；
- `smolagents/`：仓库内已有的 smolagents 源码副本，可作为 M5 Agent 框架依赖；
- `problems/problem_001/`：现有的电机启停行为问题，可作为第一个端到端验收场景。

仓库 README 已记录 M0-M4 已完成，M5 尚未开始，并且当前环境没有可用于验收的模型凭据。没有真实模型凭据时，可以进行单元测试和契约测试，但不能宣称 M5 已完成。

### 2.2 代码分层

```text
自然语言需求
      |
      v
agent/                         M5 专用 Agent、提示词、循环控制、结果汇总
      |
      v
plc_tools/                     稳定的 PLC 工具契约
      |
      v
runtime/                       MatIEC、Docker、OpenPLC 的实现细节
```

必须满足：

1. `agent/` 不得导入 `runtime.openplc`、`runtime.matiec`，不得拼接 Docker 命令、REST URL、Socket.IO 命令或 MatIEC 命令行参数。
2. Agent 只允许调用 `plc_tools` 的公开接口。
3. LLM 不得直接读写项目文件，不得使用 `PythonInterpreterTool`，不得执行任意 Python、Shell 或 Docker 命令。
4. M5 只实现一个 Agent；不引入 managed agents、RAG、数据库、UI 或多 Agent 编排。
5. 本仓库的 M5 开发不能读取、引用或复用 TIA Portal、Siemens Openness、PLCSIM 或 Windows GUI 自动化的旧项目。

## 3. smolagents 变种的选择

### 3.1 采用 `ToolCallingAgent`，不采用 `CodeAgent`

`smolagents` 当前提供 `MultiStepAgent`、`ToolCallingAgent` 和 `CodeAgent`。M5 应基于 `ToolCallingAgent` 做 PLC 专用变种，理由是：

- PLC 工具调用本身已经是明确的结构化输入输出；
- 模型可以通过 function/tool call 提交 ST 和测试计划；
- 不需要让模型生成并执行 Python；
- 可以限制工具集合、每次只允许一次候选评估，并记录每次工具调用；
- 更容易把编译诊断和行为验证失败转换成下一轮修复反馈。

`CodeAgent` 的 Python 执行能力与 M5 的安全边界不匹配，不能因为它更容易拼接字符串而使用它。

### 3.2 变种不是复制 smolagents 全部源码

优先在项目侧实现适配和子类，不修改 `smolagents/src/smolagents/` 的通用行为。建议的逻辑结构如下：

```text
agent/
  __init__.py
  contracts.py              M5 请求、候选、尝试记录、最终结果
  model.py                  真实模型配置和凭据校验
  prompts.py                PLC 专用 system prompt 和反馈模板
  tools.py                  smolagents Tool -> plc_tools 的适配器
  plc_agent.py              PLCToolCallingAgent 和 PLCRepairAgent
```

其中：

- `PLCToolCallingAgent` 是 `smolagents.ToolCallingAgent` 的专用子类，负责工具集合、提示词和工具调用限制；
- `PLCRepairAgent` 是对外的项目级入口，负责 M5 请求、运行次数、候选历史和最终 `M5Result`；
- 若确实发现当前 vendored smolagents 缺少必要扩展，才允许做最小、可记录的框架补丁；补丁必须带单元测试，且不得改变通用 Agent 的默认语义。

## 4. M5 对外契约

实现前先固定以下概念契约，避免让模型输出格式反过来决定系统架构。

### 4.1 请求

概念上定义 `M5Request`：

```text
task: str                         必填，自然语言 PLC 需求
max_attempts: int = 3             候选评估上限，包含第一次生成
source_filename: str = "candidate.st"
max_actions: int = 8              模型动作上限，独立于候选评估次数
```

约束：

- `task` 不能为空；
- `max_attempts` 只允许在 1 到 3 之间，默认 3；不能由模型动态增加；
- 需求必须包含可观察的输入、输出和行为。若只有“写一个程序”但没有可验证的输出，Agent 应返回 `unverifiable_requirement`，不能自行声称成功；
- M5 可以让 LLM 从自然语言中生成测试计划，也可以在未来扩展为用户显式提供测试计划，但本阶段不要求第二个规划 Agent。

### 4.2 候选程序

每次候选必须包含：

```text
st_code: str                       完整、可编译的 ST 文本
verification_plan: object          与 plc_tools.verify_plan 兼容的计划
summary: str                      对本次候选的简短说明，可选
```

`verification_plan` 至少满足现有 `plc_tools.verify_plan()` 的格式：

```json
{
  "steps": [
    {
      "inputs": {"Start": false, "Stop": false},
      "expected": {"Motor": false},
      "settle_ms": 50
    }
  ]
}
```

要求：

- `st_code` 必须是完整程序，不接受只包含片段的 patch；
- 测试计划必须能实际 force/read 变量；
- 测试计划不能引用不存在的变量；
- 计划至少覆盖需求中明确的关键分支；
- Agent 不能因为模型没有写测试计划而跳过行为验证；
- 系统不把模型的 `summary` 当作正确性证据。

### 4.3 最终结果

概念上定义 `M5Result`：

```text
success: bool
failure_kind: str | null
st_code: str | null
verification_plan: object | null
attempts: list[AttemptRecord]
final_message: str
model: {provider, model_id} | null
state: str | null
```

每条 `AttemptRecord` 至少包含：

```text
attempt: int
st_code_digest: str
phase: "check" | "compile" | "start" | "verify" | "accepted" | "failed"
check_result: object | null
compile_result: object | null
start_result: object | null
verify_result: object | null
feedback: object
accepted: bool
```

结果规则：

- 只有 `verify_result.passed == true` 才能令 `success == true`；
- LLM 返回“看起来正确”、MatIEC 编译成功、OpenPLC 启动成功，都不能单独令 M5 成功；
- 达到次数上限后必须返回失败结果，不能静默重试；
- 结果中不能输出 API key、Authorization header、完整请求凭据或其他秘密；
- 失败也必须保留可诊断的阶段、错误类型和尝试历史。

建议的 `failure_kind`：

```text
invalid_request
model_unavailable
model_authentication_failed
model_connection_failed
model_tool_unsupported
model_context_exceeded
model_output_invalid
candidate_check_failed
candidate_compile_failed
runtime_start_failed
behavior_verification_failed
unverifiable_requirement
attempt_limit_reached
runtime_busy
agent_reported_failure
action_limit_reached
```

## 5. Agent 工具设计

### 5.1 暴露给 LLM 的工具

M5 对模型暴露一个候选评估工具、三个非成功控制动作，以及
smolagents 内置的最终回答工具：

```text
evaluate_candidate(
    st_code: str,
    verification_plan: object,
    summary: str | null
) -> structured result
ask_user(question) -> needs_user_input
report_unverifiable(reason) -> unverifiable
report_failure(reason) -> fatal_failure
```

不暴露以下能力：

- 文件读写工具；
- Python 解释器；
- Shell、Docker、HTTP、浏览器；
- `force_variables` 和 `read_variables` 的直接调用；
- 多 Agent 工具；
- 任意用户自定义工具。

这样可以让“候选程序是否成功”只能由统一评估器判定，不让模型自行拼出一条绕过行为验证的路径。

### 5.2 `evaluate_candidate` 的确定性执行顺序

工具内部只能通过 `plc_tools` 调用，顺序固定为：

1. 校验输入类型、文本长度、测试计划结构和尝试次数；
2. 调用 `check_st_text(st_code, filename=...)`，失败时返回结构化 MatIEC 诊断；
3. 将 ST 文本写入受控临时目录中的临时 `.st` 文件；
4. 调用 `compile_st(temp_source)`，该过程必须得到真实 MatIEC 成功和真实 Runtime GCC/link 成功；
5. 调用 `start_plc()`，确认真实运行时进入 `RUNNING`；
6. 调用 `verify_plan(verification_plan)`，获取真实扫描周期中的 expected/actual 结果；
7. 无论验证成功还是失败，都调用 `stop_plc()`，并记录停止失败；
8. 只有第 6 步 `passed == true` 且清理没有产生致命错误时，返回 `accepted == true`。

如果第 2 步或第 4 步失败，不启动运行时；如果第 5 步失败，不调用行为验证；如果第 6 步失败，必须返回失败步骤、变量名、expected、actual 和原因。

### 5.3 运行时安全策略

- M5 启动前读取 `get_plc_status()`；若已有不属于当前 M5 会话的程序处于 `RUNNING`，返回 `runtime_busy`，不直接停止用户程序；
- M5 自己启动的运行时必须在 `finally` 中停止；
- `verify_plan()` 已有 force 清理逻辑，M5 不能绕过它；
- 候选源文件使用 UTF-8、唯一临时目录和自动清理；
- 单次 ST 文本、测试步骤数、诊断文本和工具输出都设置上限，防止模型无限放大上下文；
- 同一时刻只允许一个候选评估，禁止并发 compile/start/verify；
- 工具失败不能伪造空的成功结果；
- 任何真实工具错误都要进入 `feedback`，并区分“候选错误”和“环境不可用”。

## 6. 有界修复循环

### 6.1 循环定义

默认最多 3 次候选评估：

```text
第 1 次：根据自然语言需求生成初始 ST + 测试计划
第 2 次：根据检查/编译/行为反馈修复候选
第 3 次：再次修复并验证
结束：通过、达到上限、或发生不可恢复的模型/环境错误
```

`max_attempts` 是进入真实 PLC 评估链的候选次数，不是任意 LLM
请求次数。结构错误不消耗候选次数。模型动作由独立的 `max_actions`
硬上限约束，默认为 8。

### 6.2 单步限制

需要在 `PLCToolCallingAgent` 中实现并测试以下限制：

- 一次 action 最多一个工具调用；
- `evaluate_candidate` 调用后必须等待其观察结果，不能并行调用多个评估；
- 候选评估次数达到上限后，拒绝新的候选提交；
- 只有进入 `accepted`、`needs_user_input`、`unverifiable`、`fatal_failure`
  或 `exhausted` 终止状态时才允许 `final_answer`；
- 模型不能通过普通文本输出绕过工具调用直接宣布成功；
- `max_steps`、`max_attempts`、工具输入大小和每个真实工具的 timeout 都由宿主代码设定，模型不能修改。

### 6.3 反馈格式

反馈必须短、结构化、可定位，不能把整个运行时日志无条件塞回上下文：

```json
{
  "accepted": false,
  "failure_kind": "behavior_verification_failed",
  "phase": "verify",
  "diagnostics": [],
  "failed_steps": [
    {
      "step": 2,
      "variable": "Motor",
      "expected": true,
      "actual": false,
      "reason": "value mismatch"
    }
  ],
  "next_action": "提交完整修复后的 st_code 和 verification_plan，不要只提交解释。"
}
```

反馈规则：

- MatIEC 失败：优先提供文件名、行、列、source line、message；
- Runtime GCC 失败：提供 `failed_stage`、有限长度的日志和 `tool_error`；
- 行为失败：提供失败步骤及 expected/actual；
- 运行时配置问题：明确标记为环境失败，不诱导模型反复修改 ST；
- 任何日志都要截断到固定长度并清理可能的秘密。

## 7. PLC 专用提示词要求

提示词不是实现细节，而是 M5 正确性的组成部分。`agent/prompts.py` 至少应包含以下规则：

1. 你是单个 PLC Structured Text 修复 Agent，只能通过 `evaluate_candidate` 提交候选。
2. 输出必须符合 MatIEC/OpenPLC 当前支持的 IEC 61131-3 Structured Text 方言。
3. 候选必须是完整 ST 程序，包括必要的 `PROGRAM`、变量声明、逻辑和配置/task 结构。
4. 需要被 force/read 的输入输出必须使用可定位的 `%I`/`%Q` 变量；变量名必须与测试计划一致。
5. 测试计划必须描述输入和期望输出，且必须覆盖需求关键分支。
6. 编译成功不等于行为正确；必须等待 `evaluate_candidate` 的验证结果。
7. 收到失败反馈后，提交完整修复版本，不提交 diff，不调用未提供的工具。
8. 不得讨论或使用 Docker、MatIEC 命令行、OpenPLC REST、Socket.IO 或文件系统细节。
9. 如果自然语言需求缺少可观察行为，返回无法验证的结果，而不是编造成功。

提示词中应明确告诉模型：工具观察结果是唯一的编译/运行/行为证据，模型的自我判断不是证据。

## 8. 真实模型接入要求

### 8.1 参考实现

优先使用 `smolagents.OpenAIModel` 连接一个真实的 OpenAI-compatible Chat Completions API，因为当前 smolagents 已经支持：

- `model_id`；
- `api_base`；
- `api_key`；
- tool schema；
- tool call 结果解析。

可以把 `InferenceClientModel` 或 `LiteLLMModel` 作为后续兼容选项，但 M5 首次验收只需要一个真实、稳定、支持 tool calling 的 provider，并且必须记录实际使用的 provider 和 model id。

### 8.2 配置和秘密

模型工厂应从环境变量或显式配置读取信息，不把秘密写入代码、文档、测试 fixture 或结果文件。建议最小配置字段：

```text
PLC_AGENT_MODEL_PROVIDER=openai
PLC_AGENT_MODEL_ID=<provider-specific-model>
PLC_AGENT_API_KEY=<secret from environment>
PLC_AGENT_API_BASE=<optional OpenAI-compatible endpoint>
PLC_AGENT_MAX_ATTEMPTS=3
PLC_AGENT_MODEL_TIMEOUT=<bounded timeout>
```

实际变量名可以调整，但必须满足：

- 缺少凭据时尽早返回 `model_unavailable`；
- 不使用隐式 mock、固定候选、离线假模型代替真实调用；
- 单元测试可以用 fake `Model` 测循环控制，但 fake 测试不能被当作 M5 集成验收；
- 日志只记录 provider/model id 和 token usage，不记录 key。

### 8.3 smolagents 依赖方式

仓库没有根目录 `pyproject.toml`，而 `smolagents` 自身位于 `smolagents/`。实现阶段必须明确一种可重复的导入方式，例如将 `smolagents` 以 editable package 安装，或在项目测试入口显式加入 `smolagents/src`；不能依赖开发者机器上的偶然 `PYTHONPATH`。

依赖安装和启动方式必须写入 README，并在干净环境中验证。没有安装 `openai`/`litellm` 依赖时，应返回清晰配置错误，而不是在 Agent 运行中间崩溃。

## 9. CLI 和项目入口

M5 不需要 UI，但应提供一个最小 CLI 入口，建议在现有 `main.py` 增加 `agent` 子命令：

```text
python main.py agent "当 Start 为真且 Stop 为假时启动 Motor，Stop 为真时关闭 Motor"
```

建议参数：

```text
--max-attempts 1..3
--model-id <id>
--provider <provider>
--requirement-file <path>
--json
```

CLI 要求：

- 成功时输出结构化的 `M5Result`，包含最终 ST、测试计划和尝试摘要；
- 失败时仍输出结构化失败结果；
- 退出码区分成功、候选/行为失败、配置/环境失败和参数错误；
- CLI 不直接调用 `runtime/`，只调用 `agent/` 对外入口；
- 不打印 API key 或完整模型请求。

## 10. 实施分阶段计划

### 阶段 A：契约和依赖基线

- 新建 `agent/` 包和 M5 数据契约；
- 确认 `smolagents` 的可重复导入/安装方式；
- 增加配置读取和凭据预检；
- 为成功、失败、工具错误、次数上限建立结构化结果。

交付物：没有模型调用时也能通过的契约测试和配置错误测试。

### 阶段 B：PLC 工具适配器

- 实现 `evaluate_candidate` 的 Tool schema；
- 实现固定的 check -> compile -> start -> verify -> stop 顺序；
- 实现临时文件清理、运行时 busy 检查、timeout 和输出截断；
- 确保所有真实调用都经 `plc_tools`。

交付物：使用已有测试桩/patch 验证调用顺序、短路规则和清理规则；不把这些测试称为真实运行时验收。

### 阶段 C：smolagents PLC 变种

- 基于 `ToolCallingAgent` 创建 `PLCToolCallingAgent`；
- 注入 PLC 专用 prompt；
- 注册 `evaluate_candidate`、三个控制动作和内置 `final_answer`；
- 禁止并发工具调用、任意 Python 工具和多 Agent；
- 用 `final_answer_checks` 或等价宿主检查阻止未验证候选被宣布成功。

交付物：fake model 单元测试能证明初始候选、修复候选、通过候选和超限候选的状态转移。

### 阶段 D：项目级修复循环和 CLI

- 实现 `PLCRepairAgent` 的对外入口；
- 分别固定 `max_attempts` 和 `max_actions`；
- 汇总每次尝试和最终结果；
- 增加 `main.py agent` 入口；
- 更新 README 的 M5 使用、依赖、凭据和失败说明。

交付物：无真实凭据时可以看到明确的 `model_unavailable`，不会误报成功。

### 阶段 E：真实端到端验收

- 配置真实支持 tool calling 的 LLM API；
- 启动/准备真实 MatIEC 和 OpenPLC Runtime；
- 使用 `problem_001` 的自然语言需求，让 Agent 生成 ST 和测试计划；
- 真实执行 MatIEC、Runtime GCC/link、OpenPLC scan cycle 和 `verify_plan`；
- 保存不含秘密的 M5 运行摘要，包括 model id、尝试次数、各阶段结果、最终验证结果；
- 只有该流程通过后，才更新 README 为“M5 complete”。

## 11. 测试和验收标准

### 11.1 单元/契约测试

至少覆盖：

- 空需求、非法 `max_attempts`、超长 ST、非法测试计划；
- MatIEC 检查失败时不触发 compile/start/verify；
- compile 失败时不触发 start/verify；
- start 失败时不触发 verify；
- verify 失败时返回 expected/actual 和修复反馈；
- verify 成功才设置 `accepted`；
- 每个候选只计一次 attempt；
- 达到上限后拒绝额外候选；
- Agent 不能直接调用未知工具；
- 多工具并发调用被拒绝；
- 运行时异常时仍执行 stop/force 清理；
- 结果和日志不包含模型凭据；
- `agent/` 源码不导入 `runtime`，不包含 Docker/REST/Socket.IO 细节。

### 11.2 真实 Runtime 集成测试

在已有 M1-M4 集成测试基础上增加 M5 专项测试，必须使用真实运行时：

1. 候选程序真的被 MatIEC 检查；
2. 候选程序真的经过 Runtime GCC/link；
3. 程序真的进入 `RUNNING`；
4. 测试计划真的 force 输入并读取输出；
5. 失败候选不会被标记为成功；
6. 每次尝试结束后运行时和 force 状态被清理。

### 11.3 真实 LLM 集成测试

真实 LLM 测试必须是显式 opt-in，例如 `PLC_AGENT_INTEGRATION=1`，且凭据缺失时只能 skip 或返回配置失败，不能自动换成 mock。

最低验收场景：

- 输入 `problem_001` 对应的自然语言需求；
- 模型输出完整 ST 和行为测试计划；
- 最终结果 `success == true`；
- `attempts` 至少包含一次真实候选评估；
- `verify_result.passed == true`；
- 真实 Runtime 在验证后被停止。

如果要证明“修复”而不只是“首次生成成功”，还需要一个真实 LLM 场景使第一版候选产生可观察的编译或行为失败，并在剩余次数内修复通过。仅用 FakeModel 证明循环逻辑，不能作为这条验收的替代品。

### 11.4 M5 完成判定

必须同时满足：

- 使用真实支持 tool calling 的 LLM API；
- 具备可重复的模型配置和依赖安装方式；
- Agent 只通过 `plc_tools` 访问 PLC 能力；
- 候选评估次数严格有界；
- 编译和行为验证均来自真实 MatIEC/OpenPLC；
- 失败和清理行为有测试证据；
- 至少一个真实 LLM + 真实 Runtime 的端到端场景通过；
- README、测试结果和 M5 方案中的状态一致。

以下情况不能宣称 M5 完成：

- 只使用 mock model；
- 只验证 LLM 生成了 ST 文本；
- 只通过 MatIEC 编译而没有行为验证；
- 只启动 Runtime 而没有 expected/actual 行为断言；
- 允许 Agent 使用 Python/Docker/REST 绕过 `plc_tools`；
- 没有凭据时用固定答案或示例程序代替真实 LLM。

## 12. 风险和处理决定

### 风险一：模型支持 tool calling 不稳定

M5 首次只支持一个经过实际验证的 provider/model 组合。模型工厂必须在启动前校验配置，工具解析错误进入 `model_output_invalid`，不得无限重试。

### 风险二：OpenPLC 是全局运行时

运行时 busy 检查、串行候选评估和 `finally` 清理是硬性要求。M5 不应偷偷停止不属于当前会话的运行程序。

### 风险三：模型生成的测试计划可能与需求不一致

系统只能验证“模型提交的可观察断言”，不能证明模型完全理解了自然语言。M5 应要求 prompt 生成覆盖关键分支，并在结果中保留测试计划；更强的需求覆盖分析属于后续里程碑，不在 M5 内虚构。

### 风险四：编译成功但逻辑错误

这是 M5 必须解决的核心问题。任何成功路径都必须经过 `verify_plan`，并将 expected/actual 作为最终正确性证据。

### 风险五：vendored smolagents 与项目依赖冲突

优先采用项目侧适配和子类；若必须修改 smolagents，固定改动范围、记录原因、增加针对性测试，并保证现有 smolagents 测试和项目 M0-M4 测试不回归。

## 13. 本方案的最终实现形态

完成 M5 后，调用关系应接近：

```text
main.py agent
    |
    v
PLCRepairAgent.run(task)
    |
    v
PLCToolCallingAgent(ToolCallingAgent)
    |
    |  real LLM tool call: evaluate_candidate(st_code, verification_plan)
    v
evaluate_candidate adapter
    |
    +--> plc_tools.check_st_text
    +--> plc_tools.compile_st
    +--> plc_tools.start_plc
    +--> plc_tools.verify_plan
    +--> plc_tools.stop_plc
    |
    v
structured observation -> bounded repair -> accepted/failure M5Result
```

这个形态保留了 smolagents 的模型、消息、工具调用和记忆能力，但把 PLC 的正确性、运行时安全和有界性放回项目自己的 `agent/` 与 `plc_tools/` 契约中。它才是“根据现有架构对 smolagents 做变种”，而不是把一个通用 Agent 示例直接改名为 PLC-Agent。

## 14. 当前执行状态

已落地的实现包括：

- `agent/`：M5 请求/结果契约、真实模型配置、PLC prompt、`ToolCallingAgent` 变种和 `PLCRepairAgent`；
- `evaluate_candidate`：串行执行 check -> compile -> start -> verify -> stop，并保存结构化尝试记录；
- `main.py agent`：自然语言需求入口和结构化 JSON 结果；
- `requirements-m5.txt`：仓库内 smolagents 和 OpenAI 模型依赖；
- M5 单元/契约测试、真实 Runtime 适配器测试和真实 LLM opt-in 测试。

当前证据：

- 本地全量测试：51 项运行，44 项通过，7 项按环境条件跳过；
- 在 Docker 授权环境中，M1-M4 真实 MatIEC/OpenPLC 集成测试 5/5 通过；
- 在同一真实 Runtime 中，M5 `CandidateEvaluator` 对 `problem_001` 的真实 check、compile、start、verify、stop 链路通过；
- 2026-09-20，真实 `deepseek-flash` 工具调用模型生成完整 ST 和五步验证计划；候选通过真实 MatIEC 检查、OpenPLC GCC/link、真实扫描周期与五项行为断言，并在结束时成功停止 Runtime。M5 真实 LLM + 真实 Runtime 集成测试通过。

## 15. P0 状态机和协议收口

2026-09-21 完成首轮交互内核收口，不改变 `agent -> plc_tools -> runtime`
边界：

- 引入宿主控制的运行状态，区分 `needs_user_input`、`accepted`、
  `unverifiable`、`fatal_failure` 和 `exhausted` 等结果；
- 增加 `ask_user`、`report_unverifiable` 和 `report_failure` 控制动作，
  模型不再需要伪造候选才能合法结束；
- `max_actions` 独立限制模型动作，`max_attempts` 只计结构合法并进入真实
  PLC 评估链的候选；
- 空 ST、超长 ST 和非法验证计划会被标记为 `submission_rejected`，
  不消耗 PLC 候选次数；
- 保留 `agent.run()` 的最终说明，并细分鉴权、连接、上下文和工具支持错误。

当前验证证据：全量测试 51 项，44 项通过，7 项按环境条件跳过；
P0 后的 `CandidateEvaluator` 再次通过真实 MatIEC/OpenPLC
check -> compile -> start -> verify -> stop 链路，结束后 Runtime 状态为
`STOPPED`。

## 16. P1 需求理解与候选预检

2026-09-21 在 P0 协议上加入两道宿主门禁，继续保持
`agent -> plc_tools -> runtime` 边界：

- `RequirementSpec` 保存目标、输入、输出、时序、状态、安全、可观察断言、
  假设和开放问题；信息不足时先集中追问，不接触 Runtime；
- `submit_requirement_spec` 是候选生成前的结构化需求入口；
- `validate_candidate` 检查 ST/验证计划结构并调用真实 `check_st_text`，不启动
  Runtime，也不消耗 `max_attempts`；
- `evaluate_candidate` 只接受与最近一次成功预检完全相同的 ST 和验证计划，
  并继续作为唯一成功判定来源；
- Runtime 状态由宿主在编译前检查；busy 或状态工具失败不会消耗真实候选次数，
  也不会停止已有程序；
- `max_actions` 与 `max_attempts` 保持独立，语法修复只消耗动作预算。

P1 调用顺序为：

```text
自然语言 -> RequirementSpec -> 追问或生成
         -> validate_candidate: check
         -> evaluate_candidate: runtime preflight -> compile -> start -> verify -> stop
```

## 17. P2 进程内会话与过程事件

`PLCSession` 提供 `submit()`、`resume()`、`cancel()`；每轮创建新的有界 Agent，
但保留 RequirementSpec、最近一次已验证 ST/计划、真实验证证据、用户明确确认的
假设和最多六份短 Turn 摘要。不无限追加完整聊天记录，不引入数据库。

`PLCEvent` callback 与 UI 无关，覆盖需求分析、等待用户、候选生成、预检、编译、
运行、逐步验证、修复、验收/失败和清理。现有一次性 JSON CLI 保持可用。

取消是协作式的：正在进行的外部工具调用先返回，验证循环随后中断；
`verify_plan` 在 `finally` 中释放已强制的变量，Agent 随后停止自己启动的
Runtime。清理失败会使候选无法验收。

真实 Runtime 验收覆盖了同一会话中对已验证电机程序增加 Enable 输入并
重新验证、10 秒 TON 定时改为 5 秒后重新验证，以及运行中取消后的变量
释放和 Runtime 停止。定时器验证使用相对前一步输入生效后的 `settle_ms`：
10 秒版在 7.5 秒时保持关闭、后续开启；5 秒版在 7.5 秒时已开启。
此前按 `time_ms` 从验证开始累计等待，会把真实 force/read 耗时误计入
定时窗口，曾产生 expected/actual 失败；该测试计划已修正。
