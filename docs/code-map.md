# Code map

This map shows **code that exists now**. The [architecture guide](architecture.md) shows the planned Gmail, Modal and Firestore system.

**How to read it:** Start at **1** and follow the pink arrows downward. A box names a Python file, a main function and its job. Arrows show where information goes; side boxes supply supporting information. Blue borders mark inputs, gold marks work, and green marks results. File paths start at `src/sweep/` unless they say `tests/`.

For one sample email, Sweep reads its content, asks Laya whether to archive or delete it, compares the answer with the expected result, then records that result in a report.

## From sample emails to a report

```mermaid
flowchart TB
    evaluate["1. Start evaluation<br/>evaluation/__main__.py<br/>main()"]
    loader["2. Load sample emails and answers<br/>testing/fixtures.py<br/>load_messages() and load_cases()"]
    runner["3. Prepare each case<br/>evaluation/runner.py<br/>run_cases()"]
    mailbox["4. Read the sample mailbox<br/>testing/mailbox.py<br/>InMemoryMailbox"]
    decision["5. Decide archive or delete<br/>decisions/engine.py<br/>evaluate_decision()"]
    metrics["Count correct answers and timings<br/>evaluation/metrics.py<br/>summarize() and timing_summary()"]
    reports["6. Save the report<br/>evaluation/reports.py<br/>write_reports()"]

    evaluate --> loader --> runner --> mailbox --> decision --> reports
    metrics --> reports

    linkStyle default stroke:#d16293,stroke-width:4px;

    classDef input fill:#e8f1ff,stroke:#3772c8,stroke-width:2px,color:#172b4d;
    classDef work fill:#fff3d6,stroke:#b47700,stroke-width:2px,color:#362500;
    classDef output fill:#e4f5ec,stroke:#27815a,stroke-width:2px,color:#143728;
    class loader,mailbox input;
    class evaluate,runner,decision work;
    class reports,metrics output;
```

The samples live in `tests/fixtures/`. Step 3 repeats steps 4–5 for each case. It compares the decision with the separate answer **after** Laya runs; Laya never sees the expected answer. The separate fixture-check command, `testing/__main__.py:main()`, checks the sample data without running the model.

## One decision

```mermaid
flowchart TB
    data["1. Gather the input<br/>domain.py<br/>DecisionInput"]
    engine["2. Coordinate the decision<br/>decisions/engine.py<br/>evaluate_decision()"]
    context["3. Prepare complete model input<br/>decisions/context.py<br/>build_context()"]
    model["4. Score both choices<br/>decisions/laya.py<br/>LayaRuntime.predict()"]
    policy["5. Choose the final action<br/>decisions/policy.py<br/>apply_policy()"]
    question["Defines archive/delete choices<br/>decisions/question.py<br/>decision_question()"]
    files["Checks model files at startup<br/>decisions/artifacts.py<br/>verify_model()"]

    data --> engine --> context --> model --> policy
    question --> context
    files --> model

    linkStyle default stroke:#d16293,stroke-width:4px;

    classDef inputNode fill:#e8f1ff,stroke:#3772c8,stroke-width:2px,color:#172b4d;
    classDef work fill:#fff3d6,stroke:#b47700,stroke-width:2px,color:#362500;
    classDef output fill:#e4f5ec,stroke:#27815a,stroke-width:2px,color:#143728;
    class data,question,files inputNode;
    class engine,context,model work;
    class policy output;
```

`build_context()` either returns the complete input within the token limit or reports an error; it never silently clips an email. `LayaRuntime.predict()` returns scores, and `apply_policy()` turns valid scores into an archive/delete decision. This path **does not change a mailbox**.

## Find the code

| File | Main responsibilities |
| --- | --- |
| [domain.py](../src/sweep/domain.py) | `Message` and `Attachment` describe email facts; `DecisionInput` carries only data available to the model. |
| [testing/fixtures.py](../src/sweep/testing/fixtures.py) | `load_messages()` validates mail; `load_cases()` validates expected answers and dataset splits. |
| [testing/mailbox.py](../src/sweep/testing/mailbox.py) | `InMemoryMailbox.get_message()` finds one email; `get_prior_thread_messages()` finds strictly earlier mail in its thread. `reset()` restores the starting snapshot. |
| [testing/__main__.py](../src/sweep/testing/__main__.py) | `main()` checks fixtures and builds sample decision inputs without running the model. |
| [decisions/engine.py](../src/sweep/decisions/engine.py) | `evaluate_decision()` runs context building, prediction and policy in order. |
| [decisions/context.py](../src/sweep/decisions/context.py) | `build_context()` validates preferences and mail, prepares exact model tokens and enforces the limit. |
| [decisions/question.py](../src/sweep/decisions/question.py) | `decision_question()` defines the archive/delete question sent to Laya. |
| [decisions/artifacts.py](../src/sweep/decisions/artifacts.py) | `download_model()` explicitly fetches pinned files; `verify_model()` checks them locally. |
| [decisions/laya.py](../src/sweep/decisions/laya.py) | `LayaRuntime.__init__()` verifies and loads the model; `predict()` scores the prepared choices. |
| [decisions/policy.py](../src/sweep/decisions/policy.py) | `check_threshold()` validates the setting; `apply_policy()` validates scores and selects the action. |
| [evaluation/__main__.py](../src/sweep/evaluation/__main__.py) | `main()` loads fixtures and Laya, runs cases, then writes a report. |
| [evaluation/runner.py](../src/sweep/evaluation/runner.py) | `run_cases()` builds inputs from the fake mailbox and joins predictions to expected answers afterward. |
| [evaluation/metrics.py](../src/sweep/evaluation/metrics.py) | `summarize()` counts decisions/errors; `timing_summary()` measures inference and context timing. |
| [evaluation/reports.py](../src/sweep/evaluation/reports.py) | `write_reports()` saves Markdown, JSON and CSV results without email bodies. |

Update this map when the responsibilities or connections above change. The [development guide](development.md) has the commands for running each path.
