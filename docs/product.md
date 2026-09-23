# MVP

Sweep is an MIT-licensed Gmail add-on with three controls: written preferences, a number of unread emails, and a **Sweep** button. It shows saved result counts when the job finishes.

- Process up to the requested number of unread emails, newest first, one at a time.
- Laya English chooses **Archive** or **move to Trash**. Both successful actions mark the email read. Trash is recoverable; Sweep never permanently deletes mail.
- Save confirmed results after each email. If a job fails, show completed counts and leave later emails unattempted. Repeated starts and uncertain writes must be handled safely.
- Use a Modal API and worker with Firestore for preferences, jobs, and summaries. These parts and Gmail integration are still planned; only the local evaluator exists today.

Initial limits: up to 1,000 preference characters and a 2,048-token decision context. Labels, billing, and enterprise features are later work.
