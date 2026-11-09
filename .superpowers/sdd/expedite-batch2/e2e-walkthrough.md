# 急料批次②③真实 HTTP 数据流走查

执行工作目录：`/Users/neo/.codex/worktrees/814b/AI-Manufacturing-Platform`

实际执行命令：

```sh
PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python scripts/verify_expedite_batch2.py --root /Users/neo/.codex/worktrees/814b/expedite-http-finalenv --platform-root /Users/neo/Developer/work/AI-Agent-Platform --output .superpowers/sdd/expedite-batch2/finalenv > .superpowers/sdd/expedite-batch2/socket-final.log 2>&1
```

进程退出码：**0**（已核对实际执行工具返回值）。

时间：2026-11-09T10:47:03.783143+00:00
结果：通过；项目：00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6

平台运行 preview_manufacturing.py 的实际回环 socket 服务；未打通的外部 SAP/WMS/MES/PDM 使用类型化 mock。
业务操作全部通过 HTTP；唯一直接维护步骤是在新项目任何业务意图之前绑定 demo 集成档案。
交接发起与签收使用不同的清单内合成身份，切换通过重启 preview --actor-id 完成，不放松授权。
原始响应关键字段见同目录 http-evidence.json；不记录 CSRF token。

## preview process

```json
{
  "step": "preview process",
  "url": "http://127.0.0.1:57188",
  "actor": {
    "id": "b242f128-60e4-480c-a02e-aa233332a45c",
    "display_name": "【模拟】本地预览管理员"
  },
  "configuration_admin": true,
  "external_systems": "mock"
}
```

## HTTP create OEM project

```json
{
  "step": "HTTP create OEM project",
  "http_status": 200,
  "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "mode": "oem"
}
```

## demo maintenance profile assignment

```json
{
  "step": "demo maintenance profile assignment",
  "profile": "oem-network-v1",
  "business_rows_written": false
}
```

## demand.record

```json
{
  "step": "demand.record",
  "http_status": 200,
  "object_type": "demand",
  "object_id": "23e4824d-77da-4002-928d-1c3a032148bb",
  "project_version": 3,
  "integration": null,
  "network": null
}
```

## demand.review

```json
{
  "step": "demand.review",
  "http_status": 200,
  "object_type": "demand",
  "object_id": "23e4824d-77da-4002-928d-1c3a032148bb",
  "project_version": 4,
  "integration": null,
  "network": null
}
```

## demand.review

```json
{
  "step": "demand.review",
  "http_status": 200,
  "object_type": "demand",
  "object_id": "23e4824d-77da-4002-928d-1c3a032148bb",
  "project_version": 5,
  "integration": null,
  "network": null
}
```

## demand.review

```json
{
  "step": "demand.review",
  "http_status": 200,
  "object_type": "demand",
  "object_id": "23e4824d-77da-4002-928d-1c3a032148bb",
  "project_version": 6,
  "integration": null,
  "network": null
}
```

## demand.review

```json
{
  "step": "demand.review",
  "http_status": 200,
  "object_type": "demand",
  "object_id": "23e4824d-77da-4002-928d-1c3a032148bb",
  "project_version": 7,
  "integration": null,
  "network": null
}
```

## demand.review

```json
{
  "step": "demand.review",
  "http_status": 200,
  "object_type": "demand",
  "object_id": "23e4824d-77da-4002-928d-1c3a032148bb",
  "project_version": 8,
  "integration": null,
  "network": null
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 9,
  "integration": {
    "intent_id": "ba5bdddf-741a-42d3-84d4-2e795ec6c88e",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 11,
  "integration": {
    "intent_id": "ba5bdddf-741a-42d3-84d4-2e795ec6c88e",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 2,
    "duplicate": 0,
    "failed": 0
  }
}
```

## sap.release_order source evidence

```json
{
  "step": "sap.release_order source evidence",
  "source": {
    "system": "sap",
    "object_type": "order",
    "external_id": "ba5bdddf-741a-42d3-84d4-2e795ec6c88e",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:00.459741Z",
    "collected_at": "2026-11-09T10:47:00.459741Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "order_line",
      "id": "daf4c520-350c-56fd-92e4-fffdc7e6cce9"
    }
  ]
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 12,
  "integration": {
    "intent_id": "f70f5762-4dc7-4d67-b832-2be62fb54713",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 14,
  "integration": {
    "intent_id": "f70f5762-4dc7-4d67-b832-2be62fb54713",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 2,
    "duplicate": 0,
    "failed": 0
  }
}
```

