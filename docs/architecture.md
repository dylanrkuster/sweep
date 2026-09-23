# Sweep architecture

[README](../README.md) · [Detailed explanation](architecture-guide.md) · [Database](database.md)

This is Sweep's **one architecture map**. The overview shows the selected Gmail product; the lower diagrams show code that exists today. Start at **1** and follow the pink arrows. A box names what does the work and where it lives. Click a box to open its explanation or source file.

## Overview

```mermaid
flowchart TB
    ui["1. Sweep button in Gmail<br/>Google · planned"]
    api["2. Accept the request<br/>Python API on Modal · planned"]
    dispatch["3. Select unread emails<br/>Modal job · planned"]
    worker["4. Decide and change one email at a time<br/>Modal worker + Laya · planned"]
    gmail["User's mailbox<br/>Gmail · planned connection"]
    records["Preferences, jobs and results<br/>Google Firestore · planned"]
    model["Laya model files<br/>Modal Volume · planned"]
    local["Built now: local evaluator<br/>Python + synthetic emails<br/>Click to explore current code"]

    ui --> api --> dispatch --> worker
    worker <--> gmail
    api --> records
    worker --> records
    model --> worker
    local -.->|decision code will be reused| worker

    linkStyle default stroke:#d16293,stroke-width:4px;
    classDef google fill:#e8f1ff,stroke:#3772c8,stroke-width:2px,color:#172b4d;
    classDef modal fill:#fff3d6,stroke:#b47700,stroke-width:2px,color:#362500;
    classDef current fill:#e4f5ec,stroke:#27815a,stroke-width:2px,color:#143728;
    class ui,gmail,records google;
    class api,dispatch,worker,model modal;
    class local current;

    click ui href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture-guide.md#the-interface-and-api" "Read about the add-on"
    click api href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture-guide.md#the-interface-and-api" "Read about the API"
    click dispatch href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture-guide.md#follow-one-sweep-from-click-to-result" "Read about job dispatch"
    click worker href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture-guide.md#the-model-is-inside-the-worker" "Read about the worker"
    click gmail href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture-guide.md#what-archive-and-delete-actually-send" "Read about Gmail changes"
    click records href "https://github.com/dylanrkuster/sweep/blob/main/docs/database.md" "Read the database design"
    click model href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture-guide.md#the-model-is-inside-the-worker" "Read about model files"
    click local href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture.md#implemented-evaluator" "Explore implemented code"
```

The future path is **Gmail → Modal API → background job → worker**. The worker will call Laya in its own Python process, change the mailbox through Gmail's API and save progress in Firestore. Only the local evaluator below is implemented. [How the planned system works](architecture-guide.md) · [Explore current code ↓](#implemented-evaluator)

## Implemented evaluator

The local evaluator checks Sweep's decisions against synthetic emails. The numbered boxes trace one case; side boxes supply saved data or scoring.

```mermaid
flowchart TB
    cli["1. Run the evaluator<br/>evaluation/__main__.py<br/>main()"]
    fixtures["2. Load emails and separate answers<br/>testing/fixtures.py<br/>load_messages(), load_cases()"]
    runner["3. Prepare each case<br/>evaluation/runner.py<br/>run_cases()"]
    mailbox["4. Read current and earlier mail<br/>testing/mailbox.py<br/>InMemoryMailbox"]
    engine["5. Decide one email<br/>decisions/engine.py<br/>Click to see one decision"]
    result["6. Compare with expected answer<br/>evaluation/runner.py<br/>CaseResult"]
    reports["7. Save report<br/>evaluation/reports.py<br/>write_reports()"]
    metrics["Score actions and timings<br/>evaluation/metrics.py<br/>summarize(), timing_summary()"]

    cli --> fixtures --> runner --> mailbox --> engine --> result --> reports
    metrics --> reports

    linkStyle default stroke:#d16293,stroke-width:4px;
    classDef input fill:#e8f1ff,stroke:#3772c8,stroke-width:2px,color:#172b4d;
    classDef work fill:#fff3d6,stroke:#b47700,stroke-width:2px,color:#362500;
    classDef output fill:#e4f5ec,stroke:#27815a,stroke-width:2px,color:#143728;
    class fixtures,mailbox input;
    class cli,runner,engine,result work;
    class reports,metrics output;

    click cli href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/evaluation/__main__.py" "Open evaluator entry point"
    click fixtures href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/testing/fixtures.py" "Open fixture loader"
    click runner href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/evaluation/runner.py" "Open case runner"
    click mailbox href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/testing/mailbox.py" "Open fake mailbox"
    click engine href "https://github.com/dylanrkuster/sweep/blob/main/docs/architecture.md#one-decision" "Explore one decision"
    click result href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/evaluation/runner.py" "Open result comparison"
    click reports href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/evaluation/reports.py" "Open report writer"
    click metrics href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/evaluation/metrics.py" "Open scoring functions"
```

Step 3 repeats steps 4–6 for each case. Step 2 loads the separate expected answer, but the runner uses it only at step 6, **after** prediction; Laya never sees it. The [fixture-only command](../src/sweep/testing/__main__.py) checks the sample data without loading Laya. [↑ Overview](#overview) · [One decision ↓](#one-decision)

## One decision

The evaluator calls this same decision code for every email. Side boxes provide the fixed question and verified model files.

```mermaid
flowchart TB
    data["1. Gather email and preferences<br/>domain.py<br/>DecisionInput"]
    engine["2. Coordinate the decision<br/>decisions/engine.py<br/>evaluate_decision()"]
    context["3. Prepare complete model input<br/>decisions/context.py<br/>build_context()"]
    model["4. Score archive and delete<br/>decisions/laya.py<br/>LayaRuntime.predict()"]
    policy["5. Choose final action<br/>decisions/policy.py<br/>apply_policy()"]
    question["Define the two choices<br/>decisions/question.py<br/>decision_question()"]
    files["Verify model files at startup<br/>decisions/artifacts.py<br/>verify_model()"]

    data --> engine --> context --> model --> policy
    question --> context
    files --> model

    linkStyle default stroke:#d16293,stroke-width:4px;
    classDef input fill:#e8f1ff,stroke:#3772c8,stroke-width:2px,color:#172b4d;
    classDef work fill:#fff3d6,stroke:#b47700,stroke-width:2px,color:#362500;
    classDef output fill:#e4f5ec,stroke:#27815a,stroke-width:2px,color:#143728;
    class data,question,files input;
    class engine,context,model work;
    class policy output;

    click data href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/domain.py" "Open shared email types"
    click engine href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/decisions/engine.py" "Open decision coordinator"
    click context href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/decisions/context.py" "Open context builder"
    click model href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/decisions/laya.py" "Open Laya runtime"
    click policy href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/decisions/policy.py" "Open archive/delete policy"
    click question href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/decisions/question.py" "Open model question"
    click files href "https://github.com/dylanrkuster/sweep/blob/main/src/sweep/decisions/artifacts.py" "Open model file checks"
```

`build_context()` rejects invalid or oversized input rather than clipping it. `LayaRuntime.predict()` returns scores. `apply_policy()` checks those scores and chooses an action. This code does **not** change Gmail. [↑ Evaluator](#implemented-evaluator) · [↑ Overview](#overview)

Keep the overview limited to major components. Add a small linked detail diagram when a component needs more explanation, and update the map alongside code changes.
