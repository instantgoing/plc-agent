你现在要从零开始创建一个全新的项目：

```text
plc-agent
```

这是一个独立项目。

不要读取、迁移、兼容或继承以前基于：

- TIA Portal V17
- Siemens Openness
- PLCSIM
- Windows GUI 自动化

的旧 PLC-Agent。

新的项目从架构层面完全独立。

---

# 1. 项目最终目标

实现一个跨平台 PLC 编程 Agent：

```text
自然语言 PLC 任务
        ↓
理解控制需求
        ↓
生成 IEC 61131-3 Structured Text
        ↓
编译检查
        ↓
运行 PLC 程序
        ↓
自动设置输入
        ↓
读取输出
        ↓
验证行为
        ↓
失败
   ↙         ↘
分析原因      修改 ST
   ↘         ↙
      再次测试
        ↓
      PASS
```

最终用户应该能够输入：

```text
按下启动按钮后电机启动，
按下停止按钮后电机停止。
```

PLC-Agent 自动完成：

```text
需求分析
→ ST 编程
→ 编译
→ 运行
→ 测试
→ 修复
→ 最终输出
```

用户不需要安装 TIA Portal。

---

# 2. 核心技术路线

核心使用：

```text
IEC 61131-3 Structured Text
        ↓
      MatIEC
        ↓
       C
        ↓
      GCC
        ↓
OpenPLC Runtime
```

MatIEC：

https://github.com/beremiz/matiec

OpenPLC Runtime：

https://github.com/Autonomy-Logic/openplc-runtime

MatIEC 是 IEC 61131-3 编译器。

主要负责：

```text
ST
↓
语法分析
类型检查
语义检查
↓
C
```

OpenPLC Runtime 负责：

```text
PLC scan cycle
输入
程序执行
输出
变量状态
```

---

# 3. 开发前必须研究已有项目

禁止立即从零实现。

首先研究：

https://github.com/midea-ai/SemaPLC

这是本项目最重要的参考项目。

重点阅读：

```text
sema-plc-tools/
```

研究这些工具：

```text
plc_check
plc_compile
plc_buildAndRun
plc_readVariables
plc_forceVariables
plc_trace
plc_verify
```

搞清楚完整流程：

```text
ST
↓
MatIEC
↓
C
↓
GCC
↓
OpenPLC Runtime
↓
force input
↓
read / trace variables
↓
behavior verification
```

特别注意：

OpenPLC Runtime 当前 main 工具链已经发生变化。

SemaPLC 为继续使用 MatIEC，
固定了兼容 MatIEC 的 OpenPLC Runtime 版本。

不要假设 OpenPLC Runtime 当前 main 可以直接和 MatIEC 配合。

先研究 SemaPLC 使用的：

```text
OpenPLC commit
Dockerfile
build-matiec-base.sh
编译流程
REST API
```

然后决定：

A. 直接复用 sema-plc-tools

或者：

B. 提取其中必要实现

或者：

C. 在其架构基础上实现更简洁的工具层

优先 A/B。

禁止无意义重复造轮子。

---

# 4. 第一版只支持 ST

第一版只支持：

```text
IEC 61131-3 Structured Text
```

暂时不支持：

```text
Ladder Diagram
FBD
SFC
Siemens SCL extensions
TIA Portal
硬件组态
PLC 下载
```

目标是先把：

```text
自然语言
→ ST
→ 编译
→ Runtime
→ 自动测试
```

彻底跑通。

---

# 5. 项目架构

建议从以下结构开始：

```text
plc-agent/

├── agent/
│   ├── agent.py
│   ├── loop.py
│   ├── prompts.py
│   └── state.py
│
├── plc_tools/
│   ├── check.py
│   ├── compile.py
│   ├── runtime.py
│   ├── variables.py
│   ├── trace.py
│   └── verify.py
│
├── problems/
│
├── tests/
│
├── runtime/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── scripts/
│
├── examples/
│
├── docs/
│   └── architecture.md
│
├── AGENTS.md
└── README.md
```

结构可以根据实际情况调整。

不要为了符合目录而过度设计。

---

# 6. PLC 工具层

Agent 不直接操作 Docker、MatIEC 或 OpenPLC。

统一通过 PLC Tools。

至少实现：

## plc_check