## pdm.publish_revision source evidence

```json
{
  "step": "pdm.publish_revision source evidence",
  "source": {
    "system": "pdm",
    "object_type": "revision",
    "external_id": "f70f5762-4dc7-4d67-b832-2be62fb54713",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:00.562408Z",
    "collected_at": "2026-11-09T10:47:00.562408Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "revision",
      "id": "0cc54277-de4e-46d2-a99a-75ccce8ad554"
    }
  ]
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 15,
  "integration": {
    "intent_id": "60385d23-01ce-424f-811f-ed82f99a7f89",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 17,
  "integration": {
    "intent_id": "60385d23-01ce-424f-811f-ed82f99a7f89",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 1,
    "delivered": 2,
    "duplicate": 0,
    "failed": 0
  }
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 18,
  "integration": {
    "intent_id": "60385d23-01ce-424f-811f-ed82f99a7f89",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 1,
    "duplicate": 0,
    "failed": 0
  }
}
```

## sap.release_work_order source evidence

```json
{
  "step": "sap.release_work_order source evidence",
  "source": {
    "system": "sap",
    "object_type": "work_order",
    "external_id": "60385d23-01ce-424f-811f-ed82f99a7f89",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:00.626642Z",
    "collected_at": "2026-11-09T10:47:00.626642Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "work_order",
      "id": "d49d5d55-6a48-5e2b-b06e-41a838663e9c"
    }
  ]
}
```

## order.allocate

```json
{
  "step": "order.allocate",
  "http_status": 200,
  "object_type": "order_line",
  "object_id": "daf4c520-350c-56fd-92e4-fffdc7e6cce9",
  "project_version": 19,
  "integration": null,
  "network": null
}
```

## material.define

```json
{
  "step": "material.define",
  "http_status": 200,
  "object_type": "material_lot",
  "object_id": "8fcf4618-f548-4530-ac0e-016bdaf9232f",
  "project_version": 20,
  "integration": null,
  "network": null
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 21,
  "integration": {
    "intent_id": "5df85278-b605-4358-b300-52dbeb2b6b31",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 23,
  "integration": {
    "intent_id": "5df85278-b605-4358-b300-52dbeb2b6b31",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 4,
    "duplicate": 0,
    "failed": 0
  }
}
```

## sap.publish_plan source evidence

```json
{
  "step": "sap.publish_plan source evidence",
  "source": {
    "system": "sap",
    "object_type": "plan",
    "external_id": "5df85278-b605-4358-b300-52dbeb2b6b31",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:00.747839Z",
    "collected_at": "2026-11-09T10:47:00.747839Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "plan",
      "id": "a0f4d7b8-733c-5379-8ad1-16e7c1a6d56d"
    },
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "requirement",
      "id": "dd4d2543-7a9d-420c-8c84-594cd813d3ee"
    }
  ]
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 24,
  "integration": {
    "intent_id": "0af83e75-626e-4453-8d81-fb903e1f7a17",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 26,
  "integration": {
    "intent_id": "0af83e75-626e-4453-8d81-fb903e1f7a17",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 2,
    "duplicate": 0,
    "failed": 0
  }
}
```

## srm.promise source evidence

```json
{
  "step": "srm.promise source evidence",
  "source": {
    "system": "srm",
    "object_type": "promise",
    "external_id": "0af83e75-626e-4453-8d81-fb903e1f7a17",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:00.850028Z",
    "collected_at": "2026-11-09T10:47:00.850028Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "commitment",
      "id": "b4a54f3a-b41d-4639-b23a-c8ddc4096ac0"
    }
  ]
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 27,
  "integration": {
    "intent_id": "2d8cbbbd-8a84-4e7c-b8a2-6b31b7087fc2",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 29,
  "integration": {
    "intent_id": "2d8cbbbd-8a84-4e7c-b8a2-6b31b7087fc2",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 2,
    "duplicate": 0,
    "failed": 0
  }
}
```

## srm.announce_arrival source evidence

```json
{
  "step": "srm.announce_arrival source evidence",
  "source": {
    "system": "srm",
    "object_type": "arrival",
    "external_id": "2d8cbbbd-8a84-4e7c-b8a2-6b31b7087fc2",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:00.921173Z",
    "collected_at": "2026-11-09T10:47:00.921173Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": []
}
```

## expedite.open

