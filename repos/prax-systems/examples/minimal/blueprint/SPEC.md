# Specification · echo-log

Contracts provided: `K-echo-log@1`.

## Components
| Id | Component | Responsibility |
|---|---|---|
| C-01 | echo | Return the input unchanged |
| C-02 | log | Append one JSON line per call |

## Contracts
### K-echo-log@1
One JSON object per line: `{"ts": "<ISO-8601>", "msg": "<string>"}`.

## Requirements
| Id | Requirement | Acceptance check |
|---|---|---|
| R-001 | echo MUST return its input unchanged | test_R001 |
| R-002 | every echo MUST append one K-echo-log@1 line | test_R002 |
| R-003 | the demo replay MUST print every logged message | manual: demo step 1 |
