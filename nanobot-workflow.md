# TÀI LIỆU KIẾN TRÚC KỸ THUẬT: NANOBOT EXTENDED (WORKFLOW EDITION)

## 1. TỔNG QUAN KIẾN TRÚC (ARCHITECTURE OVERVIEW)
Mục tiêu của dự án là fork repository **Nanobot** (Python) để giữ lại lõi xử lý siêu nhẹ, dễ bảo trì, dễ tùy biến. Đồng thời, bổ sung thêm hệ thống **Workflow Engine** từ **OpenFang** để giải quyết bài toán: *Điều phối nhiều Sub-agent chạy theo một dây chuyền tự động mà không cần hard-code kịch bản.*

### Tôn chỉ thiết kế:
1. **Python-Native:** Toàn bộ logic viết bằng Python, tận dụng hệ sinh thái phong phú (asyncio, pydantic).
2. **Configuration over Code:** Người dùng định nghĩa Workflow bằng file JSON/YAML, hệ thống tự động biên dịch thành luồng chạy.
3. **Less is More (Memory):** Vẫn giữ nguyên kiến trúc lưu trữ bằng text file phẳng (`.md`) của Nanobot, không dùng VectorDB để giữ hệ thống nhẹ nhàng.

---

## 2. CÁC THÀNH PHẦN LÕI CƠ BẢN (KẾ THỪA TỪ NANOBOT)

Trước khi đi sâu vào Workflow, hệ thống giữ nguyên các block nền tảng sau:

*   **Agent & Sub-agent Spawning:** 
    *   **Main Agent:** Đứng ở ngoài cùng giao tiếp với User (qua Terminal/Telegram).
    *   **Sub-agent:** Được sinh ra dưới nền (spawn) để giải quyết các task độc lập. 
*   **Skill & Tool Management:**
    *   **Native Tools:** Các file `.py` đặt trong `skills/`, giao tiếp qua `requests` hoặc logic nội bộ, khai báo Type Hints + Docstring để LLM tự gọi.
    *   **MCP Server:** Tích hợp các API của công ty/bên thứ 3 thông qua chuẩn Model Context Protocol bằng cấu hình trong `config.json`.
*   **Memory Management:**
    *   Dùng 2 file cốt lõi: `MEMORY.md` (Trí nhớ dài hạn/Sự thật) và `HISTORY.md` (Lịch sử hội thoại log-append).
    *   Dùng Tool `grep` để Agent tự tìm kiếm trí nhớ thay vì RAG.
    *   Cơ chế **Auto-Consolidation**: Background task tự tóm tắt tin nhắn cũ khi tràn context window.

---

## 3. THIẾT KẾ VÀ TÍCH HỢP WORKFLOW ENGINE (DEEP DIVE)

Đây là module bạn sẽ code thêm vào source của Nanobot. Chúng ta sẽ tạo ra một Engine đọc file JSON và tự động điều phối các Sub-agent (spawn) của Nanobot.

### 3.1. Cấu trúc thư mục thêm mới
Trong repo Nanobot đã fork, bạn tổ chức lại cấu trúc như sau:
```text
nanobot/
├── core/
│   ├── agent.py         # Lõi agent cũ
│   ├── memory.py        # Quản lý file .md
│   └── workflow.py      # [NEW] File chứa WorkflowEngine và State Machine
├── skills/              # Nơi chứa Native APIs/Tools
├── workflows/           # [NEW] Thư mục chứa các định nghĩa JSON/YAML
│   └── code_review_pipeline.json
└── config.json          # Config LLM & MCP Servers
```

### 3.2. Định nghĩa Schema (JSON) cho Workflow
Kế thừa tư tưởng của OpenFang, mỗi file JSON trong `workflows/` là một pipeline. 

**Ví dụ file `workflows/content_creation.json`**:
```json
{
  "name": "Tạo Content Tự Động",
  "description": "Pipeline tìm hiểu chủ đề và viết bài đăng mạng xã hội",
  "steps":[
    {
      "step_id": "research",
      "agent_role": "Nhà nghiên cứu chuyên sâu",
      "mode": "chain",
      "prompt_template": "Hãy tìm kiếm thông tin chi tiết về chủ đề: {{input_topic}}",
      "timeout": 120
    },
    {
      "step_id": "draft_writing",
      "agent_role": "Copywriter",
      "mode": "chain",
      "prompt_template": "Dựa vào thông tin sau: {{research.output}}, hãy viết 1 bản nháp.",
      "timeout": 120
    },
    {
      "step_id": "fact_check",
      "agent_role": "Kiểm duyệt viên",
      "mode": "conditional",
      "condition": "contains: 'số liệu'",
      "prompt_template": "Hãy fact-check bản nháp sau: {{draft_writing.output}}",
      "error_handling": "continue"
    }
  ]
}
```

### 3.3. Thiết kế `core/workflow.py` (Hướng dẫn Code Python)

Bạn cần viết một class `WorkflowEngine` sử dụng `asyncio` của Python để xử lý các `mode` (Chain, Parallel, Conditional).

#### a. Quản lý trạng thái (State & Context Passing)
Mỗi instance của workflow khi chạy sẽ có một `context` dạng dictionary (tương tự như HashMap của Rust trong OpenFang) để lưu output của từng bước.