```json
{
  "step": "expedite.open",
  "http_status": 200,
  "object_type": "material_expedite",
  "object_id": "42e76ad8-09be-45d3-83e4-c04b579e336d",
  "project_version": 30,
  "integration": null,
  "network": null
}
```

## general expedite responsibility

```json
{
  "step": "general expedite responsibility",
  "title": "急料待跟进",
  "accounting_unchanged": true
}
```

## arrival.record

```json
{
  "step": "arrival.record",
  "http_status": 200,
  "object_type": "arrival",
  "object_id": "6bf0693f-2870-4915-8b41-21abccc11d9f",
  "project_version": 31,
  "integration": null,
  "network": null
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 32,
  "integration": {
    "intent_id": "2afb5a24-2227-4794-a089-3a8c1d8aa718",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 34,
  "integration": {
    "intent_id": "2afb5a24-2227-4794-a089-3a8c1d8aa718",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 1,
    "delivered": 2,
    "duplicate": 0,
    "failed": 0
  }
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 35,
  "integration": {
    "intent_id": "2afb5a24-2227-4794-a089-3a8c1d8aa718",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 1,
    "duplicate": 0,
    "failed": 0
  }
}
```

## wms.receive source evidence

```json
{
  "step": "wms.receive source evidence",
  "source": {
    "system": "wms",
    "object_type": "receipt",
    "external_id": "2afb5a24-2227-4794-a089-3a8c1d8aa718",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:01.020554Z",
    "collected_at": "2026-11-09T10:47:01.020554Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "receipt",
      "id": "6e0ea7e1-a954-4d66-afdc-1a7879c5403f"
    }
  ]
}
```

## arrival.match

```json
{
  "step": "arrival.match",
  "http_status": 200,
  "object_type": "arrival",
  "object_id": "6bf0693f-2870-4915-8b41-21abccc11d9f",
  "project_version": 36,
  "integration": null,
  "network": null
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 37,
  "integration": {
    "intent_id": "aa7f01f8-26c4-4d98-8dad-3df17fccefc1",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 39,
  "integration": {
    "intent_id": "aa7f01f8-26c4-4d98-8dad-3df17fccefc1",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 1,
    "delivered": 1,
    "duplicate": 0,
    "failed": 0
  }
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 40,
  "integration": {
    "intent_id": "aa7f01f8-26c4-4d98-8dad-3df17fccefc1",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 1,
    "duplicate": 0,
    "failed": 0
  }
}
```

## mes.inspect source evidence

```json
{
  "step": "mes.inspect source evidence",
  "source": {
    "system": "mes",
    "object_type": "iqc",
    "external_id": "aa7f01f8-26c4-4d98-8dad-3df17fccefc1",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:01.121432Z",
    "collected_at": "2026-11-09T10:47:01.121432Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "receipt",
      "id": "6e0ea7e1-a954-4d66-afdc-1a7879c5403f"
    }
  ]
}
```

## receipt urgent flag and qualified responsibility

```json
{
  "step": "receipt urgent flag and qualified responsibility",
  "receipt_id": "6e0ea7e1-a954-4d66-afdc-1a7879c5403f",
  "blocking_reasons": [
    "Expedited: open expedite on linked requirement"
  ],
  "task_title": "急料已检验，待安排上线/关案",
  "read_accounting_unchanged": true
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 41,
  "integration": {
    "intent_id": "8ff9b5c2-569d-421b-9ffd-a9693b739f97",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 43,
  "integration": {
    "intent_id": "8ff9b5c2-569d-421b-9ffd-a9693b739f97",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 0,
    "duplicate": 0,
    "failed": 0
  }
}
```

## wms.putaway source evidence

```json
{
  "step": "wms.putaway source evidence",
  "source": {
    "system": "wms",
    "object_type": "putaway",
    "external_id": "8ff9b5c2-569d-421b-9ffd-a9693b739f97",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:01.251471Z",
    "collected_at": "2026-11-09T10:47:01.251471Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": null,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "material_lot",
      "id": "8fcf4618-f548-4530-ac0e-016bdaf9232f"
    },
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "work_order",
      "id": "d49d5d55-6a48-5e2b-b06e-41a838663e9c"
    }
  ]
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 44,
  "integration": {
    "intent_id": "02adf718-3431-48da-8f8c-9ca3770b07dc",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 46,
  "integration": {
    "intent_id": "02adf718-3431-48da-8f8c-9ca3770b07dc",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 0,
    "duplicate": 0,
    "failed": 0
  }
}
```

