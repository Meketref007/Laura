# CLI Reference

Laura provides 150+ CLI commands organized by category. All commands are accessible via the `laura` entry point:

```bash
laura <command> [options]
```

## Setup & Configuration

| Command                          | Description                              |
|----------------------------------|------------------------------------------|
| `laura setup`                    | Interactive first-time setup wizard     |
| `laura setup --quick`            | Non-interactive setup using env vars     |
| `laura setup --check`            | Check prerequisites only                 |
| `laura ollama-status`            | Check Ollama connection and model list   |
| `laura ollama-fix`               | Attempt to fix common Ollama issues      |

## Daemon

| Command                          | Description                              |
|----------------------------------|------------------------------------------|
| `laura daemon`                   | Start the Laura background daemon        |
| `laura daemon --stop`            | Stop the running daemon                  |
| `laura daemon --status`          | Check daemon status                      |

## Dashboard

| Command                          | Description                              |
|----------------------------------|------------------------------------------|
| `laura dashboard`                | Launch the web dashboard                 |
| `laura dashboard --port 8888`    | Custom port                              |
| `laura dashboard --host 0.0.0.0` | Custom bind address                      |
| `laura dashboard-cli`            | Terminal-based dashboard (no browser)    |
| `laura api-serve`                | Start REST API server                    |

## Shopee Products

| Command                                      | Description                          |
|----------------------------------------------|--------------------------------------|
| `laura product-list`                         | List all products                    |
| `laura product-item-detail <item_id>`         | Get product details                   |
| `laura product-item-base-info <item_id>`      | Get base product info                 |
| `laura product-item-variations <item_id>`     | List product variations               |
| `laura product-set-price <item_id> <price>`   | Update product price                  |
| `laura product-set-stock <item_id> <stock>`   | Update product stock                  |
| `laura product-batch-update`                  | Batch update products from CSV/JSON   |
| `laura product-cost-set <item_id> <cost>`     | Set product cost for margin calcs     |
| `laura product-cost-import <file>`            | Import product costs from CSV         |
| `laura product-margin-review`                 | Review margins against targets        |
| `laura product-margin-remediate`              | Auto-fix margin violations            |

## Orders

| Command                                      | Description                          |
|----------------------------------------------|--------------------------------------|
| `laura order-list`                           | List orders with filters              |
| `laura order-detail <order_sn>`              | Get order details                     |
| `laura order-ship <order_sn>`                | Mark order as shipped                 |
| `laura order-ship --tracking <code>`         | Ship with tracking number             |
| `laura order-cancel <order_sn>`              | Cancel an order                       |
| `laura ingest-order-revenue`                 | Ingest revenue data from Shopee       |
| `laura orders-notify-poll`                   | Poll for new orders and notify        |

## Seller Center (Browser Automation)

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura sc products`                  | List products via Seller Center      |
| `laura sc product <item_id>`         | Product detail via Seller Center     |
| `laura sc orders`                    | List orders via Seller Center        |
| `laura sc ship <order_sn>`           | Ship order via Seller Center         |
| `laura sc pending`                   | Show pending shipments               |
| `laura sc balance`                   | Check account balance                |
| `laura sc campaigns`                 | List active campaigns                |
| `laura sc perf`                      | Shop performance metrics             |
| `laura sc violations`                | Listing violation records            |
| `laura sc bulk-price`                | Bulk price update                    |
| `laura sc bulk-stock`               | Bulk stock update                    |
| `laura sc export`                    | Export products to CSV               |
| `laura seller-center-status`         | Check Seller Center auth status      |

## Skills & GOAP

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura skill-list`                   | List all registered skills           |
| `laura skill-run <name>`             | Execute a skill by name              |
| `laura skill-register <name>`        | Register a new skill class           |
| `laura skill-create <name>`          | Scaffold a new skill from template   |
| `laura skill-goap-plan`              | Test GOAP planner interactively      |
| `laura skill-goap-explain`           | Explain a GOAP plan in plain text    |
| `laura skill-history`                | View skill execution history         |
| `laura skill-approve <id>`           | Approve a pending skill action       |
| `laura skill-reject <id>`            | Reject a pending skill action        |
| `laura skill-approval-list`          | List actions pending approval        |
| `laura skill-reload`                 | Reload all skills from registry      |
| `laura skill-test <name>`            | Test a skill in sandbox mode         |
| `laura skill-simulate`               | Simulate skill execution             |
| `laura skill-generate`               | Generate skill from natural language |
| `laura skill-profile <name>`         | Profile skill performance            |
| `laura skill-version <name>`         | Show skill version history           |
| `laura skill-market`                 | Browse community skill marketplace   |
| `laura skill-rollback-learning`      | Rollback GOAP learned costs          |

## Chat & Customer Service

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura chat auto`                    | Toggle auto-responder on/off         |
| `laura chat respond`                 | Classify and respond to a message    |
| `laura chat process`                 | Process all pending messages         |
| `laura chat stats`                   | Show auto-responder statistics       |
| `laura chat history <conversation>`  | Show conversation history            |
| `laura chat template add`            | Add a response template              |
| `laura chat template list`           | List all response templates          |

## Telegram

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura telegram-bot`                 | Run Telegram bot interactively       |
| `laura telegram-setup`               | Configure Telegram bot               |
| `laura telegram-setup-token`         | Update bot token                     |
| `laura telegram-narrator`            | Generate daily narration             |