```text
ST
↓
MatIEC
↓
检查是否存在编译错误
```

返回结构化结果：

```json
{
  "success": false,
  "errors": [
    {
      "line": 12,
      "message": "..."
    }
  ]
}
```

---

## plc_compile

完成：

```text
ST
→ MatIEC
→ C
→ GCC
→ Runtime 可运行程序
```

---

## plc_start

启动 PLC Runtime。

---

## plc_stop

停止 PLC Runtime。

---

## plc_force_variables

例如：

```json
{
  "Start": true,
  "Stop": false
}
```

---

## plc_read_variables

例如：

```json
[
  "Motor",
  "Alarm"
]
```

返回实际变量值。

---

## plc_trace

对变量进行连续采样。

例如：

```text
Start
Motor
Timer.Q
Counter.CV
```

用于验证：

- Timer
- Counter
- 状态机
- 顺序控制

---

## plc_verify

输入一个测试计划：

```json
{
  "steps": [
    {
      "time_ms": 0,
      "inputs": {
        "Start": false
      },
      "expect": {
        "Motor": false
      }
    },
    {
      "time_ms": 100,
      "inputs": {
        "Start": true
      },
      "expect": {
        "Motor": true
      }
    }
  ]
}
```

返回：

```json
{
  "passed": true,
  "failures": []
}
```

这是项目最核心的工具之一。

---

# 7. Agent Loop

Agent 必须使用明确的闭环。

```text
用户需求
↓
分析需求
↓
确定 inputs / outputs / states
↓
生成 ST
↓
plc_check
```

如果编译错误：

```text
读取真实错误
↓
分析
↓
修改 ST
↓
重新 plc_check
```

通过后：

```text
plc_compile
↓
plc_start
↓
plc_verify
```

如果行为错误：

```text
expected
vs
actual
↓
读取 trace
↓
定位逻辑错误
↓
修改 ST
↓
重新验证
```

直到：

```text
PASS
```

设置：

```text
MAX_ITERATIONS
```

例如：

```text
10
```

防止无限循环。

---

# 8. 必须区分两种正确性

绝对不能：

```text
编译成功
=
程序正确
```

这是错误的。

必须分成：

```text
Compiler Verification

语法
类型
符号
编译
```

和：

```text
Behavior Verification

输入变化
时间变化
状态变化
输出结果
```

最终：

```text
Compile PASS
+
Behavior PASS

才算成功。
```

---

# 9. 题目系统

建立：

```text
problems/
```

每道题：

```text
problem_001/
├── description.md
├── metadata.json
└── tests.json
```

例如：

```json
{
  "name": "motor_start_stop",
  "inputs": [
    "Start",
    "Stop"
  ],
  "outputs": [
    "Motor"
  ]
}
```

tests：

```json
[
  {
    "inputs": {
      "Start": false,
      "Stop": false
    },
    "expected": {
      "Motor": false
    }
  },
  {
    "inputs": {
      "Start": true,
      "Stop": false
    },
    "expected": {
      "Motor": true
    }
  }
]
```

测试题是 PLC-Agent 的核心 benchmark。

以后衡量 Agent 是否变强，不能凭感觉。

必须统计：

```text
compile success rate
behavior pass rate
first-attempt pass rate
average iterations
execution time
```

---

# 10. 第一阶段不要开发 UI

现在不要开发：

```text
React
网页
漂亮界面
梯形图显示
动画
用户系统
数据库
```

这些暂时没有价值。

第一阶段只开发：

```text
CLI PLC-Agent
```

例如：

```bash
python main.py
```

输入：

```text
按下 Start 后 Motor 启动，
按下 Stop 后 Motor 停止。
```

终端显示：

```text
Analyzing requirement...

Generating ST...

Checking...
PASS

Compiling...
PASS

Starting OpenPLC...
PASS

Running tests...

Test 1 PASS
Test 2 PASS
Test 3 FAIL

Expected:
Motor = FALSE

Actual:
Motor = TRUE

Fixing program...

Running tests again...

ALL TESTS PASSED
```

先证明核心能力成立。

---

# 11. Docker

OpenPLC 环境必须 Docker 化。

目标：

```bash
docker compose up
```

即可启动 Runtime。

不要要求用户安装：

```text
TIA Portal
PLCSIM
MatIEC
GCC
复杂 PLC 软件
```