## wms.reserve source evidence

```json
{
  "step": "wms.reserve source evidence",
  "source": {
    "system": "wms",
    "object_type": "reservation",
    "external_id": "02adf718-3431-48da-8f8c-9ca3770b07dc",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:01.309565Z",
    "collected_at": "2026-11-09T10:47:01.309565Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": null,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "reservation",
      "id": "05debd8c-d616-4b29-9809-4962f7a02218"
    }
  ]
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 47,
  "integration": {
    "intent_id": "07cdddfc-e9c2-4eec-b862-b841ac55c9c2",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 49,
  "integration": {
    "intent_id": "07cdddfc-e9c2-4eec-b862-b841ac55c9c2",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 1,
    "delivered": 3,
    "duplicate": 0,
    "failed": 0
  }
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 50,
  "integration": {
    "intent_id": "07cdddfc-e9c2-4eec-b862-b841ac55c9c2",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 1,
    "duplicate": 0,
    "failed": 0
  }
}
```

## wms.pick source evidence

```json
{
  "step": "wms.pick source evidence",
  "source": {
    "system": "wms",
    "object_type": "pick",
    "external_id": "07cdddfc-e9c2-4eec-b862-b841ac55c9c2",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:01.371929Z",
    "collected_at": "2026-11-09T10:47:01.371929Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "material_lot",
      "id": "8fcf4618-f548-4530-ac0e-016bdaf9232f"
    },
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "work_order",
      "id": "d49d5d55-6a48-5e2b-b06e-41a838663e9c"
    }
  ]
}
```

## integration.pull

```json
{
  "step": "integration.pull",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 51,
  "integration": {
    "intent_id": "8131b4a2-bcee-47dd-aa97-74bc782d366c",
    "phase": "applied",
    "source_committed": null,
    "receipt_phase": null,
    "projection_applied": true
  },
  "network": null
}
```

## WMS pick causal SAP posting

```json
{
  "step": "WMS pick causal SAP posting",
  "source_key": {
    "system": "wms",
    "object_type": "pick",
    "external_id": "07cdddfc-e9c2-4eec-b862-b841ac55c9c2",
    "version": 1
  },
  "consumer_delivered": true,
  "sap_posting_key": {
    "system": "sap",
    "object_type": "accounting_entry",
    "external_id": "7df20480-f882-5dd5-a15c-4cd692100bc0",
    "version": 1
  },
  "sap_posted": true,
  "workflow_projected": true
}
```

## preview process

```json
{
  "step": "preview process",
  "url": "http://127.0.0.1:57507",
  "actor": {
    "id": "6c1439fe-535d-5fa3-bc99-b2d37a2d7b89",
    "display_name": "【模拟维护】production"
  },
  "configuration_admin": false,
  "external_systems": "mock"
}
```

## material_handoff.record

```json
{
  "step": "material_handoff.record",
  "http_status": 200,
  "object_type": "material_handoff",
  "object_id": "fa94db45-e7d0-413c-8509-344b7026cf5b",
  "project_version": 53,
  "integration": null,
  "network": null
}
```

## preview process

```json
{
  "step": "preview process",
  "url": "http://127.0.0.1:57603",
  "actor": {
    "id": "b242f128-60e4-480c-a02e-aa233332a45c",
    "display_name": "【模拟】本地预览管理员"
  },
  "configuration_admin": true,
  "external_systems": "mock"
}
```

## material_handoff.receive

```json
{
  "step": "material_handoff.receive",
  "http_status": 200,
  "object_type": "material_handoff",
  "object_id": "fa94db45-e7d0-413c-8509-344b7026cf5b",
  "project_version": 54,
  "integration": null,
  "network": null
}
```

## issue.mark

```json
{
  "step": "issue.mark",
  "http_status": 200,
  "object_type": "issue_mark",
  "object_id": "24cf70f9-e558-4ffc-8f5f-9bc5373bc346",
  "project_version": 55,
  "integration": null,
  "network": null
}
```

## issue.mark

```json
{
  "step": "issue.mark",
  "http_status": 200,
  "object_type": "issue_mark",
  "object_id": "bfc17fd6-6d16-4efc-a622-65da728ec73e",
  "project_version": 56,
  "integration": null,
  "network": null
}
```

## issue.mark

```json
{
  "step": "issue.mark",
  "http_status": 200,
  "object_type": "issue_mark",
  "object_id": "ee039e7c-f25a-4a1c-ad4d-4110a2251ccd",
  "project_version": 57,
  "integration": null,
  "network": null
}
```

