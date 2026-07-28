# 主路径渐进重构路线

本次先冻结历史债务，禁止大文件、宽泛异常和旧运行时依赖继续增长；后续按以下切片迁移，每个切片
保持 Responses 合同不变，禁止“大爆炸重写”。

1. `kernel/agent_loop/runner.py`：拆为 planning、tool_execution、approval、persistence、recovery；目标
   单文件 ≤ 1,600 行。
2. `kernel/agent_loop/context.py`：拆 attachment、memory、instruction、conversation assemblers；目标 ≤ 700 行。
3. `infra/storage/models.py`：按 responses、knowledge、identity、governance 分模块，统一从 model registry 导入；
   目标单文件 ≤ 1,800 行。
4. `agents/data_agent_v2/supervisor.py`：DAG 状态机、节点和验证器分离；目标 ≤ 1,200 行。
5. `frontend/src/api/client.ts`：按 responses、knowledge、data、admin 与 transport 分域；目标 ≤ 1,800 行。

`quality/engineering_baseline.json` 保存冻结上限和目标，`scripts/check_enterprise_boundaries.py` 阻止回退。