尽量全部封装。

---

# 12. Agent 与 PLC 系统解耦

Agent 不应该知道：

```text
OpenPLC REST API 细节
Docker command
MatIEC command
编译目录
```

Agent 只看到：

```text
plc_check
plc_compile
plc_start
plc_stop
plc_force_variables
plc_read_variables
plc_trace
plc_verify
```

即：

```text
LLM
 ↓
PLC Tools API
 ↓
MatIEC / OpenPLC
```

这样以后可以增加：

```text
CODESYS backend
Siemens backend
TwinCAT backend
```

而不用修改 Agent 核心。

---

# 13. 不要一开始开发复杂 Agent

第一版 Agent Loop 保持简单：

```python
while iteration < MAX_ITERATIONS:

    generate_or_fix()

    compile_result = plc_check()

    if not compile_result.success:
        feedback = compile_result.errors
        continue

    test_result = plc_verify()

    if test_result.passed:
        break

    feedback = test_result.failures
```

不要一开始加入：

```text
复杂 memory
multi-agent
planner agent
critic agent
RAG
向量数据库
复杂 workflow framework
```

只有出现明确需求再加入。

---

# 14. 第一阶段开发顺序

严格按照：

## M0：调研

研究：

```text
SemaPLC
MatIEC
OpenPLC Runtime
```

输出：

```text
docs/research.md
```

重点回答：

```text
SemaPLC 哪些代码可以直接复用？

MatIEC 如何调用？

OpenPLC Runtime 使用哪个 commit？

ST 如何上传运行？

变量如何 force/read？

Timer 如何验证？
```

---

## M1：MatIEC

实现：

```text
example.st
↓
MatIEC
↓
PASS / ERROR
```

真实运行。

---

## M2：Runtime

实现：

```text
ST
↓
MatIEC
↓
OpenPLC
↓
运行
```

---

## M3：变量控制

实现：

```text
force input
↓
PLC scan
↓
read output
```

---

## M4：自动测试

实现：

```text
tests.json
↓
plc_verify
↓
PASS / FAIL
```

---

## M5：Agent

接入 LLM：

```text
Natural language
↓
ST
↓
compile
↓
verify
↓
fix
```

---

## M6：Benchmark

至少运行多道真实 PLC 题目。

输出：

```text
成功率
平均修改次数
失败原因
```

---

## M7：Docker 一键运行

做到：

```bash
git clone ...
docker compose up
python main.py
```

即可使用。

---

# 15. 开发原则

必须遵守：

1. 先搜索 GitHub，再写代码。
2. 优先复用成熟开源实现。
3. SemaPLC 是第一参考项目。
4. 不依赖 TIA Portal。
5. 不依赖 GUI。
6. 不使用 mock 代替真实 Runtime。
7. 每个功能都必须真实运行验证。
8. 不因为代码能编译就认为题目正确。
9. 所有行为必须通过测试用例验证。
10. 每完成一个 milestone 就运行回归测试。
11. 不提前开发 UI。
12. 不提前设计复杂 Agent。
13. 保持 Agent、PLC Tools、Runtime 三层解耦。
14. 遇到失败首先查看 SemaPLC/OpenPLC/MatIEC 已经怎样解决。
15. 保持项目能够在 Linux/Docker 环境运行。

---

# 16. 现在开始

现在直接创建全新的：

```text
plc-agent
```

不要接触旧项目。

首先执行 M0。

具体：

1. 调研 SemaPLC。
2. 调研 `sema-plc-tools`。
3. 找出 MatIEC/OpenPLC 完整调用链。
4. 确认 OpenPLC Runtime 兼容 MatIEC 的具体版本。
5. 判断哪些代码值得直接复用。
6. 写出 `docs/research.md`。
7. 写出最小架构。
8. 然后立即进入 M1。
9. 真实运行一个最简单 ST 编译测试。
10. 根据实际结果继续开发。

不要一次生成大量未经测试的代码。

采用：

```text
研究
↓
实现最小功能
↓
运行
↓
检查结果
↓
修复
↓
提交
↓
下一阶段
```

最终目标只有一个：

**实现一个真正能够自主编写、编译、执行、验证并修改 IEC 61131-3 Structured Text PLC 程序的跨平台 PLC-Agent。**