```python
import json
import asyncio
from core.agent import SubAgent # Giả sử import từ lõi nanobot

class WorkflowEngine:
    def __init__(self, workflow_path: str):
        with open(workflow_path, 'r', encoding='utf-8') as f:
            self.definition = json.load(f)
        self.context = {} # Nơi lưu trữ output của các bước: {"step1": "...", "step2": "..."}

    def render_prompt(self, template: str) -> str:
        """Thay thế biến {{step_id.output}} trong prompt bằng dữ liệu thực"""
        rendered = template
        for key, value in self.context.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered
```

#### b. Xử lý logic thực thi (Execution Loop)
Vòng lặp chính sẽ duyệt qua từng `step` trong JSON. Tuỳ vào `mode` mà gọi Sub-agent tương ứng.

```python
    async def execute_step(self, step: dict):
        step_id = step["step_id"]
        mode = step.get("mode", "chain")
        
        # 1. Rẽ nhánh (Conditional)
        if mode == "conditional":
            condition = step.get("condition", "")
            if "contains:" in condition:
                keyword = condition.split("contains:")[1].strip().strip("'\"")
                # Kiểm tra output của bước ngay trước đó
                last_output = list(self.context.values())[-1] 
                if keyword not in last_output:
                    print(f"Skipping step {step_id} (Condition not met)")
                    return

        # 2. Render Prompt nội suy dữ liệu
        raw_prompt = step["prompt_template"]
        final_prompt = self.render_prompt(raw_prompt)

        # 3. Chạy Sub-Agent của Nanobot
        print(f"Executing {step_id}...")
        try:
            # Sử dụng cơ chế spawn của Nanobot
            agent = SubAgent(role=step["agent_role"])
            # Có thể timeout dùng asyncio.wait_for
            output = await asyncio.wait_for(
                agent.run(final_prompt), 
                timeout=step.get("timeout", 60)
            )
            
            # Lưu lại output để bước sau dùng
            self.context[f"{step_id}.output"] = output
            
        except Exception as e:
            if step.get("error_handling") == "continue":
                print(f"Step {step_id} failed but continuing: {e}")
                self.context[f"{step_id}.output"] = "LỖI BỎ QUA"
            else:
                raise e

    async def run(self, input_topic: str):
        """Hàm khởi chạy toàn bộ Pipeline"""
        self.context["input_topic"] = input_topic
        
        # Hỗ trợ Parallel (Fan-out) cơ bản:
        # Nếu thiết kế nâng cao, bạn có thể nhóm các step có mode='parallel' để chạy bằng asyncio.gather()
        
        for step in self.definition["steps"]:
            await self.execute_step(step)
            
        return list(self.context.values())[-1] # Trả về output của bước cuối cùng
```

---

## 4. TƯƠNG TÁC GIỮA WORKFLOW VÀ MEMORY/TOOLS

Khi tích hợp Workflow vào Nanobot, bạn cần lưu ý 2 điểm xử lý kỹ thuật sau để hệ thống không bị "phân mảnh":

### 4.1. Cách Tool hoạt động trong Workflow
*   **Sub-Agent tự quyết định Tool:** Workflow Engine **KHÔNG** gọi Tool. Workflow Engine chỉ làm nhiệm vụ giao Prompt cho Sub-agent. Lõi Sub-agent của Nanobot sẽ tự động đọc System Prompt, tự quét thư mục `skills/` và kết nối MCP Server để lấy Tool (vd: `get_user_info`, `search_web`) tùy ý theo tư duy của LLM tại bước đó. 
*   Việc tách bạch này giữ cho Workflow file (`.json`) sạch sẽ, chỉ tập trung vào luồng luân chuyển công việc.

### 4.2. Xử lý Memory (Tránh rác dữ liệu)
Nếu để mỗi Sub-agent trong Workflow tự do ghi vào `HISTORY.md` và `MEMORY.md`, file trí nhớ của bạn sẽ đầy rác (các bản nháp, text log thừa mứa).
*   **Giải pháp (Sandbox Memory):** Khi `WorkflowEngine` spawn một Sub-agent, nó cung cấp cho Agent này một phiên bản *Memory ảo tạm thời* (Temporary Session Context).
*   Chỉ khi toàn bộ Workflow hoàn thành (`Completed`), Main Agent mới đọc Output cuối cùng của Workflow, tóm tắt nó thành 1 câu duy nhất (Vd: *"Đã hoàn thành nghiên cứu và đăng bài viết về AI Agent thành công lúc 14:00"*) và ghi câu này vào `HISTORY.md` cốt lõi.

---

## 5. TỔNG KẾT ROADMAP TRIỂN KHAI

Để biến bản thiết kế này thành hiện thực, lộ trình code của bạn:
1.  **Fork** repo `HKUDS/nanobot` về máy.
2.  Tạo thư mục `workflows/` và viết thử 1 file `test_pipeline.json` cấu trúc đơn giản.
3.  Tạo file `core/workflow.py` chứa class `WorkflowEngine` sử dụng module `asyncio` để parse luồng JSON.
4.  Viết hàm kết nối (bridge): Thêm một Tool vào `skills/` của Main Agent tên là `run_workflow_tool(workflow_name: str, input: str)`. Nhờ vậy, từ giao diện chat Telegram/Terminal, bạn có thể ra lệnh: *"Bot ơi, chạy cho tôi quy trình tạo content về bài học Crypto đi"*, Main Agent sẽ kích hoạt file JSON tương ứng chạy ngầm.

Cách tiếp cận này mang lại **sức mạnh luồng tự động (Pipelines) của C++ / Rust (OpenFang)** trực tiếp vào **môi trường Python linh hoạt, dễ tuỳ biến của Nanobot** một cách hoàn hảo!