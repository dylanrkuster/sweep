# Sweep

Sweep will be a Gmail add-on that clears a chosen number of unread emails using your written preferences. For each email, Laya chooses **Archive** or **move to Trash**; Sweep marks successful decisions read and saves a summary.

**Status:** The local evaluator and fake mailbox work. The Gmail add-on, Modal worker, and Firestore storage are planned. The current model baseline archives every valid test case, so it is not ready to change a real inbox.

## Code map

Follow the pink arrows. Solid boxes are implemented; dashed boxes are planned. File paths are under `src/sweep/`.

```mermaid
flowchart TB
    start("1. Start local evaluation<br/>evaluation/__main__.py<br/>main()")
    fixtures("2. Load sample emails and answers<br/>testing/fixtures.py<br/>load_messages() and load_cases()")
    runner("3. Run each case<br/>evaluation/runner.py<br/>run_cases()")
    fake("4. Read the fake mailbox<br/>testing/mailbox.py<br/>InMemoryMailbox")
    engine("5. Decide one email<br/>decisions/engine.py<br/>evaluate_decision()")
    context("6. Prepare the model input<br/>decisions/context.py<br/>build_context()")
    laya("7. Score Archive and Trash<br/>decisions/laya.py<br/>LayaRuntime.predict()")
    policy("8. Choose the final action<br/>decisions/policy.py<br/>apply_policy()")
    compare("9. Compare with the answer key<br/>evaluation/runner.py<br/>CaseResult")
    report("10. Save scores and timings<br/>evaluation/reports.py and metrics.py<br/>write_reports()")

    gmail_ui("Gmail add-on · planned<br/>Preferences, number of emails, Sweep button")
    api("Modal API + job · planned<br/>Select unread emails, newest first")
    worker("Modal worker · planned<br/>Process one email at a time")
    model_files("Model files · planned<br/>Modal Volume: weights and tokenizer")
    gmail_api("Gmail API · planned<br/>Archive or Trash, then mark read")
    firestore("Firestore · planned<br/>Save job progress and result counts")

    start --> fixtures --> runner --> fake --> engine --> context --> laya --> policy --> compare --> report
    gmail_ui --> api --> worker
    worker -->|reuse decision code| engine
    model_files --> laya
    policy -->|hosted sweep| gmail_api --> firestore

    linkStyle default stroke:#e46b9f,stroke-width:4px;
    classDef input fill:#414141,stroke:#4c90ea,stroke-width:3px,color:#ffffff;
    classDef work fill:#414141,stroke:#d49418,stroke-width:3px,color:#ffffff;
    classDef output fill:#414141,stroke:#32966e,stroke-width:3px,color:#ffffff;
    classDef planned fill:#303b49,stroke:#74b7ff,stroke-width:3px,stroke-dasharray:7 5,color:#ffffff;
    class fixtures,fake input;
    class start,runner,engine,context,laya,policy,compare work;
    class report output;
    class gmail_ui,api,worker,model_files,gmail_api,firestore planned;
```

The evaluator compares answers only **after** the decision. It does not change Gmail.

[Quickstart](docs/development.md) · [MVP scope](docs/product.md) · [MIT License](LICENSE)