## Reports & Analytics

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura report-generate`              | Generate daily sales report          |
| `laura report-sales --days 7`        | Sales report for last N days         |
| `laura performance-report`           | Full performance report              |
| `laura export-report`                | Export report to PDF/Excel           |
| `laura schedule-report`              | Schedule recurring reports           |
| `laura competitive-intel-summary`    | Competitor analysis summary          |
| `laura branding-growth-summary`      | Brand growth metrics                 |
| `laura economic-brain-summary`       | Economic/brain analysis              |
| `laura visual-analysis`              | Visual product analysis              |
| `laura store-analysis`               | Comprehensive store analysis         |
| `laura store-health-report`          | Store health check                   |
| `laura anomaly-detect`               | Detect anomalies in metrics          |
| `laura predict-refunds`              | Predict refund probability           |

## Campaigns & Promotions

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura campaign list`                | List active campaigns                |
| `laura campaign bundle`              | Create a bundle deal                 |
| `laura campaign voucher`             | Create a voucher                     |
| `laura campaign auto`                | Suggest campaigns based on metrics   |
| `laura flash-sale-exec create`       | Create a flash sale                  |
| `laura flash-sale-exec list`         | List flash sales                     |
| `laura flash-sale-exec cancel`       | Cancel a flash sale                  |

## Pricing & Automation

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura pricing check`                | Check pricing rules                  |
| `laura pricing auto`                 | Run automated pricing adjustments    |
| `laura ab-auto-promote`              | Auto-promote A/B test winners        |
| `laura ab-test-start`                | Start a new A/B test                 |
| `laura ab-test-status`               | Check A/B test status                |

## Decision Engine

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura decision-status`              | Decision engine status               |
| `laura decision-history`             | Historical decisions                 |
| `laura decision-detail <id>`          | Decision details                     |
| `laura decision-cycle`               | Run a decision cycle                 |
| `laura decision-metrics`             | Decision performance metrics         |
| `laura decision-outcomes`            | Decision outcome analysis            |
| `laura decision-learn`               | Trigger learning from past decisions |
| `laura decision-effectiveness`       | Measure decision effectiveness       |
| `laura decision-similar`             | Find similar past decisions          |

## Monitoring & Health

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura health`                       | Full system health check             |
| `laura doctor`                       | Diagnose configuration issues        |
| `laura metrics-export`               | Export Prometheus metrics            |
| `laura trace`                        | View distributed tracing spans       |
| `laura watchdog`                     | Run watchdog checks                  |
| `laura queue status`                 | Event bus queue status               |
| `laura queue dlq`                    | View dead-letter queue               |
| `laura queue retry`                  | Retry DLQ events                     |

## Memory & Vectors

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura memory-reindex-vectors`       | Rebuild vector indexes               |
| `laura memory-semantic-search`       | Semantic search across memories      |
| `laura learning-summary`             | Learning system summary              |
| `laura learning-stats`               | Learning statistics                  |
| `laura cognitive-memory-save`        | Save to cognitive memory             |
| `laura cognitive-memory-search`      | Search cognitive memory              |
| `laura cognitive-memory-summary`     | Cognitive memory summary             |

## Multi-Store

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura store-list`                   | List configured stores               |
| `laura store-init <name>`            | Initialize a new store               |
| `laura store-summary <name>`         | Store summary                        |

## Deployment & Operations

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura backup`                       | Compressed backup management         |
| `laura audit`                        | Run security audit                   |
| `laura db version`                   | Database schema version              |
| `laura db migrate`                   | Run database migrations              |
| `laura db rollback`                  | Rollback migration                   |
| `laura db list`                      | List all migrations                  |
| `laura export`                       | Export data                          |
| `laura cleanup`                      | Clean up temporary files             |
| `laura token-refresh`                | Refresh Shopee access token          |
| `laura token-get`                    | Get current access token             |
| `laura secrets-rotate`               | Rotate secrets                       |
| `laura tenant list`                  | List tenants (multi-tenant mode)     |

## Webhooks

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura webhook-start`                | Start webhook server                 |
| `laura webhook-drain`               | Drain active webhook connections     |
| `laura shopee-webhook-register`      | Register webhook with Shopee         |

## Advanced

| Command                              | Description                          |
|--------------------------------------|--------------------------------------|
| `laura skill-goap-explain`           | Explain GOAP plan in NL             |
| `laura goal-list`                    | List active goals                    |
| `laura goal-add`                     | Add a new goal                       |
| `laura goal-complete`                | Mark goal complete                   |
| `laura goal-summary`                 | Goal summary                         |
| `laura goal-synthesize`              | Synthesize new goals from data       |
| `laura goal-nl`                      | Add goal via natural language        |
| `laura goal-library`                 | Browse goal library                  |
| `laura plan-store`                   | Store a plan                         |
| `laura plan-diff`                    | Diff two plans                       |
| `laura plan-export`                  | Export plans to file                 |
| `laura plan-import`                  | Import plans from file               |
| `laura plan-template`                | Manage plan templates                |
| `laura plan-schedule`                | Schedule a plan for execution        |
| `laura plan-optimize`                | Optimize an existing plan            |
| `laura plan-heal`                    | Heal broken plans                    |
| `laura plan-explain`                 | Explain a plan in natural language   |
| `laura plan-viz`                     | Visualize a plan as ASCII/HTML       |
| `laura planner-alerts`               | Planner alert configuration          |
| `laura plan-conform`                 | Check plan conformance to policies   |
| `laura cross-sell recommend`         | Cross-sell recommendations           |
| `laura cross-sell top-pairs`         | Top product pairs                    |
| `laura cross-sell bundle`            | Bundle recommendations               |
| `laura browser-run navigate`         | Browser automation (CDP/Playwright)  |
| `laura auto-login`                   | Auto-login to Seller Center          |

## Global Options

These options work with most commands:

| Option               | Description                          |
|----------------------|--------------------------------------|
| `--access-token`     | Override access token                |
| `--shop-id`          | Override shop ID                     |
| `--help`             | Show help for any command            |