## issue.mark

```json
{
  "step": "issue.mark",
  "http_status": 200,
  "object_type": "issue_mark",
  "object_id": "863510f4-8d26-4b15-9a64-ced5445321be",
  "project_version": 58,
  "integration": null,
  "network": null
}
```

## four issue marks and all five milestones

```json
{
  "step": "four issue marks and all five milestones",
  "marks_total": 4,
  "milestones": {
    "opened_at": "2026-11-09T10:47:00.986202Z",
    "arrival_at": "2026-11-09T10:47:00.996545Z",
    "receipt_at": "2026-11-09T10:47:01.026095Z",
    "inspection_at": "2026-11-09T10:47:01.128665Z",
    "handoff_at": "2026-11-09T10:47:02.885793Z"
  },
  "accounting_unchanged": true
}
```

## expedite.close

```json
{
  "step": "expedite.close",
  "http_status": 200,
  "object_type": "material_expedite",
  "object_id": "42e76ad8-09be-45d3-83e4-c04b579e336d",
  "project_version": 59,
  "integration": null,
  "network": null
}
```

## closed case clears flag and responsibility

```json
{
  "step": "closed case clears flag and responsibility",
  "case_id": "42e76ad8-09be-45d3-83e4-c04b579e336d",
  "accounting_unchanged": true
}
```

## mock_system.execute

```json
{
  "step": "mock_system.execute",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 60,
  "integration": {
    "intent_id": "3a781ef8-4823-444c-97d5-5165094fdef8",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": null
}
```

## mock_system.query

```json
{
  "step": "mock_system.query",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 62,
  "integration": {
    "intent_id": "3a781ef8-4823-444c-97d5-5165094fdef8",
    "phase": "applied",
    "source_committed": true,
    "receipt_phase": "accepted",
    "projection_applied": true
  },
  "network": {
    "pending": 0,
    "delivered": 1,
    "duplicate": 0,
    "failed": 0
  }
}
```

## mes.shortage source evidence

```json
{
  "step": "mes.shortage source evidence",
  "source": {
    "system": "mes",
    "object_type": "shortage",
    "external_id": "3a781ef8-4823-444c-97d5-5165094fdef8",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:02.982502Z",
    "collected_at": "2026-11-09T10:47:02.982502Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "source_accepted": true,
  "consumer_delivered": true,
  "workflow_projected": true,
  "sap_posted": null,
  "targets": [
    {
      "project_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
      "kind": "material_expedite",
      "id": "41becb66-22ff-570c-ac2d-b94c4178186f"
    }
  ]
}
```

## integration.pull

```json
{
  "step": "integration.pull",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 63,
  "integration": {
    "intent_id": "4d5f3f12-91fe-4df1-8723-505a6c78748b",
    "phase": "applied",
    "source_committed": null,
    "receipt_phase": null,
    "projection_applied": true
  },
  "network": null
}
```

## integration.pull

```json
{
  "step": "integration.pull",
  "http_status": 200,
  "object_type": "project",
  "object_id": "00dcbbb7-9220-462c-8dbb-7ef56eb1b8e6",
  "project_version": 65,
  "integration": {
    "intent_id": "4bfd01db-cf10-43bd-831f-6c11fd21220f",
    "phase": "applied",
    "source_committed": null,
    "receipt_phase": null,
    "projection_applied": true
  },
  "network": null
}
```

## preview process

```json
{
  "step": "preview process",
  "url": "http://127.0.0.1:57606",
  "actor": {
    "id": "b242f128-60e4-480c-a02e-aa233332a45c",
    "display_name": "【模拟】本地预览管理员"
  },
  "configuration_admin": true,
  "external_systems": "mock"
}
```

## MES shortage replay and restart

```json
{
  "step": "MES shortage replay and restart",
  "case_id": "41becb66-22ff-570c-ac2d-b94c4178186f",
  "case_count": 2,
  "source": {
    "system": "mes",
    "object_type": "shortage",
    "external_id": "3a781ef8-4823-444c-97d5-5165094fdef8",
    "version": 1,
    "mode": "mock",
    "occurred_at": "2026-11-09T10:47:02.982502Z",
    "collected_at": "2026-11-09T10:47:02.982502Z",
    "cutoff": null,
    "evidence": "Source-owned committed mock fact"
  },
  "accounting_unchanged": true,
  "restart_readable": true
}
```
