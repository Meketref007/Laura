# Skills & GOAP

Laura uses a **Goal-Oriented Action Planning (GOAP)** system to autonomously decide which actions to take. Skills are individual actions the agent can perform.

## Architecture

```
User Goals → GOAP Planner → Action Plan → Skill Executor → Shopee API
                                  ↓
                          Learning System
                          (costs, outcomes)
```

The planner takes a **current state** and a **goal state**, searches for the lowest-cost sequence of skills to reach the goal, and executes the plan.

## Skills Registry

All available skills are registered in the `skills/` directory. List them:

```bash
laura skill-list
```

Each skill has:
- **Name** — unique identifier
- **Cost** — estimated cost (time/resources); learned over time
- **Priority** — execution priority
- **Preconditions** — state requirements before execution
- **Effects** — state changes after execution

### Built-in Skills

| Skill                    | Description                               |
|--------------------------|-------------------------------------------|
| `pricing_skill`          | Adjust product prices based on rules      |
| `stock_monitor_skill`    | Check stock levels and alert on low stock |
| `order_fulfillment_skill`| Process pending orders                    |
| `customer_reply_skill`   | Auto-reply to customer messages           |
| `rating_response_skill`  | Respond to product ratings                |
| `competitor_skill`       | Monitor competitor pricing                |
| `campaign_skill`         | Manage promotions and vouchers            |
| `report_skill`           | Generate daily/weekly reports             |
| `inventory_skill`        | Analyze inventory and suggest restocks    |
| `margin_skill`           | Monitor and enforce margin targets        |
| `flash_sale_skill`       | Create and manage flash sales             |

## Creating Custom Skills

### 1. Create the skill file

Create `shopee_agent/skills/my_skill.py`:

```python
from shopee_agent.skills.base import BaseSkill


class MyCustomSkill(BaseSkill):
    name = "my_custom_skill"
    cost = 5.0
    priority = 50
    preconditions = {"has_data": True}
    effects = {"analyzed": True}

    async def execute(self, context: dict) -> dict:
        # Your skill logic here
        result = {"status": "ok", "message": "Analysis complete"}
        return result
```

### 2. Register the skill

```bash
laura skill-register MyCustomSkill --module shopee_agent.skills.my_skill
```

Or use the scaffold command:

```bash
laura skill-create my_custom_skill
```

### 3. Test the skill

```bash
laura skill-test my_custom_skill
laura skill-run my_custom_skill
```

### Skill Lifecycle

1. **Registration** — skill class is loaded by the registry
2. **Validation** — preconditions are checked before execution
3. **Execution** — `execute()` is called with context
4. **Learning** — outcomes are recorded; costs are adjusted
5. **Approval** (optional) — actions pending human approval

## GOAP Planner

The planner finds the optimal sequence of skills to achieve a goal.

### Run the planner

```bash
laura skill-goap-plan \
  --current-state '{"stock_checked":false,"margin_protected":false}' \
  --goal-state '{"stock_checked":true,"margin_protected":true}' \
  --max-depth 6
```

### Plan explanation

```bash
laura skill-goap-explain --plan-id <id>
```

Outputs a natural-language explanation of the plan.

### Learning

The GOAP system learns from execution outcomes:
- Successful skills have their costs decreased
- Failed skills have their costs increased
- New preconditions/effects are discovered

View learning state:

```bash
laura skill-history --learning
laura learning-stats
```

### Approval Workflow

For sensitive actions (pricing changes, campaign spends), skills can require approval:

```bash
laura skill-approval-list    # View pending approvals
laura skill-approve <id>     # Approve
laura skill-reject <id>      # Reject
```

### Plan Templates

Plans can be saved as templates for recurring workflows:

```bash
laura plan-template list
laura plan-template save --name "morning_routine"
laura plan-template apply --name "morning_routine"
```

## Skill Marketplace

Laura supports a community skill marketplace where users can share skills:

```bash
laura skill-market browse
laura skill-market install <skill_name>
laura skill-market publish <skill_name>
```
